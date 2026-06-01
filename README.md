# Fueled's Open Source Metrics

[![Monthly Stats Collection](https://github.com/Fueled/oss-metrics/actions/workflows/monthly-stats.yml/badge.svg)](https://github.com/Fueled/oss-metrics/actions/workflows/monthly-stats.yml) [![pages-build-deployment](https://github.com/Fueled/oss-metrics/actions/workflows/pages/pages-build-deployment/badge.svg)](https://github.com/Fueled/oss-metrics/actions/workflows/pages/pages-build-deployment)

> Automated monthly metrics for Fueled's open source projects.

## Overview

A self-contained OSS metrics tracker for Fueled's public GitHub repos, their WordPress.org plugins, and npm packages. Runs monthly via GitHub Actions, stores data as JSON, and serves a static dashboard via GitHub Pages.

**Dashboard:** https://fueled.github.io/oss-metrics/

## How it works

1. On the 1st of each month at 6AM UTC, a GitHub Action runs `scripts/collect_stats.py`
2. The script fetches stars, forks, watchers, dependents, and release counts from the GitHub API, plus active installs, downloads, and ratings from the WordPress.org Plugins API, plus monthly downloads and dependents counts from the npm public APIs
3. Results are written to `data/stats/YYYY-MM.json` and committed back to the repo
4. GitHub Pages is triggered to rebuild the static dashboard
5. A Slack notification is sent to `#oss-practice` once the dashboard is live (requires `SLACK_WEBHOOK_URL` repo secret)
6. The static dashboard at `index.html` loads those JSON files via `fetch()` and renders charts and tables

## Setup

### 1. Add the `GH_TOKEN` secret

The collection script requires a GitHub Personal Access Token to raise the API rate limit from 60 to 5,000 requests/hour.

This repo uses the org-level secret `BOT_PUBLIC_GITHUB_TOKEN` (a PAT with `public_repo` read-only scope). No additional secret setup is needed — the org secret is inherited automatically.

### 2. Enable GitHub Pages

1. Go to **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/` (root)
4. Save — GitHub will publish the dashboard at `https://fueled.github.io/oss-metrics/`

### 3. (Optional) Add the Slack webhook secret

To receive a Slack notification in `#oss-practice` after each monthly run:

1. Create an incoming webhook for the Fueled Slack workspace pointing at `#oss-practice`
2. Add the webhook URL as a repo secret named `SLACK_WEBHOOK_URL`

The workflow step is skipped gracefully if the secret is not set.

### 4. Trigger the first run

Go to **Actions → Monthly Stats Collection → Run workflow** to collect the first month of data immediately.

## Running locally

```bash
# Install dependencies
pip install -r scripts/requirements.txt

# Run for the previous calendar month (default)
GH_TOKEN=your_token python scripts/collect_stats.py

# Run for a specific month (backfill)
GH_TOKEN=your_token python scripts/collect_stats.py --period 2025-03
```

Output is written to `data/stats/YYYY-MM.json` and `data/stats/index.json` is updated.

## Adding repos

Edit `data/config.yml`. Each entry supports GitHub, WordPress.org, and npm tracking:

```yaml
repos:
  - github: "owner/repo"              # GitHub repo slug (exact casing)
    label: "Human-readable name"
    wordpress_slug: "plugin-slug"     # WordPress.org plugin slug, or null
    npm_slug: "@scope/package-name"   # npm package name, or null
```

Set any slug to `null` if the project is not published on that platform.

## Repo structure

```
oss-metrics/
├── .github/
│   └── workflows/
│       └── monthly-stats.yml   # Cron + manual trigger
├── data/
│   ├── config.yml              # Which repos to track
│   └── stats/
│       ├── index.json          # Manifest of available monthly files
│       └── YYYY-MM.json        # One file per month (auto-committed)
├── scripts/
│   ├── collect_stats.py        # Data collection script
│   ├── backfill.py             # One-time backfill from XLSX spreadsheet
│   └── requirements.txt
├── index.html                  # Self-contained dashboard (GitHub Pages root)
└── README.md
```

## Data format

Each monthly file (`data/stats/YYYY-MM.json`) looks like:

```json
{
  "collected_at": "2025-05-01T06:05:00Z",
  "period": "2025-04",
  "repos": [
    {
      "github": "10up/ads-txt",
      "label": "Ads.txt Manager",
      "github_stats": {
        "stars": 1234,
        "watchers": 56,
        "forks": 78,
        "releases_this_month": 2,
        "used_by_repositories": 890,
        "used_by_packages": 12,
        "used_by_total": 902
      },
      "wordpress_stats": {
        "active_installs": 50000,
        "total_downloads": 250000,
        "rating": 92,
        "num_ratings": 340
      },
      "npm_stats": {
        "monthly_downloads": 18500,
        "dependents": 42
      }
    }
  ]
}
```

- `wordpress_stats` is `null` for repos not published on WordPress.org
- `npm_stats` is `null` for repos not published on npm
- Any metric that fails to fetch is stored as `null` rather than aborting the run
- WordPress ratings are stored on a 0–100 scale (matching the WordPress.org API) and converted to 0–5 for display on the dashboard

## Like what you see?

[![Work with the 10up WordPress Practice at Fueled](https://github.com/10up/.github/blob/trunk/profile/10up-github-banner.jpg)](http://10up.com/contact/)
