#!/usr/bin/env python3
"""Collect monthly OSS metrics from GitHub and WordPress.org APIs."""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).parent.parent
CONFIG_PATH = REPO_ROOT / "data" / "config.yml"
STATS_DIR = REPO_ROOT / "data" / "stats"
INDEX_PATH = STATS_DIR / "index.json"

GH_API      = "https://api.github.com"
WP_API      = "https://api.wordpress.org/plugins/info/1.0/{slug}.json"
NPM_DL_API  = "https://api.npmjs.org/downloads/point/{start}:{end}/{package}"
NPM_DEP_API = "https://registry.npmjs.org/-/v1/search?text=dependencies:{package}&size=0"

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds; doubles each attempt


def gh_headers():
    token = os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        print("WARNING: GH_TOKEN not set — rate limited to 60 req/hour", file=sys.stderr)
    return headers


def fetch_with_retry(url: str, *, headers=None, params=None, timeout=30) -> requests.Response:
    """GET a URL with exponential-backoff retries on transient errors (429, 5xx, timeout)."""
    delay = RETRY_BACKOFF
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = int(r.headers.get("Retry-After", delay))
                print(f"  WARN: HTTP {r.status_code} on attempt {attempt}/{MAX_RETRIES} "
                      f"for {url} — retrying in {retry_after}s", file=sys.stderr)
                time.sleep(retry_after)
                delay *= 2
                continue
            return r
        except requests.exceptions.Timeout as e:
            last_exc = e
            print(f"  WARN: Timeout on attempt {attempt}/{MAX_RETRIES} for {url} "
                  f"— retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
        except requests.exceptions.RequestException as e:
            last_exc = e
            print(f"  WARN: Request error on attempt {attempt}/{MAX_RETRIES} for {url}: {e} "
                  f"— retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise requests.exceptions.RequestException(
        f"Failed after {MAX_RETRIES} attempts: {last_exc}"
    )


def period_bounds(period: str):
    """Return (start, end) as aware datetimes for the given YYYY-MM period."""
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def previous_month() -> str:
    today = datetime.now(timezone.utc)
    first_of_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_of_prev = first_of_this_month - timedelta(seconds=1)
    return last_of_prev.strftime("%Y-%m")


def fetch_github_repo(owner_repo: str) -> dict | None:
    url = f"{GH_API}/repos/{owner_repo}"
    try:
        r = fetch_with_retry(url, headers=gh_headers())
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ERROR fetching repo {owner_repo}: {e}", file=sys.stderr)
        return None


def fetch_releases_count(owner_repo: str, period: str) -> int | None:
    start, end = period_bounds(period)
    url = f"{GH_API}/repos/{owner_repo}/releases"
    count = 0
    page = 1
    try:
        while True:
            r = fetch_with_retry(url, headers=gh_headers(), params={"per_page": 100, "page": page})
            r.raise_for_status()
            releases = r.json()
            if not releases:
                break
            for rel in releases:
                pub = rel.get("published_at")
                if not pub:
                    continue
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if start <= pub_dt < end:
                    count += 1
                elif pub_dt < start:
                    return count
            if len(releases) < 100:
                break
            page += 1
        return count
    except Exception as e:
        print(f"  ERROR fetching releases for {owner_repo}: {e}", file=sys.stderr)
        return None


def fetch_dependents(owner_repo: str) -> tuple[int | None, int | None]:
    """Scrape the dependents page for tab badge counts. Returns (repos, packages)."""
    url = f"https://github.com/{owner_repo}/network/dependents"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; oss-metrics-bot/1.0)",
        "Accept": "text/html",
    }
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    try:
        r = fetch_with_retry(url, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        repos_count = None
        packages_count = None

        # Tab links contain text like "Repositories\n  890\n" or badge spans
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True)

            if "dependents_type=REPOSITORY" in href or (
                "network/dependents" in href and "PACKAGE" not in href
            ):
                nums = re.findall(r"[\d,]+", text)
                if nums:
                    repos_count = int(nums[-1].replace(",", ""))

            if "dependents_type=PACKAGE" in href:
                nums = re.findall(r"[\d,]+", text)
                if nums:
                    packages_count = int(nums[-1].replace(",", ""))

        # Fallback: look for Counter/badge spans near tab headings
        if repos_count is None and packages_count is None:
            for span in soup.find_all("span", class_=re.compile(r"Counter|badge", re.I)):
                parent_text = span.parent.get_text(" ", strip=True).lower() if span.parent else ""
                val_text = span.get_text(strip=True).replace(",", "")
                if not val_text.isdigit():
                    continue
                val = int(val_text)
                if "repositor" in parent_text and repos_count is None:
                    repos_count = val
                elif "package" in parent_text and packages_count is None:
                    packages_count = val

        if repos_count is None and packages_count is None:
            print(f"  WARN: Could not parse dependents for {owner_repo} — "
                  f"GitHub may have changed their markup. Storing null.", file=sys.stderr)

        return repos_count, packages_count
    except Exception as e:
        print(f"  ERROR scraping dependents for {owner_repo}: {e}", file=sys.stderr)
        return None, None


def fetch_npm(package: str, period: str) -> dict | None:
    """Fetch monthly downloads and dependent count from npm public APIs."""
    start, end = period_bounds(period)
    start_str = start.strftime("%Y-%m-%d")
    end_str   = (end - timedelta(seconds=1)).strftime("%Y-%m-%d")
    try:
        dl_url = NPM_DL_API.format(start=start_str, end=end_str, package=package)
        dl_r = fetch_with_retry(dl_url)
        dl_r.raise_for_status()
        downloads = dl_r.json().get("downloads")

        dep_url = NPM_DEP_API.format(package=package)
        dep_r = fetch_with_retry(dep_url)
        dep_r.raise_for_status()
        dependents = dep_r.json().get("total")

        return {
            "monthly_downloads": downloads,
            "dependents": dependents,
        }
    except Exception as e:
        print(f"  ERROR fetching npm stats for {package}: {e}", file=sys.stderr)
        return None


def fetch_wordpress(slug: str) -> dict | None:
    url = WP_API.format(slug=slug)
    try:
        r = fetch_with_retry(url)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return None
        return {
            "active_installs": data.get("active_installs"),
            "total_downloads": data.get("downloaded"),
            "rating": data.get("rating"),
            "num_ratings": data.get("num_ratings"),
        }
    except Exception as e:
        print(f"  ERROR fetching WordPress stats for {slug}: {e}", file=sys.stderr)
        return None


def collect_repo(repo_cfg: dict, period: str) -> dict:
    owner_repo = repo_cfg["github"]
    label      = repo_cfg["label"]
    wp_slug    = repo_cfg.get("wordpress_slug")
    npm_slug   = repo_cfg.get("npm_slug")

    print(f"\n{'─'*60}")
    print(f"  {label} ({owner_repo})")
    print(f"{'─'*60}")

    gh_data = fetch_github_repo(owner_repo)
    releases = fetch_releases_count(owner_repo, period)
    dep_repos, dep_pkgs = fetch_dependents(owner_repo)

    if gh_data:
        github_stats = {
            "stars": gh_data.get("stargazers_count"),
            "watchers": gh_data.get("subscribers_count"),
            "forks": gh_data.get("forks_count"),
            "releases_this_month": releases,
            "used_by_repositories": dep_repos,
            "used_by_packages": dep_pkgs if dep_pkgs is not None else 0,
            "used_by_total": (dep_repos or 0) + (dep_pkgs or 0)
            if dep_repos is not None
            else None,
        }
    else:
        github_stats = {
            "stars": None,
            "watchers": None,
            "forks": None,
            "releases_this_month": releases,
            "used_by_repositories": dep_repos,
            "used_by_packages": dep_pkgs,
            "used_by_total": None,
        }

    print(f"  Stars: {github_stats['stars']}  Forks: {github_stats['forks']}  "
          f"Watchers: {github_stats['watchers']}")
    print(f"  Releases this month: {github_stats['releases_this_month']}")
    print(f"  Used by repos: {dep_repos}  packages: {dep_pkgs}")

    wp_stats = None
    if wp_slug:
        wp_stats = fetch_wordpress(wp_slug)
        if wp_stats:
            print(f"  WP active installs: {wp_stats['active_installs']}  "
                  f"downloads: {wp_stats['total_downloads']}  "
                  f"rating: {wp_stats['rating']}/100 ({wp_stats['num_ratings']} ratings)")

    npm_stats = None
    if npm_slug:
        npm_stats = fetch_npm(npm_slug, period)
        if npm_stats:
            print(f"  npm monthly downloads: {npm_stats['monthly_downloads']}  "
                  f"dependents: {npm_stats['dependents']}")

    return {
        "github":          owner_repo,
        "label":           label,
        "github_stats":    github_stats,
        "wordpress_stats": wp_stats,
        "npm_stats":       npm_stats,
    }


def update_index(filename: str):
    index = {"files": []}
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text())
        except Exception:
            pass
    if filename not in index["files"]:
        index["files"].append(filename)
        index["files"].sort()
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Collect monthly OSS metrics.")
    parser.add_argument(
        "--period",
        metavar="YYYY-MM",
        help="Month to collect stats for (default: previous calendar month)",
    )
    args = parser.parse_args()

    period = args.period if args.period else previous_month()

    # Validate period format
    if not re.match(r"^\d{4}-\d{2}$", period):
        print(f"ERROR: --period must be YYYY-MM, got: {period}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  OSS Metrics Collection — period: {period}")
    print(f"{'='*60}")

    config = yaml.safe_load(CONFIG_PATH.read_text())
    repos_cfg = config.get("repos", [])

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = []
    for repo_cfg in repos_cfg:
        result = collect_repo(repo_cfg, period)
        results.append(result)

    output = {
        "collected_at": collected_at,
        "period": period,
        "repos": results,
    }

    STATS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = STATS_DIR / f"{period}.json"
    out_file.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\n✓ Wrote {out_file.relative_to(REPO_ROOT)}")

    update_index(f"{period}.json")
    print(f"✓ Updated index.json")

    print(f"\n{'='*60}")
    print("  Collection complete")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
