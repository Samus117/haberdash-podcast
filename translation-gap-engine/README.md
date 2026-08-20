# Translation Gap Engine

Haberdash Books' business is finding forgotten classics and bringing them
into English (e.g. *The Railway*, Finland's most-read novel, translated for
the first time). This tool runs that idea in reverse: it finds English
public-domain classics that are well-loved in English but have **never been
published in a given other language** — a ranked list of translation
opportunities, weighted by how many people could actually read the result.

## How it works

Three steps, three scripts:

1. **`src/fetch_top_books.py`** — pulls the N most-downloaded
   English-language public-domain books from [Project Gutenberg's
   API (Gutendex)](https://gutendex.com), ranked by real download counts.
   "Public domain" here means "hosted by Gutenberg," which requires US
   public-domain status — copyright can still differ by country, so
   re-check before acting on any specific title.

2. **`src/fetch_translations.py`** — for each book, queries the [Open
   Library Search API](https://openlibrary.org/dev/docs/api/search) by
   title + author and records which languages Open Library has a
   catalogued edition in. This is a heuristic (title/author text matching),
   not a guarantee — see **Known limitations** below.

3. **`src/compute_gaps.py`** — cross-references the result against
   `data/languages.csv` (a reference table of ~120 languages with
   approximate speaker counts) and scores every (book, missing language)
   pair by `relative English popularity x speakers of the missing language
   (millions)`. This surfaces the highest-audience gaps first, not just the
   most numerous ones.

Output lands in `data/`:
- `top_books.json` — the raw book list
- `translations.json` — book list + known languages per book
- `gaps.csv` — every gap found, one row each, ranked
- `gaps_summary.md` — the top 50, human-readable

## Running it

**This has to run somewhere with real internet access.** The session that
built this tool runs in a sandboxed environment whose network policy blocks
Gutenberg, Gutendex, Open Library, and Wikidata outright (confirmed via
repeated 403s, not a guess) — so none of this could be tested against the
live APIs from there. The logic that doesn't need the network
(`compute_gaps.py`, and the language-code alias handling in
`lang_utils.py`) was verified offline against realistic fixture data; the
two fetch scripts are written carefully against the documented API
contracts but have **not yet made a real request**. Treat the first run as
a shakedown, not a known-good pipeline.

### Via GitHub Actions (recommended)

`.github/workflows/translation-gap-engine.yml` runs the full pipeline on
GitHub's own runners (unrestricted internet), weekly on Mondays, or
on-demand from the Actions tab ("Run workflow" → optionally set
`book_count` lower, e.g. `50`, for a fast first test). It commits the
updated `data/` files straight back to the repo when it finishes.

### Locally

```bash
cd translation-gap-engine
pip install -r requirements.txt

python src/fetch_top_books.py --count 50 --out data/top_books.json
python src/fetch_translations.py --in data/top_books.json --out data/translations.json
python src/compute_gaps.py --translations data/translations.json \
  --languages data/languages.csv --out data/gaps.csv --summary data/gaps_summary.md
```

Start with a small `--count` (Gutendex) or `--limit` (Open Library step) to
confirm everything works before committing to a full 1000-book run —
`fetch_translations.py` does one request per book at ~1/second, so 1000
books takes on the order of 20-30 minutes.

## Known limitations (read before acting on the output)

- **Title matching is fuzzy.** `fetch_translations.py` takes Open Library's
  top search hit for `title + first author`. Common titles, omnibus
  editions, or unusual transliterations can mismatch. Any gap you're
  seriously considering acting on is worth a manual check on
  [openlibrary.org](https://openlibrary.org) first.
- **The language table is illustrative, not authoritative.** Speaker
  counts in `data/languages.csv` are rounded, order-of-magnitude figures
  for prioritization, not census data. Codes are standard MARC/ISO 639-2
  bibliographic codes; a handful of languages have two overlapping codes
  (bibliographic vs. terminology — e.g. German is both `ger` and `deu`),
  which `lang_utils.py` treats as equivalent so a code mismatch doesn't
  create a false gap. It doesn't attempt to cover all ~7,000 living
  languages — most have no meaningful book-publishing industry to check
  against; it covers roughly the 120 languages a translation business could
  plausibly publish in.
- **"No Open Library edition" isn't proof a translation has never
  existed.** Older or obscure translations, especially pre-20th-century
  or from smaller presses, may not be catalogued there. For anything
  high-stakes, [UNESCO's Index Translationum](https://www.unesco.org/xtrans/)
  is the authoritative (if dated) global translation bibliography and is
  worth cross-checking — it wasn't wired into this pipeline because its
  interface doesn't offer a simple JSON API, but it's a natural next
  data source to add.
- **A found "gap" is a lead, not a guarantee of rights.** Public domain
  status varies by country and by which edition/translation you'd be
  building from; confirm the specific rights situation before commissioning
  work off any result here.

## Extending it

- Add Wikidata as a second, corroborating source (`P629`/`P407` — editions
  and their languages) to reduce false gaps from Open Library mismatches.
- Add a `subjects` filter to `fetch_top_books.py` if the business wants to
  focus on fiction specifically rather than all of Gutenberg's top
  downloads (which includes reference works, plays, etc.).
- Widen `data/languages.csv` — it's a plain CSV, easy to extend with more
  languages or better speaker-count data from a proper source.
