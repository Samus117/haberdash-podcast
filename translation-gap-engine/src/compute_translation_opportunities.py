#!/usr/bin/env python3
"""
Find notable non-English public-domain books that have NEVER been
published in English -- the direct opposite direction of compute_gaps.py,
and the one that matches Haberdash's actual business (translating a
forgotten foreign classic into English, e.g. *The Railway* from Finnish).

Ranked by the book's own Wikidata sitelink count (how many different-
language Wikipedias cover it) -- a book that's well-known across many
languages but STILL has no English edition is a stronger, more legible
signal of "overdue" than an obscure title with the same gap.

Usage:
    python compute_translation_opportunities.py \
        --translations data/translations_multilang.json \
        --out data/english_gaps.csv --summary data/english_gaps_summary.md
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lang_utils import language_present  # noqa: E402


def compute_opportunities(books):
    opportunities = []
    for book in books:
        if not book.get("matched"):
            continue  # no reliable language data -- skip rather than guess
        have = set(book.get("languages", []))
        if language_present("eng", have):
            continue  # already has an English edition
        opportunities.append({
            "title": book["title"],
            "authors": "; ".join(book.get("authors", [])),
            "source_language": book.get("source_language", ""),
            "gutenberg_id": book["gutenberg_id"],
            "sitelinks": book.get("sitelinks", 0),
            "known_languages": "; ".join(sorted(have)) or "(none catalogued)",
            "edition_count": book.get("edition_count", 0),
        })

    opportunities.sort(key=lambda o: o["sitelinks"], reverse=True)
    return opportunities


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "title", "authors", "source_language", "gutenberg_id",
        "sitelinks", "known_languages", "edition_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows, books, path, top_n=100):
    top = rows[:top_n]
    matched = sum(1 for b in books if b.get("matched"))
    by_language = {}
    for r in rows:
        by_language[r["source_language"]] = by_language.get(r["source_language"], 0) + 1

    lines = [
        "# Untranslated-into-English opportunities",
        "",
        f"{len(books)} non-English books checked, {matched} matched against Open Library, "
        f"{len(rows)} have no known English edition.",
        "",
        "Ranked by the book's own Wikidata sitelink count -- how many different-language "
        "Wikipedias cover it. A book well-known across many languages but still missing "
        "an English edition is the strongest signal of a real, overdue opportunity.",
        "",
        "**Spot-check before commissioning a translation.** Title/author matching against "
        "Open Library is a heuristic; a book can be public domain in its home country "
        "(or in the US) while a specific edition/translation is not, and older or obscure "
        "translations may exist without being catalogued on Open Library.",
        "",
        "## By source language",
        "",
        "| Language | Untranslated books found |",
        "|---|---|",
    ]
    for lang, count in sorted(by_language.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {lang} | {count} |")

    lines += [
        "",
        f"## Top {len(top)} opportunities",
        "",
        "| Rank | Book | Author | Source language | Sitelinks | Known languages |",
        "|---|---|---|---|---|---|",
    ]
    for i, o in enumerate(top, 1):
        lines.append(
            f"| {i} | {o['title']} | {o['authors']} | {o['source_language']} | "
            f"{o['sitelinks']} | {o['known_languages']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("data/translations_multilang.json"))
    parser.add_argument("--out", type=Path, default=Path("data/english_gaps.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/english_gaps_summary.md"))
    args = parser.parse_args()

    books = json.loads(args.translations.read_text(encoding="utf-8"))
    opportunities = compute_opportunities(books)

    write_csv(opportunities, args.out)
    write_summary(opportunities, books, args.summary)

    print(f"Wrote {len(opportunities)} opportunities to {args.out}")
    print(f"Wrote summary to {args.summary}")


if __name__ == "__main__":
    main()
