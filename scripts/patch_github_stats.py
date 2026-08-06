#!/usr/bin/env python3
"""
Patch null GitHub REST API fields in an existing stats JSON file.

Fetches stars, watchers, forks, and releases_this_month from the GitHub API
for repos where those fields are null, leaving wordpress_stats and npm_stats
untouched.

Usage:
    GH_TOKEN=<token> python scripts/patch_github_stats.py data/stats/2026-05.json
"""

import json
import os
import sys
from pathlib import Path

# Ensure we can import from the same scripts directory
sys.path.insert(0, str(Path(__file__).parent))
from collect_stats import (
    fetch_github_repo,
    fetch_releases_count,
    fetch_dependents,
    gh_headers,
)

REPO_ROOT = Path(__file__).parent.parent


def patch(stats_path: Path):
    data = json.loads(stats_path.read_text())
    period = data["period"]
    repos = data["repos"]

    patched = 0
    for repo in repos:
        gs = repo["github_stats"]
        if gs.get("stars") is not None:
            print(f"  SKIP {repo['github']} — already has stars={gs['stars']}")
            continue

        owner_repo = repo["github"]
        print(f"\n  Patching {owner_repo} ...")

        gh_data = fetch_github_repo(owner_repo)
        releases = fetch_releases_count(owner_repo, period)
        dep_repos, dep_pkgs = fetch_dependents(owner_repo)

        if gh_data:
            gs["stars"] = gh_data.get("stargazers_count")
            gs["watchers"] = gh_data.get("subscribers_count")
            gs["forks"] = gh_data.get("forks_count")
        gs["releases_this_month"] = releases
        if dep_repos is not None:
            gs["used_by_repositories"] = dep_repos
            gs["used_by_packages"] = dep_pkgs if dep_pkgs is not None else 0
            gs["used_by_total"] = dep_repos + (dep_pkgs or 0)

        print(f"    stars={gs['stars']}  forks={gs['forks']}  "
              f"watchers={gs['watchers']}  releases={releases}  "
              f"used_by={gs['used_by_total']}")
        patched += 1

    stats_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"\n✓ Patched {patched} repos in {stats_path.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path/to/YYYY-MM.json>", file=sys.stderr)
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"ERROR: {target} not found", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("GH_TOKEN"):
        print("WARNING: GH_TOKEN not set — rate limited to 60 req/hour", file=sys.stderr)

    patch(target)
