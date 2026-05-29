# fueled/oss-metrics

A self-contained OSS metrics tracker for Fueled's public GitHub repos and their WordPress.org plugins. Runs monthly via GitHub Actions, stores data as JSON, and serves a static dashboard via GitHub Pages.

**Dashboard:** https://fueled.github.io/oss-metrics/

---

## How it works

1. On the 1st of each month at 6AM UTC, a GitHub Action runs `scripts/collect_stats.py`
2. The script fetches stars, forks, watchers, dependents, and release counts from the GitHub API, plus active installs, downloads, and ratings from the WordPress.org Plugins API
3. Results are written to `data/stats/YYYY-MM.json` and committed back to the repo
4. The static dashboard at `dashboard/index.html` loads those JSON files via `fetch()` and renders charts and tables

---

## Setup

### 1. Add the `GH_TOKEN` secret

The collection script requires a GitHub Personal Access Token to raise the API rate limit from 60 to 5,000 requests/hour.

This repo uses the org-level secret `BOT_PUBLIC_GITHUB_TOKEN` (a PAT with `public_repo` read-only scope). No additional secret setup is needed — the org secret is inherited automatically.

### 2. Enable GitHub Pages

1. Go to **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/dashboard`
4. Save — GitHub will publish the dashboard at `https://fueled.github.io/oss-metrics/`

### 3. Trigger the first run

Go to **Actions → Monthly Stats Collection → Run workflow** to collect the first month of data immediately.

---

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

---

## Adding repos

Edit `data/config.yml`. Each entry needs:

```yaml
repos:
  - github: "owner/repo"        # GitHub repo slug (exact casing)
    label: "Human-readable name"
    wordpress_slug: "plugin-slug"  # or null if not a WP plugin
```

---

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
│   └── requirements.txt
├── dashboard/
│   └── index.html              # Self-contained dashboard
└── README.md
```

---

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
      }
    }
  ]
}
```

Any metric that fails to fetch is stored as `null` rather than aborting the run.
