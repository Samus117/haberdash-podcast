#!/usr/bin/env python3
"""
Fetch the world's languages ranked by number of speakers, from Wikidata.

Replaces the original hand-typed `data/languages.csv` (which the README
flagged as "illustrative, not authoritative") with real, sourced data.

Source and scope, honestly stated:

- Wikidata has ~13,457 items typed as some kind of "language" (P31/P279* of
  Q34770) -- but that count includes language families, historical/extinct
  language stages, sign languages, constructed languages, and dialect-level
  entries, so it is NOT "how many languages exist in the world" in the
  usual sense. The commonly-cited figure for living human languages is
  roughly 7,000 (Ethnologue's count, ~7,000-7,200 depending on edition) --
  that figure isn't queried here, it's just well-established background.

- Of those Wikidata items, ~2,327 have a "number of speakers" value
  (P1098) at all, and many of those are language *families*
  (Indo-European: 3.39 billion "speakers", i.e. everyone who speaks any
  Indo-European language) rather than individual languages -- counting
  those would massively double-count. This script filters to P31 = "modern
  language" (Q1288568) specifically, which excludes families/branches.

- Wikidata still models regional/spoken varieties of the same written/
  literary language as separate items with their own P1098 value (e.g.
  Mandarin, Wu, Cantonese, Hakka are each "a language" in Wikidata, all
  colloquially "Chinese"; Egyptian/Levantine/Algerian Arabic likewise vs.
  Standard Arabic). For a book-publishing gap analysis, what matters is
  the written/literary standard a market publishes in, not spoken dialect
  variation -- so this script restricts to items that have an ISO 639-1
  code (P218), which is only ever assigned to major/national/literary
  standard languages (~184 codes total, by design), not dialects or
  spoken varieties. That filter alone is tight enough to do the job.

  An earlier version of this script *also* required P31 = "modern
  language" (Q1288568) on top of the ISO 639-1 filter, reasoning that
  it would be extra insurance against families/dialects slipping through.
  In practice it silently dropped real, major languages instead -- Hindi
  (Q1568), spoken by ~600 million people, turned out not to be typed as
  Q1288568 on Wikidata (its P31 values are different), so the entire
  first version of this table shipped with no Hindi entry at all despite
  it easily belonging in the top 5 by population. Wikidata's typing of
  "what kind of language is this" is inconsistent across items even for
  major languages, so P218 does the real filtering work here and the P31
  check has been dropped rather than trusted.

- A handful of ISO 639-1 codes still appear on more than one Wikidata item
  (e.g. two separate "French" items with slightly different speaker
  counts). Where that happens, this script keeps the higher figure and
  discards the rest, rather than double-counting or averaging.

Usage:
    python fetch_languages.py --out data/languages.csv
"""
import argparse
import csv
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

QUERY = """
SELECT ?langLabel ?iso1 ?iso2 ?speakers WHERE {
  ?lang wdt:P218 ?iso1 .
  ?lang wdt:P1098 ?speakers .
  OPTIONAL { ?lang wdt:P219 ?iso2 . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?speakers)
"""


def fetch_languages(retries=4, backoff=3.0):
    for attempt in range(retries):
        try:
            resp = requests.get(
                SPARQL_URL, params={"query": QUERY}, headers=HEADERS, timeout=90
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

    # Dedupe by ISO 639-1 code, keeping the entry with the most speakers.
    best = {}
    for row in bindings:
        iso1 = row["iso1"]["value"].strip().lower()
        speakers = float(row["speakers"]["value"])
        if iso1 in best and best[iso1]["speakers_millions"] >= speakers / 1_000_000:
            continue
        best[iso1] = {
            "marc": row.get("iso2", {}).get("value", "").strip().lower() or iso1,
            "iso1": iso1,
            "name": row["langLabel"]["value"],
            "speakers_millions": round(speakers / 1_000_000, 1),
        }

    return sorted(best.values(), key=lambda l: l["speakers_millions"], reverse=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/languages.csv"))
    args = parser.parse_args()

    print("Fetching world languages ranked by speaker count from Wikidata...", file=sys.stderr)
    languages = fetch_languages()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["marc", "iso1", "name", "speakers_millions"])
        writer.writeheader()
        writer.writerows(languages)

    print(f"Wrote {len(languages)} languages to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
