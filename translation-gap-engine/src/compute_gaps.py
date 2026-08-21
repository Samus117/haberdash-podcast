#!/usr/bin/env python3
"""
Cross-reference translations.json against the world-language reference
table to find "gaps": popular, public-domain English books with no known
catalogued edition in a given language.

Produces:
  data/gaps.csv        -- one row per (book, missing language), ranked by
                           opportunity score = relative English popularity
                           x millions of speakers of the missing language
  data/gaps_summary.md -- human-readable top-50 opportunities

Usage:
    python compute_gaps.py --translations data/translations.json \
                            --languages data/languages.csv \
                            --out data/gaps.csv
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lang_utils import language_present  # noqa: E402


def load_languages(path):
    langs = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                speakers = float(row["speakers_millions"])
            except (KeyError, ValueError):
                speakers = 0.0
            langs.append({
                "marc": row["marc"].strip(),
                "iso1": (row.get("iso1") or "").strip(),
                "name": row["name"].strip(),
                "speakers_millions": speakers,
            })
    return langs


def compute_gaps(books, languages, min_speakers=1.0):
    languages = [
        l for l in languages
        if l["marc"] != "eng" and l["speakers_millions"] >= min_speakers
    ]
    max_sitelinks = max((b.get("sitelinks", 0) for b in books), default=1) or 1

    gaps = []
    for book in books:
        if not book.get("matched"):
            continue  # no reliable language data for this title -- skip rather than guess
        have = set(book.get("languages", []))
        popularity = book.get("sitelinks", 0) / max_sitelinks  # 0..1
        for lang in languages:
            if language_present(lang["marc"], have):
                continue
            score = popularity * lang["speakers_millions"]
            gaps.append({
                "title": book["title"],
                "authors": "; ".join(book.get("authors", [])),
                "source": book.get("source", "gutenberg"),
                "source_url": book.get("wikisource_url") or (
                    f"https://www.gutenberg.org/ebooks/{book['gutenberg_id']}"
                    if book.get("gutenberg_id") is not None else ""
                ),
                "sitelinks": book.get("sitelinks", 0),
                "missing_language": lang["name"],
                "language_marc": lang["marc"],
                "speakers_millions": lang["speakers_millions"],
                "opportunity_score": round(score, 3),
            })

    gaps.sort(key=lambda g: g["opportunity_score"], reverse=True)
    return gaps


def write_csv(gaps, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(gaps[0].keys()) if gaps else [
        "title", "authors", "source", "source_url", "sitelinks",
        "missing_language", "language_marc", "speakers_millions", "opportunity_score",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(gaps)


def write_summary(gaps, books, path, top_n=50):
    top = gaps[:top_n]
    matched = sum(1 for b in books if b.get("matched"))
    lines = [
        "# Translation gap opportunities",
        "",
        f"{len(books)} books checked, {matched} matched against Open Library, "
        f"{len(gaps)} book/language gaps found.",
        "",
        "Ranked by opportunity score = (relative popularity in English) x "
        "(speakers of the missing language, millions). This surfaces books "
        "that are both well-loved in English *and* missing from a language "
        "with a large potential audience -- not just any gap.",
        "",
        f"Top {len(top)} shown below. **Spot-check any of these before commissioning "
        "a translation** -- title/author matching against Open Library is a "
        "heuristic, and a book can be legitimately public domain in the US "
        "while still under copyright (or already translated under a "
        "different edition title) elsewhere.",
        "",
        "| Rank | Book | Author | Missing language | Speakers (M) | Score |",
        "|---|---|---|---|---|---|",
    ]
    for i, g in enumerate(top, 1):
        lines.append(
            f"| {i} | {g['title']} | {g['authors']} | {g['missing_language']} | "
            f"{g['speakers_millions']:.0f} | {g['opportunity_score']:.2f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translations", type=Path, default=Path("data/translations.json"))
    parser.add_argument("--languages", type=Path, default=Path("data/languages.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/gaps.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/gaps_summary.md"))
    parser.add_argument("--min-speakers", type=float, default=1.0,
                         help="ignore languages with fewer than this many million speakers")
    args = parser.parse_args()

    books = json.loads(args.translations.read_text(encoding="utf-8"))
    languages = load_languages(args.languages)

    gaps = compute_gaps(books, languages, min_speakers=args.min_speakers)

    write_csv(gaps, args.out)
    write_summary(gaps, books, args.summary)

    print(f"Wrote {len(gaps)} gap rows to {args.out}")
    print(f"Wrote summary to {args.summary}")


if __name__ == "__main__":
    main()
