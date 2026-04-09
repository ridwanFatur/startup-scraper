# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install requests beautifulsoup4 lxml
```

## Running

```bash
# Run with the default pre-selected sources (see __main__ block)
python startup_scraper.py

# Run all 12 sources
python -c "from startup_scraper import main; main(success_websites=None)"

# Run specific sources
python -c "from startup_scraper import main; main(success_websites=['github_trending', 'techcrunch_rss'])"
```

## Architecture

Everything lives in a single file: `startup_scraper.py`.

**Data flow:**
1. `main(success_websites)` filters `FETCHERS` dict to the requested sources
2. Each fetcher is called via `run_and_fix(fetch_fn, source_name)` which retries up to 3 times
3. On each retry, `fix` level increments (0→1→2), and the fetcher uses that to switch to an alternate URL, params, or selector strategy
4. Results from all sources are merged and written to `result/startup_data_combined.json`; each source also writes its own `result/startup_data_<source>.json`

**Adding a new fetcher:**
- Write `def fetch_<name>(fix: int = 0) -> list` returning dicts with at minimum `name`, `website`, `description`, `source`
- Register it in the `FETCHERS` dict at the bottom of the file
- Add it to the `success_websites` list in `__main__` if it works without API keys

**Output directory:** `result/` — gitignored, created automatically on first run.

**Sources that work without credentials:** `github_trending`, `hn_hiring`, `crunchbase_odm`, `wikidata`, `techcrunch_rss`, `wellfound`.

**Sources that currently fail:** `yc_startups` (500 from YC API), `eu_startups`/`producthunt` (403), `opencorporates` (401, needs API key), `github_datasets`/`indiehackers` (404 or empty SPA).
