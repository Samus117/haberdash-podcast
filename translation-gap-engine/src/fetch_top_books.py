#!/usr/bin/env python3
"""
Fetch the N most-downloaded English-language public-domain books from
Project Gutenberg via the Gutendex API (https://gutendex.com).

"Public domain" here means "hosted by Project Gutenberg", which requires
the work to be in the public domain in the United States -- copyright
status can differ in other countries, so re-check that for any title
before commissioning a translation there.

Usage:
    python fetch_top_books.py --count 1000 --out data/top_books.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

GUTENDEX_BASE = "https://gutendex.com/books"
HEADERS = {
    "User-Agent": "haberdash-translation-gap-engine/1.0 (https://github.com/Samus117/haberdash-podcast)"
}


def fetch_page(url, retries=5, backoff=2.0):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as exc:
            wait = backoff * (2 ** attempt)
            print(f"  request failed ({exc}), retrying in {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            wait = backoff * (2 ** attempt)
            print(f"  rate limited, waiting {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def parse_results(data):
    """Pull the fields we care about out of one Gutendex page response."""
    books = []
    for item in data.get("results", []):
        if item.get("media_type") != "Text":
            continue
        if item.get("copyright") is True:
            continue  # skip anything Gutendex flags as still under copyright
        authors = [a["name"] for a in item.get("authors", [])]
        books.append({
            "gutenberg_id": item["id"],
            "title": item["title"],
            "authors": authors,
            "subjects": item.get("subjects", []),
            "download_count": item.get("download_count", 0),
        })
    return books


def fetch_top_books(count, languages="en"):
    books = []
    url = f"{GUTENDEX_BASE}?languages={languages}&sort=popular"
    while url and len(books) < count:
        data = fetch_page(url)
        books.extend(parse_results(data))
        url = data.get("next")
        print(f"  collected {len(books)} / {count}", file=sys.stderr)
        time.sleep(0.5)  # be polite to a free public API
    return books[:count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--out", type=Path, default=Path("data/top_books.json"))
    args = parser.parse_args()

    print(f"Fetching top {args.count} English public-domain books from Gutendex...", file=sys.stderr)
    books = fetch_top_books(args.count)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(books, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(books)} books to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
