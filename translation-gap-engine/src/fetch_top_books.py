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

Every result already has a confirmed Project Gutenberg ebook ID (Wikidata
property P2034), so "public domain" here still means "hosted by Project
Gutenberg" -- see the note in this repo's README about what that does and
doesn't guarantee.

Language is selected by ISO 639-1 code (e.g. "fr", "de", "fi") and resolved
to a Wikidata language item dynamically via P218, so no hardcoded table of
language -> Wikidata-item IDs is needed here.

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

QUERY_TEMPLATE = """
SELECT ?work ?workLabel ?gutenbergId ?sitelinks
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
GROUP BY ?work ?workLabel ?gutenbergId ?sitelinks
ORDER BY DESC(?sitelinks)
LIMIT {limit}
"""


def fetch_top_books(count, language="en", retries=4, backoff=3.0, timeout=90):
    # Over-fetch: some Wikidata works have more than one linked Gutenberg
    # edition, which produces duplicate rows for the same book that get
    # collapsed below -- asking for a bit more than `count` keeps us from
    # falling short after deduplication.
    query = QUERY_TEMPLATE.format(limit=int(count * 1.3) + 20, language=language)

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
            break
        if resp.status_code == 429:
            wait = backoff * (2 ** attempt)
            print(f"  rate limited, waiting {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
    else:
        raise RuntimeError(f"Wikidata query failed after {retries} attempts")

    bindings = resp.json()["results"]["bindings"]

    books = []
    seen_works = set()
    for row in bindings:
        work_uri = row["work"]["value"]
        if work_uri in seen_works:
            continue  # same book linked to more than one Gutenberg edition
        seen_works.add(work_uri)

        gutenberg_id_raw = row["gutenbergId"]["value"].strip()
        try:
            gutenberg_id = int(gutenberg_id_raw)
        except ValueError:
            # A handful of P2034 values are ranges ("1234-1235") for
            # multi-volume works -- keep the first volume's ID.
            gutenberg_id = int(gutenberg_id_raw.split("-")[0])

        authors_raw = row.get("authors", {}).get("value", "")
        authors = [a.strip() for a in authors_raw.split(";") if a.strip()]

        books.append({
            "gutenberg_id": gutenberg_id,
            "wikidata_id": work_uri.rsplit("/", 1)[-1],
            "title": row["workLabel"]["value"],
            "authors": authors,
            "sitelinks": int(row["sitelinks"]["value"]),
            "source_language": language,
        })
        if len(books) >= count:
            break

    return books


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
