#!/usr/bin/env python3
"""
Fetch the top N public-domain books in EACH of the top M world languages
(by speaker population, from data/languages.csv), and combine them into one
book list -- the reverse direction of fetch_top_books.py's English-only
default: this is "what are the most notable books in French / German /
Finnish / ... that a translation-focused business might not yet know about,"
not "what English books are missing elsewhere."

English itself is skipped as a source language (it's the target we're
checking coverage against, not a candidate to translate into English).

Realistic expectation, stated up front: most non-English languages have far
fewer than N notable works with a confirmed Project Gutenberg edition --
Gutenberg's non-English catalog is real but much smaller than its English
one. Large literary languages (French, German, Spanish, Russian, Italian,
Portuguese, Dutch, Finnish...) will come close to N; many others will
return only a handful, some zero. That's reported per-language rather than
padded to look like a full 1000.

Usage:
    python fetch_top_books_multilang.py --languages data/languages.csv \
        --num-languages 50 --count-per-language 1000 \
        --out data/top_books_multilang.json
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_top_books import fetch_top_books  # noqa: E402


def load_top_languages(path, num_languages):
    langs = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            iso1 = (row.get("iso1") or "").strip()
            if not iso1 or iso1 == "en":
                continue
            langs.append({"iso1": iso1, "name": row["name"].strip()})
    return langs[:num_languages]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", type=Path, default=Path("data/languages.csv"))
    parser.add_argument("--num-languages", type=int, default=50)
    parser.add_argument("--count-per-language", type=int, default=1000)
    parser.add_argument("--out", type=Path, default=Path("data/top_books_multilang.json"))
    args = parser.parse_args()

    languages = load_top_languages(args.languages, args.num_languages)
    print(f"Fetching top {args.count_per_language} books each for {len(languages)} languages...",
          file=sys.stderr)

    all_books = []
    per_language_counts = {}
    for i, lang in enumerate(languages, 1):
        print(f"[{i}/{len(languages)}] {lang['name']} ({lang['iso1']})...", file=sys.stderr)
        try:
            books = fetch_top_books(args.count_per_language, language=lang["iso1"])
        except Exception as exc:  # noqa: BLE001 -- one bad language shouldn't kill the run
            print(f"    failed ({exc}), skipping", file=sys.stderr)
            books = []
        print(f"    got {len(books)} books", file=sys.stderr)
        per_language_counts[lang["name"]] = len(books)
        all_books.extend(books)

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(all_books, indent=2, ensure_ascii=False), encoding="utf-8")

        time.sleep(1.0)  # be a good citizen of a free public API between languages

    print(f"\nDone. {len(all_books)} books across {len(languages)} languages.", file=sys.stderr)
    print("Per-language yield:", file=sys.stderr)
    for name, count in sorted(per_language_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>5}  {name}", file=sys.stderr)


if __name__ == "__main__":
    main()
