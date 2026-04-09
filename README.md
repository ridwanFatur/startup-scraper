# Startup Data Scraper

Collects startup and company data from multiple public sources and merges the results into a single JSON file.

## Requirements

Python 3.10+ is required.

Install dependencies:

```bash
pip install requests beautifulsoup4 lxml
```

## Running the script

### Default run (pre-selected working sources)

```bash
python startup_scraper.py
```

This runs the 6 sources that are known to work without API keys:

| Source | Description |
|---|---|
| `github_trending` | Trending repositories on GitHub |
| `hn_hiring` | Hacker News "Who is Hiring?" thread companies |
| `crunchbase_odm` | Crunchbase open dataset (CSV on GitHub) |
| `wikidata` | Technology companies from Wikidata SPARQL |
| `techcrunch_rss` | Companies mentioned in TechCrunch RSS feed |
| `wellfound` | Startup listings from Wellfound (AngelList) |

### Run all 12 sources

Edit the bottom of `startup_scraper.py` and set `success_websites=None`:

```python
if __name__ == "__main__":
    main(success_websites=None)
```

### Run specific sources

Pass a list of source names:

```python
if __name__ == "__main__":
    main(success_websites=["github_trending", "techcrunch_rss"])
```

Or import and call from another script:

```python
from startup_scraper import main

results = main(success_websites=["github_trending", "hn_hiring", "crunchbase_odm"])
print(f"Collected {len(results)} records")
```

## Output

Each run produces:

- `result/startup_data_<source>.json` — results per source
- `result/startup_data_combined.json` — all results merged into one file

Every record contains at minimum:

```json
{
  "name": "Company Name",
  "website": "https://example.com",
  "description": "Short description",
  "source": "source_name"
}
```

Some sources include extra fields such as `batch` (YC), `founded`, `country` (Crunchbase).

## Available sources

| Source key | Function | Notes |
|---|---|---|
| `github_trending` | `fetch_github_trending()` | No auth needed |
| `yc_startups` | `fetch_yc_startups()` | YC API intermittently returns 500 |
| `hn_hiring` | `fetch_hn_hiring()` | Uses Algolia + Firebase HN APIs |
| `eu_startups` | `fetch_eu_startups()` | May return 403 |
| `producthunt` | `fetch_producthunt()` | May return 403 without API key |
| `opencorporates` | `fetch_open_corporates()` | Requires API key for search |
| `crunchbase_odm` | `fetch_crunchbase_odm()` | Public CSV dump from GitHub |
| `wikidata` | `fetch_wikidata_companies()` | Free SPARQL endpoint |
| `github_datasets` | `fetch_github_startup_datasets()` | Community datasets on GitHub |
| `indiehackers` | `fetch_indiehackers()` | React SPA, may return empty |
| `techcrunch_rss` | `fetch_techcrunch_rss()` | Parses RSS feed |
| `wellfound` | `fetch_wellfound()` | Scrapes Wellfound startup listings |

## How the auto-fix works

Each fetcher is wrapped in `run_and_fix()`, which retries up to 3 times with increasing `fix` levels. On each retry the fetcher adjusts its behaviour (different URL, different parameters, broader selectors) before trying again:

```
attempt 1  fix=0  →  normal request
attempt 2  fix=1  →  alternate URL or params
attempt 3  fix=2  →  broader fallback strategy
```

If all attempts return empty, an empty list is saved and the script continues with the next source.

## Project structure

```
claude-code-for-scraping/
├── startup_scraper.py        # Main script
├── startup_data_*.json       # Output files (created on run)
└── README.md
```
