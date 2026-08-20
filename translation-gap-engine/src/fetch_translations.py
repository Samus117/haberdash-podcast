#!/usr/bin/env python3
"""
For each book in top_books.json, query the Open Library Search API to find
which languages it has been published/catalogued in.

Results are written incrementally, so an interrupted run can be re-started
with the same --out path and it will skip books already looked up.

Matching is by title + first author against Open Library's search index,
taking the top hit. That's a heuristic, not a guarantee -- ambiguous or
very common titles can mismatch. Treat this as a first pass to prioritize
manual verification, not a final answer on its own (see the project
README for how compute_gaps.py's output should be spot-checked).

Usage:
    python fetch_translations.py --in data/top_books.json --out data/translations.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

SEARCH_URL = "https://openlibrary.org/search.json"
# See fetch_top_books.py -- a custom/app-style User-Agent got a flat 403 from
# Gutendex on this same class of request, so use a standard browser UA here too.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
REQUEST_DELAY = 1.0  # seconds between requests -- be a good citizen of a free public API


def query_languages(title, authors, retries=4):
    # Omit the `author` param entirely when there isn't one -- sending
    # `author=` (empty string) reliably 500s on Open Library's search API,
    # confirmed live (e.g. "The Jungle Book", which Wikidata lists with no
    # author). Absent-vs-empty matters to their backend even though both
    # mean "no author filter" from our side.
    params = {
        "title": title,
        "fields": "title,author_name,language,edition_count,first_publish_year",
        "limit": 1,
    }
    if authors:
        params["author"] = authors[0]

    for attempt in range(retries):
        try:
            resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        except requests.RequestException as exc:
            print(f"    error ({exc}), retrying...", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 200:
            docs = resp.json().get("docs", [])
            if not docs:
                return {"matched": False, "languages": [], "edition_count": 0}
            doc = docs[0]
            return {
                "matched": True,
                "matched_title": doc.get("title"),
                "matched_author": (doc.get("author_name") or [None])[0],
                "languages": doc.get("language", []),
                "edition_count": doc.get("edition_count", 0),
                "first_publish_year": doc.get("first_publish_year"),
            }
        if resp.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if resp.status_code >= 500:
            print(f"    server error {resp.status_code}, retrying...", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
            continue
        resp.raise_for_status()
    return {"matched": False, "languages": [], "edition_count": 0, "error": "failed after retries"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="infile", type=Path, default=Path("data/top_books.json"))
    parser.add_argument("--out", dest="outfile", type=Path, default=Path("data/translations.json"))
    parser.add_argument("--limit", type=int, default=None, help="only process the first N books (for a quick test run)")
    args = parser.parse_args()

    books = json.loads(args.infile.read_text(encoding="utf-8"))
    if args.limit:
        books = books[: args.limit]

    cache = {}
    if args.outfile.exists():
        cache = {b["gutenberg_id"]: b for b in json.loads(args.outfile.read_text(encoding="utf-8"))}
        print(f"Resuming: {len(cache)} books already cached in {args.outfile}", file=sys.stderr)

    results = []
    for i, book in enumerate(books, 1):
        gid = book["gutenberg_id"]
        if gid in cache:
            results.append(cache[gid])
            continue

        print(f"[{i}/{len(books)}] {book['title']}", file=sys.stderr)
        info = query_languages(book["title"], book["authors"])
        results.append({**book, **info})

        # Write after every book so a timeout/crash doesn't lose progress.
        args.outfile.parent.mkdir(parents=True, exist_ok=True)
        args.outfile.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

        time.sleep(REQUEST_DELAY)

    print(f"Done. Wrote {len(results)} records to {args.outfile}", file=sys.stderr)


if __name__ == "__main__":
    main()
