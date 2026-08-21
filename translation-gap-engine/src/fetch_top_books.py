#!/usr/bin/env python3
"""
Fetch the N most-notable public-domain books in a given language via
Wikidata (default: English).

Originally this used the Gutendex API (a third-party JSON mirror of
Project Gutenberg), but Gutendex returns a flat 403 for every request from
this pipeline's environment (confirmed: happens with both a custom and a
standard browser User-Agent, from both this sandbox and live GitHub Actions
runners -- almost certainly IP-range bot protection, not fixable by
changing headers). Project Gutenberg's own site works fine, but its
search-results page explicitly asks not to be scraped for exactly this
purpose ("DON'T USE THIS PAGE FOR SCRAPING... you'll only get your IP
blocked"), and its sanctioned bulk feed (catalog.rdf.bz2) has no
popularity data.

So popularity here is approximated by a book's Wikidata sitelink count
(how many different-language Wikipedias have an article on it) -- a
standard, widely-used fame/notability proxy in bibliometrics, queried in
bulk against Wikidata's own public SPARQL endpoint, which is explicitly
designed for exactly this kind of bulk querying (no scraping concerns).

A book counts as "public domain and available" if it has EITHER a
confirmed Project Gutenberg ebook ID (Wikidata property P2034) OR a
full-text edition on that language's own Wikisource (e.g. fr.wikisource.org,
hi.wikisource.org) -- Wikidata models the latter as a sitelink whose page
is `schema:about` the work. Gutenberg's non-English catalog is real but
heavily skewed toward Western European languages; Wikisource exists
per-language (over 70 language editions) and is where a lot of the
world's non-English public-domain text actually lives, so relying on
Gutenberg alone silently returns zero books for most of the world's major
languages. Each result records which source(s) it came from -- see
"source" / "gutenberg_id" / "wikisource_url" below -- so that distinction
isn't lost downstream. Public domain status is still whatever Gutenberg or
Wikisource enforce for their own jurisdiction, not independently verified
here -- see this repo's README.

Language is selected by ISO 639-1 code (e.g. "fr", "de", "fi") and resolved
to a Wikidata language item dynamically via P218, so no hardcoded table of
language -> Wikidata-item IDs is needed here. The same code is tried as
the Wikisource subdomain (e.g. "fr" -> fr.wikisource.org); that's usually
right but not guaranteed for every language, since Wikisource subdomains
don't always follow ISO 639-1 exactly (e.g. some languages use a
different code or have no Wikisource at all) -- when it's wrong, that
language's Wikisource results are just silently empty, same as Gutenberg
coverage gaps already are.

Usage:
    python fetch_top_books.py --count 1000 --language en --out data/top_books.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Two fully separate queries, not one UNION -- tried the UNION shape first
# and live-tested it badly: even with no extra type filter, every one of 10
# test languages timed out identically at 30s, including tiny Wikisource
# editions (e.g. Punjabi) with nowhere near enough pages to explain that on
# data size alone. That uniformity points at BlazeGraph (Wikidata's query
# service) picking a bad join plan for two very differently-shaped branches
# combined in one UNION, not at either branch being inherently slow. Two
# independent queries, each shaped like the original (proven-fast, ~3s)
# Gutenberg-only query, sidestep that entirely -- and as a bonus, a slow or
# failing Wikisource query for one language no longer costs that language
# its (working) Gutenberg results too.
GUTENBERG_QUERY_TEMPLATE = """
SELECT ?work ?workLabel ?sitelinks
       (SAMPLE(?gutenbergId) AS ?gutenbergIdSample)
       (GROUP_CONCAT(DISTINCT ?authorLabel; separator="; ") AS ?authors)
WHERE {{
  ?langItem wdt:P218 "{language}" .
  ?work wdt:P2034 ?gutenbergId .
  ?work wdt:P407 ?langItem .
  ?work wikibase:sitelinks ?sitelinks .
  OPTIONAL {{
    ?work wdt:P50 ?author .
    ?author rdfs:label ?authorLabel .
    FILTER(LANG(?authorLabel) = "en")
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
GROUP BY ?work ?workLabel ?sitelinks
ORDER BY DESC(?sitelinks)
LIMIT {limit}
"""

WIKISOURCE_QUERY_TEMPLATE = """
SELECT ?work ?workLabel ?sitelinks
       (SAMPLE(?wikisourceUrl) AS ?wikisourceUrlSample)
       (GROUP_CONCAT(DISTINCT ?authorLabel; separator="; ") AS ?authors)
WHERE {{
  ?langItem wdt:P218 "{language}" .
  ?wsArticle schema:about ?work ;
             schema:isPartOf <https://{language}.wikisource.org/> ;
             schema:name ?wikisourceTitle .
  ?work wdt:P407 ?langItem .
  BIND(CONCAT("https://{language}.wikisource.org/wiki/", ENCODE_FOR_URI(?wikisourceTitle)) AS ?wikisourceUrl)
  ?work wikibase:sitelinks ?sitelinks .
  OPTIONAL {{
    ?work wdt:P50 ?author .
    ?author rdfs:label ?authorLabel .
    FILTER(LANG(?authorLabel) = "en")
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
GROUP BY ?work ?workLabel ?sitelinks
ORDER BY DESC(?sitelinks)
LIMIT {limit}
"""


def _run_sparql_query(query, retries, backoff, timeout):
    for attempt in range(retries):
        try:
            resp = requests.get(
                SPARQL_URL, params={"query": query}, headers=HEADERS, timeout=timeout
            )
        except requests.RequestException as exc:
            wait = backoff * (2 ** attempt)
            print(f"  request failed ({exc}), retrying in {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        if resp.status_code == 200:
            return resp.json()["results"]["bindings"]
        if resp.status_code == 429:
            wait = backoff * (2 ** attempt)
            print(f"  rate limited, waiting {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Wikidata query failed after {retries} attempts")


def _parse_gutenberg_id(raw):
    try:
        return int(raw)
    except ValueError:
        # A handful of P2034 values are ranges ("1234-1235") for
        # multi-volume works -- keep the first volume's ID.
        return int(raw.split("-")[0])


def fetch_top_books(count, language="en", retries=4, backoff=3.0, timeout=90):
    # Over-fetch: some Wikidata works have more than one linked Gutenberg
    # edition, or show up in both the Gutenberg and Wikisource results,
    # producing duplicates that get collapsed below -- asking for a bit
    # more than `count` from each source keeps us from falling short.
    limit = int(count * 1.3) + 20

    books_by_id = {}

    gutenberg_query = GUTENBERG_QUERY_TEMPLATE.format(limit=limit, language=language)
    for row in _run_sparql_query(gutenberg_query, retries, backoff, timeout):
        work_id = row["work"]["value"].rsplit("/", 1)[-1]
        authors_raw = row.get("authors", {}).get("value", "")
        books_by_id[work_id] = {
            "wikidata_id": work_id,
            "title": row["workLabel"]["value"],
            "authors": [a.strip() for a in authors_raw.split(";") if a.strip()],
            "sitelinks": int(row["sitelinks"]["value"]),
            "source_language": language,
            "source": "gutenberg",
            "gutenberg_id": _parse_gutenberg_id(row["gutenbergIdSample"]["value"].strip()),
            "wikisource_url": None,
        }

    # English skips the Wikisource query entirely: Gutenberg's English
    # catalog is already comprehensive, and English is this project's
    # *target* language (what a translation is missing *into*), never a
    # source language that needs the extra non-Gutenberg coverage.
    if language != "en":
        try:
            wikisource_query = WIKISOURCE_QUERY_TEMPLATE.format(limit=limit, language=language)
            wikisource_rows = _run_sparql_query(wikisource_query, retries, backoff, timeout)
        except Exception as exc:  # noqa: BLE001 -- a slow/failed Wikisource query shouldn't cost the (already-fetched) Gutenberg results
            print(f"  Wikisource query failed ({type(exc).__name__}: {exc}), "
                  f"keeping Gutenberg-only results for this language", file=sys.stderr)
            wikisource_rows = []
        for row in wikisource_rows:
            work_id = row["work"]["value"].rsplit("/", 1)[-1]
            wikisource_url = row["wikisourceUrlSample"]["value"].strip()
            if work_id in books_by_id:
                # Already have it via Gutenberg -- just record the extra edition.
                books_by_id[work_id]["wikisource_url"] = wikisource_url
                continue
            authors_raw = row.get("authors", {}).get("value", "")
            books_by_id[work_id] = {
                "wikidata_id": work_id,
                "title": row["workLabel"]["value"],
                "authors": [a.strip() for a in authors_raw.split(";") if a.strip()],
                "sitelinks": int(row["sitelinks"]["value"]),
                "source_language": language,
                "source": "wikisource",
                "gutenberg_id": None,
                "wikisource_url": wikisource_url,
            }

    books = sorted(books_by_id.values(), key=lambda b: b["sitelinks"], reverse=True)
    return books[:count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--language", default="en", help="ISO 639-1 code of the source language")
    parser.add_argument("--out", type=Path, default=Path("data/top_books.json"))
    args = parser.parse_args()

    print(
        f"Fetching top {args.count} public-domain books in language "
        f"'{args.language}' from Wikidata (ranked by Wikipedia sitelink count)...",
        file=sys.stderr,
    )
    books = fetch_top_books(args.count, language=args.language)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(books, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(books)} books to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
