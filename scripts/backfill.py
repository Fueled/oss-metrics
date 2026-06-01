#!/usr/bin/env python3
"""
Backfill historical OSS metrics from an XLSX spreadsheet.

Usage:
    python scripts/backfill.py path/to/spreadsheet.xlsx
    python scripts/backfill.py path/to/spreadsheet.xlsx --overwrite
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
STATS_DIR  = REPO_ROOT / "data" / "stats"
INDEX_PATH = STATS_DIR / "index.json"

# ── Sheet → (github_slug, display_label, wordpress_slug | None) ──────────────
# wordpress_slug is the WP.org plugin slug; None = not a WP plugin.
# Rating in the spreadsheet is on a 0–5 scale; we multiply by 20 before storing
# so it matches the 0–100 scale returned by the live WordPress.org API.
SHEET_MAP = {
    "Ads.txt Manager":                 ("10up/ads-txt",                                   "Ads.txt Manager",                        "ads-txt"),
    "Ad Refresh Control":              ("10up/Ad-Refresh-Control",                         "Ad Refresh Control",                     "ad-refresh-control"),
    "AI Provider for Ollama":          ("Fueled/ai-provider-for-ollama",                   "AI Provider for Ollama",                 "ai-provider-for-ollama"),
    "Autoshare for Twitter":           ("10up/autoshare-for-twitter",                      "Autoshare for Twitter",                  "autoshare-for-twitter"),
    "Block for Apple Maps":            ("10up/maps-block-apple",                           "Apple Maps Block",                       "maps-block-apple"),
    "Block Components":                ("10up/block-components",                           "Block Components",                       None),
    "ClassifAI":                       ("10up/classifai",                                  "ClassifAI",                              None),
    "Convert to Blocks":               ("10up/convert-to-blocks",                          "Convert to Blocks",                      "convert-to-blocks"),
    "Django-init":                     ("Fueled/django-init",                              "Django Init",                            None),
    "Distributor":                     ("10up/distributor",                                "Distributor",                            None),
    "Eight Day Week":                  ("10up/eight-day-week",                             "Eight Day Week",                         "eight-day-week-print-workflow"),
    "ElasticPress":                    ("10up/ElasticPress",                               "ElasticPress",                           "elasticpress"),
    "ElasticPress Labs":               ("10up/ElasticPressLabs",                           "ElasticPress Labs",                      None),
    "Embed Figma Block":               ("10up/embed-block-figma",                          "Figma Block",                            "embed-block-figma"),
    "Engineering Best Practices":      ("10up/Engineering-Best-Practices",                 "Engineering Best Practices",             None),
    "Fastlane_Plugin":                 ("Fueled/fastlane-plugin-fueled",                   "Fueled Fastlane Plugin",                 None),
    "Figma_to_WordPress_JSON_Exporte": ("10up/figma-to-wordpress-theme-json-exporter",     "Figma to WordPress theme.json Exporter", None),
    "FueledUtils":                     ("Fueled/ios-utilities",                            "FueledUtils",                            None),
    "GitHub Actions":                  ("10up/actions-wordpress",                          "GitHub Actions",                         None),
    "GHA Plugin Deploy":               ("10up/action-wordpress-plugin-deploy",             "GHA Plugin Deploy",                      None),
    "GHA Plugin Build":                ("10up/action-wordpress-plugin-build-zip",          "GHA Plugin Build",                       None),
    "GHA Assets Update":               ("10up/action-wordpress-plugin-asset-update",       "GHA Assets Update",                      None),
    "GHA Repo Automator":              ("10up/action-repo-automator",                      "GHA Repo Automator",                     None),
    "GHA WPCS":                        ("10up/wpcs-action",                                "GHA WPCS",                               None),
    "GHA WP Scanner":                  ("10up/wp-scanner-action",                          "GHA WP Scanner",                         None),
    "Gutenberg Best Practices":        ("10up/gutenberg-best-practices",                   "Gutenberg Best Practices",               None),
    "HeadstartWP":                     ("10up/headstartwp",                                "HeadstartWP",                            None),
    "Insecure Content Warning":        ("10up/insecure-content-warning",                   "Insecure Content Warning",               "insecure-content-warning"),
    "Insert Special Characters":       ("10up/insert-special-characters",                  "Insert Special Characters",              "insert-special-characters"),
    "Microsoft Azure Storage":         ("10up/windows-azure-storage",                      "Microsoft Azure Storage",                "windows-azure-storage"),
    "Open Source Best Practices":      ("10up/Open-Source-Best-Practices",                 "Open Source Best Practices",             None),
    "Publisher Media Kit":             ("10up/publisher-media-kit",                        "Publisher Media Kit",                    "publisher-media-kit"),
    "Restricted Site Access":          ("10up/restricted-site-access",                     "Restricted Site Access",                 "restricted-site-access"),
    "Safe Redirect Manager":           ("10up/safe-redirect-manager",                      "Safe Redirect Manager",                  "safe-redirect-manager"),
    "Safe SVG":                        ("10up/safe-svg",                                   "Safe SVG",                               "safe-svg"),
    "Simple Local Avatars":            ("10up/simple-local-avatars",                       "Simple Local Avatars",                   "simple-local-avatars"),
    "Simple Page Ordering":            ("10up/simple-page-ordering",                       "Simple Page Ordering",                   "simple-page-ordering"),
    "Simple Podcasting":               ("10up/simple-podcasting",                          "Simple Podcasting",                      "simple-podcasting"),
    "ToolKit":                         ("10up/10up-toolkit",                               "10up Toolkit",                           None),  # npm_slug: 10up-toolkit
    "Typescript_Standards":            ("Fueled/typescript-standards",                     "Typescript Standards",                   None),
    "Winamp Block":                    ("10up/retro-winamp-block",                         "Winamp Block",                           "retro-winamp-block"),
    "WP_Framework":                    ("10up/wp-framework",                               "WP Framework",                           None),
    "WP_Hooks_Documentor":             ("10up/wp-hooks-documentor",                        "WP Hooks Documentor",                    None),
    "WP_Mock":                         ("10up/wp_mock",                                    "WP Mock",                                None),
    "WP Scaffold":                     ("10up/wp-scaffold",                                "WP Scaffold",                            None),
}

# Row indices within each project sheet (0-based, row 0 = header)
ROWS = {
    "used_by":      1,
    "watchers":     2,
    "stars":        3,
    "forks":        4,
    "releases":     5,
    "wp_downloads": 6,
    "wp_installs":  7,
    "wp_rating":    8,   # 0–5 scale in spreadsheet; stored as 0–100
}


def safe_int(val):
    try:
        s = str(val)
        if s in ("nan", "NaT", "NaN", "None", ""):
            return None
        return int(float(s))
    except (ValueError, TypeError):
        return None


def safe_float(val):
    try:
        s = str(val)
        if s in ("nan", "NaT", "NaN", "None", ""):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def extract_period(date_val):
    """Return 'YYYY-MM' from a date column header value, or None if unparseable."""
    try:
        s = str(date_val)
        if s in ("nan", "NaT", "NaN", "None", ""):
            return None
        if hasattr(date_val, "strftime"):
            return date_val.strftime("%Y-%m")
        return s[:7]  # e.g. "2026-01-01 00:00:00" → "2026-01"
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Backfill historical OSS metrics from XLSX.")
    parser.add_argument("xlsx", help="Path to the source XLSX file")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing JSON files (default: skip them)")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"ERROR: File not found: {xlsx_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {xlsx_path.name} …")
    xl = pd.read_excel(xlsx_path, sheet_name=None, header=None, engine="openpyxl")

    project_sheets = [s for s in xl.keys() if s != "SUMMARY"]
    print(f"Found {len(project_sheets)} project sheets")

    # Discover month columns from the first project sheet
    first_df = xl[project_sheets[0]]
    period_cols = {}  # col_index → "YYYY-MM"
    for col_idx in first_df.columns[1:]:
        period = extract_period(first_df.iloc[0, first_df.columns.get_loc(col_idx)])
        if period:
            period_cols[col_idx] = period

    periods = sorted(period_cols.values())
    print(f"Periods found: {periods}\n")

    # Build per-period repo lists
    by_period = {p: [] for p in periods}

    for sheet_name in project_sheets:
        if sheet_name not in SHEET_MAP:
            print(f"  WARN: No mapping for sheet '{sheet_name}' — skipping")
            continue

        github_slug, label, wp_slug = SHEET_MAP[sheet_name]
        df = xl[sheet_name]
        col_locs = {col: df.columns.get_loc(col) for col in df.columns}

        for col_idx, period in period_cols.items():
            if col_idx not in col_locs:
                continue  # this sheet has fewer columns than the first
            pos = col_locs[col_idx]

            def cell(row):
                return df.iloc[row, pos]

            used_by  = safe_int(cell(ROWS["used_by"]))
            watchers = safe_int(cell(ROWS["watchers"]))
            stars    = safe_int(cell(ROWS["stars"]))
            forks    = safe_int(cell(ROWS["forks"]))
            releases = safe_int(cell(ROWS["releases"]))

            github_stats = {
                "stars":                stars,
                "watchers":             watchers,
                "forks":                forks,
                "releases_this_month":  releases,
                "used_by_repositories": used_by,
                "used_by_packages":     None,   # not tracked in spreadsheet
                "used_by_total":        used_by,
            }

            wp_stats = None
            if wp_slug is not None:
                downloads = safe_int(cell(ROWS["wp_downloads"]))
                installs  = safe_int(cell(ROWS["wp_installs"]))
                rating_05 = safe_float(cell(ROWS["wp_rating"]))
                # Convert 0–5 → 0–100 to match live API storage
                rating    = round(rating_05 * 20, 1) if rating_05 is not None else None

                if any(v is not None for v in [downloads, installs, rating]):
                    wp_stats = {
                        "active_installs": installs,
                        "total_downloads": downloads,
                        "rating":          rating,
                        "num_ratings":     None,  # not tracked in spreadsheet
                    }

            by_period[period].append({
                "github":          github_slug,
                "label":           label,
                "github_stats":    github_stats,
                "wordpress_stats": wp_stats,
            })

    # Write JSON files
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    written  = []
    skipped  = []

    for period in periods:
        out_path = STATS_DIR / f"{period}.json"
        if out_path.exists() and not args.overwrite:
            print(f"  SKIP  {period}.json (already exists; use --overwrite to replace)")
            skipped.append(f"{period}.json")
            continue

        payload = {
            "collected_at": f"{period}-01T00:00:00Z",
            "period":       period,
            "repos":        by_period[period],
        }
        out_path.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"  WROTE {period}.json  ({len(by_period[period])} repos)")
        written.append(f"{period}.json")

    # Update index.json
    existing = {"files": []}
    if INDEX_PATH.exists():
        try:
            existing = json.loads(INDEX_PATH.read_text())
        except Exception:
            pass

    all_files = sorted(set(existing.get("files", [])) | set(written) | set(skipped))
    INDEX_PATH.write_text(json.dumps({"files": all_files}, indent=2) + "\n")

    print(f"\nDone. Written: {len(written)}  Skipped: {len(skipped)}")
    print(f"index.json now references {len(all_files)} file(s): {all_files}")


if __name__ == "__main__":
    main()
