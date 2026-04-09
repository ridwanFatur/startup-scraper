"""
Startup & Company Data Scraper
================================
Collects company/startup data from multiple public sources:
 1. GitHub Trending Repositories
 2. Y Combinator (YC) Company List
 3. Product Hunt (via unofficial scraping)
 4. Hacker News Who's Hiring posts
 5. F6S Startup Directory
 6. EU-Startups directory
 7. Crunchbase Open Data (free CSV dump)
 8. StartupBlink open data
 9. Open Corporates (free API)
10. Wired/TechCrunch RSS (news-based company mentions)

Each fetcher returns a list of dicts with at minimum:
  { "name": ..., "website": ..., "description": ... }
"""

import requests
import json
import time
import re
from datetime import datetime
from bs4 import BeautifulSoup
import os

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Rotate a few realistic User-Agent strings to avoid simple bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

_ua_index = 0

def get_headers(extra: dict = None) -> dict:
    """Return rotating browser-like headers."""
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if extra:
        headers.update(extra)
    return headers


def safe_get(url: str, headers: dict = None, params: dict = None,
             timeout: int = 15) -> requests.Response | None:
    """GET with error handling; returns Response or None."""
    try:
        resp = requests.get(
            url,
            headers=headers or get_headers(),
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"  [!] Request failed for {url}: {exc}")
        return None


def save_json(data: list, source_name: str):
    """Save results list to startup_data_<source>.json"""
    os.makedirs("./result", exist_ok=True)
    filename = f"./result/startup_data_{source_name}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [+] Saved {len(data)} records → {filename}")


# ---------------------------------------------------------------------------
# run_and_fix wrapper
# ---------------------------------------------------------------------------

def run_and_fix(fetch_fn, source_name: str, max_retries: int = 3) -> list:
    """
    Attempt to run fetch_fn; if the result is empty, retry with progressively
    tweaked parameters (fix=True, then fix=2, etc.) up to max_retries times.

    After a successful (non-empty) result – or after exhausting retries –
    saves the output to startup_data_<source_name>.json.
    """
    data = []
    for attempt in range(max_retries):
        fix_level = attempt  # 0 = normal, 1 = first fix, 2 = second fix …
        print(f"  → [{source_name}] attempt {attempt + 1}/{max_retries} "
              f"(fix_level={fix_level})")
        try:
            data = fetch_fn(fix=fix_level)
        except Exception as exc:
            print(f"  [!] Exception in {source_name}: {exc}")
            data = []

        if data:
            print(f"  [✓] {source_name}: got {len(data)} records.")
            break
        else:
            print(f"  [~] Empty result from {source_name}, retrying …")
            time.sleep(2 * (attempt + 1))   # back-off before retry

    if not data:
        print(f"  [✗] {source_name}: all attempts failed, saving empty list.")

    save_json(data, source_name)
    return data


# ---------------------------------------------------------------------------
# 1. GitHub Trending Repositories
# ---------------------------------------------------------------------------

def fetch_github_trending(fix: int = 0) -> list:
    """
    Scrape https://github.com/trending to get trending repos.
    Each repo is treated as a "company/project".

    fix=0  → default (daily trending)
    fix=1  → weekly trending
    fix=2  → monthly trending + broader selectors
    """
    time_ranges = {0: "daily", 1: "weekly", 2: "monthly"}
    since = time_ranges.get(fix, "daily")
    url = f"https://github.com/trending?since={since}"

    resp = safe_get(url, headers=get_headers())
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Each trending repo sits inside an <article> tag
    articles = soup.select("article.Box-row") or soup.select("article")
    results = []

    for article in articles:
        try:
            # Repo full name  e.g.  "owner/repo"
            h2 = article.find("h2") or article.find("h1")
            if not h2:
                continue
            name_raw = h2.get_text(separator="/", strip=True)
            # Clean extra whitespace/newlines often present
            name = re.sub(r"\s+", "", name_raw).strip("/")

            # Description paragraph
            desc_tag = article.find("p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            # Build website URL from repo path
            a_tag = h2.find("a")
            repo_path = a_tag["href"].lstrip("/") if a_tag else name
            website = f"https://github.com/{repo_path}"

            results.append({
                "name": name,
                "website": website,
                "description": description,
                "source": "github_trending",
            })
        except Exception:
            continue

    return results


# ---------------------------------------------------------------------------
# 2. Y Combinator Company List
# ---------------------------------------------------------------------------

def fetch_yc_startups(fix: int = 0) -> list:
    """
    Pull the YC company directory from the public YC API endpoint.
    Returns companies with name, website, description, batch.

    fix=0  → first page (100 companies)
    fix=1  → page 2
    fix=2  → broader fetch, top 500 via multiple pages
    """
    base_url = "https://www.ycombinator.com/companies"
    api_url = "https://www.ycombinator.com/companies.json"

    # YC exposes a JSON feed used by their own React frontend
    params = {"page": 1 + fix, "per_page": 100}
    resp = safe_get(api_url, params=params, headers=get_headers({
        "Referer": "https://www.ycombinator.com/companies",
        "X-Requested-With": "XMLHttpRequest",
    }))

    results = []

    if resp and resp.headers.get("Content-Type", "").startswith("application/json"):
        try:
            payload = resp.json()
            companies = payload.get("companies", payload) if isinstance(payload, dict) else payload
            for c in companies:
                results.append({
                    "name": c.get("name", ""),
                    "website": c.get("url") or c.get("website", ""),
                    "description": c.get("one_liner") or c.get("long_description", ""),
                    "batch": c.get("batch", ""),
                    "source": "yc",
                })
            return results
        except (ValueError, KeyError):
            pass  # fall through to HTML scraping

    # Fallback: scrape the HTML directory page
    resp = safe_get(base_url, headers=get_headers())
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # YC renders companies inside a Next.js __NEXT_DATA__ JSON blob
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if script_tag:
        try:
            next_data = json.loads(script_tag.string)
            companies = (
                next_data.get("props", {})
                         .get("pageProps", {})
                         .get("companies", [])
            )
            for c in companies:
                results.append({
                    "name": c.get("name", ""),
                    "website": c.get("url", ""),
                    "description": c.get("one_liner", "") or c.get("long_description", ""),
                    "batch": c.get("batch", ""),
                    "source": "yc",
                })
            return results
        except (json.JSONDecodeError, KeyError):
            pass

    # Last resort: parse visible HTML cards
    cards = soup.select("a[class*='company']") or soup.select("div[class*='company-card']")
    for card in cards:
        name_tag = card.find(["h3", "h4", "strong"])
        desc_tag = card.find("p")
        href = card.get("href", "")
        results.append({
            "name": name_tag.get_text(strip=True) if name_tag else "",
            "website": f"https://www.ycombinator.com{href}" if href else "",
            "description": desc_tag.get_text(strip=True) if desc_tag else "",
            "source": "yc",
        })

    return results


# ---------------------------------------------------------------------------
# 3. Hacker News "Who's Hiring" (monthly thread)
# ---------------------------------------------------------------------------

def fetch_hn_hiring(fix: int = 0) -> list:
    """
    Uses the Algolia HN search API to find the latest 'Ask HN: Who is hiring?'
    thread and parse company entries from the top-level comments.

    fix=0  → most recent month
    fix=1  → second-most-recent
    fix=2  → page 2 of results
    """
    # Search for "Ask HN: Who is hiring" posts
    search_url = "https://hn.algolia.com/api/v1/search"
    params = {
        "query": "Ask HN: Who is hiring?",
        "tags": "ask_hn",
        "hitsPerPage": 5,
    }
    resp = safe_get(search_url, params=params)
    if not resp:
        return []

    hits = resp.json().get("hits", [])
    if not hits:
        return []

    # Pick which monthly thread to use based on fix level
    thread_index = min(fix, len(hits) - 1)
    thread_id = hits[thread_index]["objectID"]

    # Fetch all top-level comments for the thread
    item_url = f"https://hacker-news.firebaseio.com/v0/item/{thread_id}.json"
    resp = safe_get(item_url)
    if not resp:
        return []

    thread = resp.json()
    kids = thread.get("kids", [])[:100]  # limit to first 100 comments

    results = []
    for kid_id in kids:
        comment_url = f"https://hacker-news.firebaseio.com/v0/item/{kid_id}.json"
        c_resp = safe_get(comment_url)
        if not c_resp:
            continue
        comment = c_resp.json()
        text = comment.get("text", "")
        if not text:
            continue

        # Each comment typically starts with "CompanyName | ..."
        # Parse company name and extract a URL if present
        soup = BeautifulSoup(text, "html.parser")
        plain = soup.get_text(separator=" ")
        lines = [l.strip() for l in plain.split("|") if l.strip()]
        company_name = lines[0] if lines else plain[:60]

        # Try to find a URL in the text
        urls = re.findall(r"https?://[^\s\"<>]+", text)
        website = urls[0] if urls else ""

        # Build short description from rest of text
        description = " | ".join(lines[1:3]) if len(lines) > 1 else plain[:200]

        results.append({
            "name": company_name.strip(),
            "website": website,
            "description": description[:300],
            "source": "hn_hiring",
        })
        time.sleep(0.1)  # be polite to Firebase

    return results


# ---------------------------------------------------------------------------
# 4. EU-Startups Directory
# ---------------------------------------------------------------------------

def fetch_eu_startups(fix: int = 0) -> list:
    """
    Scrape the EU-Startups company database.
    https://www.eu-startups.com/directory/

    fix=0  → page 1
    fix=1  → page 2
    fix=2  → page 3 with larger timeout
    """
    page = fix + 1
    url = f"https://www.eu-startups.com/directory/page/{page}/"

    resp = safe_get(url, headers=get_headers({
        "Referer": "https://www.eu-startups.com/",
    }), timeout=20 + fix * 5)

    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    # Each startup is inside an article or div with class containing "listing"
    cards = (
        soup.select("div.wpbdp-listing") or
        soup.select("article.wpbdp-listing") or
        soup.select("div[class*='listing-item']") or
        soup.select("div.listing")
    )

    for card in cards:
        # Name
        name_tag = (
            card.find("h3") or
            card.find("h4") or
            card.find(class_=re.compile(r"title|name", re.I))
        )
        name = name_tag.get_text(strip=True) if name_tag else ""

        # Website link
        link_tag = card.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        # Prefer external links over internal directory URLs
        if href.startswith("http") and "eu-startups.com" not in href:
            website = href
        else:
            website = href

        # Description
        desc_tag = card.find("p") or card.find(class_=re.compile(r"desc|excerpt", re.I))
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        if name:
            results.append({
                "name": name,
                "website": website,
                "description": description,
                "source": "eu_startups",
            })

    return results


# ---------------------------------------------------------------------------
# 5. ProductHunt (public scraping – no API key required)
# ---------------------------------------------------------------------------

def fetch_producthunt(fix: int = 0) -> list:
    """
    Scrape ProductHunt's front page or trending products.
    https://www.producthunt.com/

    fix=0  → today's front page
    fix=1  → /posts/trending (different URL)
    fix=2  → use GraphQL-like JSON endpoint that PH uses internally
    """
    if fix == 0:
        url = "https://www.producthunt.com/"
    elif fix == 1:
        url = "https://www.producthunt.com/posts"
    else:
        # PH uses a Next.js build; try the JSON data endpoint
        url = "https://www.producthunt.com/frontend/graphql"

    if fix < 2:
        resp = safe_get(url, headers=get_headers({
            "Referer": "https://www.producthunt.com/",
        }))
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Products are rendered in <li> or <section> items; look for __NEXT_DATA__
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if script_tag:
            try:
                nd = json.loads(script_tag.string)
                # Navigate the Next.js page props to find posts
                posts = []
                props = nd.get("props", {}).get("pageProps", {})
                # Try common keys
                for key in ("posts", "dailyPosts", "featuredPosts"):
                    if key in props:
                        posts = props[key]
                        break
                if not posts:
                    # Deep search for a list of dicts with "name"
                    def deep_find(obj, depth=0):
                        if depth > 6:
                            return []
                        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "name" in obj[0]:
                            return obj
                        if isinstance(obj, dict):
                            for v in obj.values():
                                r = deep_find(v, depth + 1)
                                if r:
                                    return r
                        return []
                    posts = deep_find(props)

                results = []
                for p in posts:
                    results.append({
                        "name": p.get("name", ""),
                        "website": p.get("website") or p.get("url", ""),
                        "description": p.get("tagline") or p.get("description", ""),
                        "source": "producthunt",
                    })
                if results:
                    return results
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: parse visible HTML cards
        results = []
        # PH renders products in list items with data-test attributes
        items = (
            soup.select("li[data-test*='post-item']") or
            soup.select("section[class*='post']") or
            soup.select("div[class*='styles_item']")
        )
        for item in items:
            name_tag = item.find(["h3", "h2", "strong"]) or item.find(class_=re.compile(r"name|title", re.I))
            tagline_tag = item.find("p") or item.find(class_=re.compile(r"tagline|desc", re.I))
            a_tag = item.find("a", href=True)
            results.append({
                "name": name_tag.get_text(strip=True) if name_tag else "",
                "website": "https://www.producthunt.com" + a_tag["href"] if a_tag else "",
                "description": tagline_tag.get_text(strip=True) if tagline_tag else "",
                "source": "producthunt",
            })
        return [r for r in results if r["name"]]

    return []


# ---------------------------------------------------------------------------
# 6. Open Corporates (free tier API)
# ---------------------------------------------------------------------------

def fetch_open_corporates(fix: int = 0) -> list:
    """
    Use the OpenCorporates free REST API to search for tech companies.
    https://api.opencorporates.com/

    No API key needed for basic queries (rate-limited).

    fix=0  → search "startup" in US
    fix=1  → search "technology" in UK
    fix=2  → search "innovation" globally
    """
    queries = {
        0: {"q": "startup", "jurisdiction_code": "us", "per_page": 50},
        1: {"q": "technology", "jurisdiction_code": "gb", "per_page": 50},
        2: {"q": "innovation", "per_page": 50},
    }
    params = queries.get(fix, queries[0])
    url = "https://api.opencorporates.com/v0.4/companies/search"

    resp = safe_get(url, params=params)
    if not resp:
        return []

    try:
        data = resp.json()
    except ValueError:
        return []

    companies = (
        data.get("results", {}).get("companies", [])
    )
    results = []
    for item in companies:
        c = item.get("company", item)
        results.append({
            "name": c.get("name", ""),
            "website": c.get("registry_url", "") or c.get("opencorporates_url", ""),
            "description": f"Incorporated: {c.get('incorporation_date', 'N/A')} | "
                           f"Status: {c.get('current_status', 'N/A')} | "
                           f"Jurisdiction: {c.get('jurisdiction_code', 'N/A')}",
            "source": "opencorporates",
        })
    return results


# ---------------------------------------------------------------------------
# 7. Crunchbase Odm (Open Data Map) – free CSV releases on GitHub
# ---------------------------------------------------------------------------

def fetch_crunchbase_odm(fix: int = 0) -> list:
    """
    Crunchbase releases periodic Open Data Map snapshots on GitHub as CSV.
    We use the most recent known public export.

    fix=0  → try the GitHub raw CSV
    fix=1  → try an alternative mirror/cache
    fix=2  → fall back to a cached subset hosted on Kaggle datasets (JSON proxy)
    """
    # Known public snapshots on GitHub / data.world mirrors
    sources = [
        # Crunchbase 2015 open dataset (public domain)
        "https://raw.githubusercontent.com/notpeter/crunchbase-data/master/companies.csv",
        # Alternate source
        "https://raw.githubusercontent.com/njanakiev/crunchbase-analysis/master/data/companies.csv",
    ]
    url = sources[min(fix, len(sources) - 1)]

    resp = safe_get(url, timeout=30)
    if not resp:
        return []

    lines = resp.text.splitlines()
    if not lines:
        return []

    import csv
    import io
    reader = csv.DictReader(io.StringIO(resp.text))
    results = []
    for i, row in enumerate(reader):
        if i >= 500:  # cap at 500 rows to keep it manageable
            break
        name = row.get("name") or row.get("company_name", "")
        website = row.get("homepage_url") or row.get("website", "")
        description = row.get("short_description") or row.get("description", "")
        if name:
            results.append({
                "name": name,
                "website": website,
                "description": description,
                "founded": row.get("founded_at") or row.get("founded_year", ""),
                "country": row.get("country_code", ""),
                "source": "crunchbase_odm",
            })
    return results


# ---------------------------------------------------------------------------
# 8. Wikidata SPARQL – tech companies
# ---------------------------------------------------------------------------

def fetch_wikidata_companies(fix: int = 0) -> list:
    """
    Query the Wikidata SPARQL endpoint for technology companies.
    Completely free and open.

    fix=0  → top 100 tech companies (instance of "startup")
    fix=1  → top 100 software companies
    fix=2  → expand to 200 results
    """
    sparql_url = "https://query.wikidata.org/sparql"

    limits = {0: 100, 1: 100, 2: 200}
    types = {
        0: "wd:Q1620963",   # technology startup
        1: "wd:Q2738075",   # software company
        2: "wd:Q4830453",   # business enterprise (broader)
    }
    limit = limits.get(fix, 100)
    company_type = types.get(fix, "wd:Q1620963")

    query = f"""
    SELECT ?company ?companyLabel ?websiteLabel ?description WHERE {{
      ?company wdt:P31 {company_type} .
      OPTIONAL {{ ?company wdt:P856 ?website . }}
      OPTIONAL {{ ?company schema:description ?description .
                 FILTER(LANG(?description) = "en") }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT {limit}
    """

    resp = safe_get(
        sparql_url,
        headers=get_headers({
            "Accept": "application/sparql-results+json",
        }),
        params={"query": query, "format": "json"},
        timeout=30,
    )
    if not resp:
        return []

    try:
        data = resp.json()
    except ValueError:
        return []

    bindings = data.get("results", {}).get("bindings", [])
    results = []
    for b in bindings:
        name = b.get("companyLabel", {}).get("value", "")
        website = b.get("websiteLabel", {}).get("value", "")
        description = b.get("description", {}).get("value", "")
        if name and not name.startswith("Q"):  # skip unlabeled items
            results.append({
                "name": name,
                "website": website,
                "description": description,
                "source": "wikidata",
            })
    return results


# ---------------------------------------------------------------------------
# 9. Startup Genome (open report data) / SemRush free tier
#    → replaced with FreeCodeCamp dataset on GitHub (real open data)
# ---------------------------------------------------------------------------

def fetch_github_startup_datasets(fix: int = 0) -> list:
    """
    Pull startup lists from open datasets hosted on GitHub.
    Several researchers have published cleaned startup CSVs.

    fix=0  → unicorn companies list
    fix=1  → Y Combinator alumni CSV (community-maintained)
    fix=2  → Forbes AI 50 snapshot
    """
    datasets = [
        # CB Insights Unicorn list (community scraped)
        "https://raw.githubusercontent.com/jnishiyama/unicorn-list/main/unicorns.json",
        # YC Alumni (community maintained)
        "https://raw.githubusercontent.com/ryxcommar/yc-companies/main/yc_companies.json",
        # Misc startup list
        "https://raw.githubusercontent.com/prasertcbs/startup_dataset/main/unicorn.csv",
    ]
    url = datasets[min(fix, len(datasets) - 1)]

    resp = safe_get(url, timeout=20)
    if not resp:
        return []

    content_type = resp.headers.get("Content-Type", "")
    results = []

    if url.endswith(".json") or "json" in content_type:
        try:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        results.append({
                            "name": item.get("company") or item.get("name", ""),
                            "website": item.get("website") or item.get("url", ""),
                            "description": item.get("description") or item.get("category", ""),
                            "source": "github_datasets",
                        })
            elif isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        results.append({
                            "name": v.get("name", k),
                            "website": v.get("website", ""),
                            "description": v.get("description", ""),
                            "source": "github_datasets",
                        })
        except ValueError:
            pass
    else:
        # CSV
        import csv, io
        reader = csv.DictReader(io.StringIO(resp.text))
        for i, row in enumerate(reader):
            if i >= 300:
                break
            name = (row.get("Company") or row.get("company") or
                    row.get("Name") or row.get("name", ""))
            website = (row.get("Website") or row.get("website") or
                       row.get("URL") or row.get("url", ""))
            description = (row.get("Description") or row.get("description") or
                           row.get("Industry") or row.get("industry", ""))
            if name:
                results.append({
                    "name": name,
                    "website": website,
                    "description": description,
                    "source": "github_datasets",
                })

    return results


# ---------------------------------------------------------------------------
# 10. Indie Hackers Products (scraping)
# ---------------------------------------------------------------------------

def fetch_indiehackers(fix: int = 0) -> list:
    """
    Scrape IndieHackers product/company pages.
    https://www.indiehackers.com/products

    fix=0  → /products default sort
    fix=1  → /products?revenueVerified=true
    fix=2  → try embedded JSON in HTML
    """
    urls = {
        0: "https://www.indiehackers.com/products",
        1: "https://www.indiehackers.com/products?revenueVerified=true",
        2: "https://www.indiehackers.com/products?sorting=revenue",
    }
    url = urls.get(fix, urls[0])

    resp = safe_get(url, headers=get_headers({
        "Referer": "https://www.indiehackers.com/",
    }))
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # IH is a React SPA; look for __NEXT_DATA__ or Firebase data
    results = []
    for script in soup.find_all("script"):
        src = script.string or ""
        if '"products"' in src or '"product"' in src:
            # Try to extract JSON array
            match = re.search(r'"products"\s*:\s*(\[.*?\])', src, re.DOTALL)
            if match:
                try:
                    prods = json.loads(match.group(1))
                    for p in prods:
                        results.append({
                            "name": p.get("name", ""),
                            "website": p.get("url", ""),
                            "description": p.get("description", ""),
                            "source": "indiehackers",
                        })
                    if results:
                        return results
                except json.JSONDecodeError:
                    pass

    # Fallback: parse visible product cards
    cards = (
        soup.select("div[class*='product-summary']") or
        soup.select("div[class*='ProductCard']") or
        soup.select("a[class*='product']")
    )
    for card in cards:
        name_tag = card.find(["h2", "h3", "strong"]) or card.find(class_=re.compile(r"name|title", re.I))
        desc_tag = card.find("p") or card.find(class_=re.compile(r"desc|tagline", re.I))
        a_tag = card.find("a", href=True) if card.name != "a" else card
        href = a_tag["href"] if a_tag else ""
        results.append({
            "name": name_tag.get_text(strip=True) if name_tag else "",
            "website": href if href.startswith("http") else f"https://www.indiehackers.com{href}",
            "description": desc_tag.get_text(strip=True) if desc_tag else "",
            "source": "indiehackers",
        })

    return [r for r in results if r["name"]]


# ---------------------------------------------------------------------------
# 11. TechCrunch RSS Feed (news-based company data)
# ---------------------------------------------------------------------------

def fetch_techcrunch_rss(fix: int = 0) -> list:
    """
    Parse TechCrunch's RSS feed to extract company names and descriptions
    from article titles/summaries.

    fix=0  → main feed
    fix=1  → startups category feed
    fix=2  → fundings feed
    """
    feeds = {
        0: "https://techcrunch.com/feed/",
        1: "https://techcrunch.com/category/startups/feed/",
        2: "https://techcrunch.com/category/funding/feed/",
    }
    url = feeds.get(fix, feeds[0])

    resp = safe_get(url, headers=get_headers({
        "Accept": "application/rss+xml, application/xml, text/xml",
    }))
    if not resp:
        return []

    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")

    results = []
    for item in items:
        title = item.find("title")
        desc = item.find("description") or item.find("summary")
        link = item.find("link")

        title_text = title.get_text(strip=True) if title else ""
        desc_text = BeautifulSoup(desc.get_text(strip=True), "html.parser").get_text() if desc else ""
        link_text = link.get_text(strip=True) if link else ""

        # Try to extract company name from title (usually "Company raises $X...")
        company_match = re.match(r"^([A-Z][A-Za-z0-9\s\.\-&]+?)\s+(raises|launches|acquires|announces|closes|gets|lands)", title_text)
        company_name = company_match.group(1).strip() if company_match else title_text[:60]

        results.append({
            "name": company_name,
            "website": link_text,
            "description": desc_text[:300],
            "source": "techcrunch_rss",
        })

    return results


# ---------------------------------------------------------------------------
# 12. Wellfound (AngelList) – public job listings (no key needed)
# ---------------------------------------------------------------------------

def fetch_wellfound(fix: int = 0) -> list:
    """
    Scrape Wellfound (formerly AngelList Talent) startup listings.
    https://wellfound.com/startups

    fix=0  → /startups default
    fix=1  → /startups?filter[stage]=seed
    fix=2  → /startups?filter[stage]=series-a
    """
    stages = {0: "", 1: "seed", 2: "series-a"}
    stage = stages.get(fix, "")
    url = f"https://wellfound.com/startups" + (f"?filter[stage]={stage}" if stage else "")

    resp = safe_get(url, headers=get_headers({
        "Referer": "https://wellfound.com/",
    }))
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    # Look for Next.js data
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if script_tag:
        try:
            nd = json.loads(script_tag.string)
            def find_startups(obj, depth=0):
                if depth > 8:
                    return []
                if isinstance(obj, list):
                    flat = []
                    for i in obj:
                        flat.extend(find_startups(i, depth + 1))
                    return flat
                if isinstance(obj, dict):
                    if "name" in obj and ("pitch" in obj or "description" in obj or "slug" in obj):
                        return [obj]
                    found = []
                    for v in obj.values():
                        found.extend(find_startups(v, depth + 1))
                    return found
                return []
            startups = find_startups(nd)
            for s in startups:
                results.append({
                    "name": s.get("name", ""),
                    "website": s.get("company_url") or s.get("website") or
                               f"https://wellfound.com/company/{s.get('slug', '')}",
                    "description": s.get("pitch") or s.get("product_desc") or s.get("description", ""),
                    "source": "wellfound",
                })
            if results:
                return results
        except (json.JSONDecodeError, KeyError):
            pass

    # HTML fallback
    cards = (
        soup.select("div[class*='startup-card']") or
        soup.select("div[data-test*='startup']") or
        soup.select("li[class*='startup']")
    )
    for card in cards:
        name_tag = card.find(["h2", "h3", "strong"])
        desc_tag = card.find("p")
        a_tag = card.find("a", href=True)
        href = a_tag["href"] if a_tag else ""
        results.append({
            "name": name_tag.get_text(strip=True) if name_tag else "",
            "website": href if href.startswith("http") else f"https://wellfound.com{href}",
            "description": desc_tag.get_text(strip=True) if desc_tag else "",
            "source": "wellfound",
        })

    return [r for r in results if r["name"]]


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

FETCHERS = {
    "github_trending":      fetch_github_trending,
    "yc_startups":          fetch_yc_startups,
    "hn_hiring":            fetch_hn_hiring,
    "eu_startups":          fetch_eu_startups,
    "producthunt":          fetch_producthunt,
    "opencorporates":       fetch_open_corporates,
    "crunchbase_odm":       fetch_crunchbase_odm,
    "wikidata":             fetch_wikidata_companies,
    "github_datasets":      fetch_github_startup_datasets,
    "indiehackers":         fetch_indiehackers,
    "techcrunch_rss":       fetch_techcrunch_rss,
    "wellfound":            fetch_wellfound,
}


def main(success_websites: list[str] = None):
    """
    Run the scraper pipeline.

    Parameters
    ----------
    success_websites : list[str], optional
        Whitelist of source names to process (e.g. ["github_trending",
        "crunchbase_odm"]).  When provided, only those sources are executed
        and their results are merged into a single output file.
        When omitted (or None), every source in FETCHERS is processed and
        each source also gets its own individual JSON file.
    """
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger(__name__)

    print("=" * 60)
    print("  Startup & Company Data Scraper")
    print(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if success_websites is not None:
        print(f"  Mode: filtered ({len(success_websites)} sources)")
        print(f"  Sources: {', '.join(success_websites)}")
    else:
        print("  Mode: all sources")
    print("=" * 60)

    # Validate the requested source names against known fetchers
    if success_websites is not None:
        unknown = [s for s in success_websites if s not in FETCHERS]
        if unknown:
            log.warning(
                "Unknown source name(s) in success_websites (will be skipped): %s",
                ", ".join(unknown),
            )

    # Determine which fetchers to run
    sources_to_run = {
        name: fn
        for name, fn in FETCHERS.items()
        if success_websites is None or name in success_websites
    }

    if not sources_to_run:
        log.error("No valid sources to process. Exiting.")
        return []

    combined: list = []
    stats: dict[str, int] = {}

    for source_name, fetch_fn in sources_to_run.items():
        print(f"\n[{source_name}]")
        try:
            data = run_and_fix(fetch_fn, source_name)
        except Exception as exc:
            log.error("Unhandled error processing '%s': %s", source_name, exc)
            data = []

        stats[source_name] = len(data)
        combined.extend(data)

        # Polite delay between sources
        time.sleep(1)

    # Save all collected records to a single merged file
    output_filename = "startup_data_combined.json"
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2, ensure_ascii=False)
        log.info("Merged results saved → %s (%d records)", output_filename, len(combined))
    except OSError as exc:
        log.error("Failed to write merged output file: %s", exc)

    # Print summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    total = 0
    for source_name, count in stats.items():
        status = "✓" if count > 0 else "✗"
        print(f"  [{status}] {source_name:25s} : {count} records")
        total += count
    print(f"  {'TOTAL':27s} : {total} records")
    print(f"  Output file : {output_filename}")
    print(f"\n  Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return combined


if __name__ == "__main__":
    # Default: run only the sources that succeeded in the last run.
    # Edit this list or pass success_websites=None to run all sources.
    success_websites = [
        "github_trending",
        "hn_hiring",
        "crunchbase_odm",
        "wikidata",
        "techcrunch_rss",
        "wellfound",
    ]
    main(success_websites=success_websites)
