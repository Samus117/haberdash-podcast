# Translation Gap Engine

Haberdash Books' business is finding forgotten classics and bringing them
into English (e.g. *The Railway*, Finland's most-read novel, translated for
the first time). This tool runs that idea in reverse: it finds English
public-domain classics that are well-loved in English but have **never been
published in a given other language** — a ranked list of translation
opportunities, weighted by how many people could actually read the result.

## How it works

Three steps, three scripts:

1. **`src/fetch_top_books.py`** — queries [Wikidata's public SPARQL
   endpoint](https://query.wikidata.org) for every work that has a
   confirmed Project Gutenberg edition (Wikidata property `P2034`) and an
   original language of English, ranked by **Wikipedia sitelink count**
   (how many different-language Wikipedias have an article on it) as a
   fame/notability proxy. "Public domain" here means "hosted by Gutenberg,"
   which requires US public-domain status — copyright can still differ by
   country, so re-check before acting on any specific title.

   This wasn't the first design — see **Why Wikidata, not Gutendex**
   below for what didn't work and why.

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

## Why Wikidata, not Gutendex

The original design used [Gutendex](https://gutendex.com), a third-party
JSON API mirroring Project Gutenberg's catalog with a clean `download_count`
field — the obvious choice for "most popular." Live testing (from GitHub
Actions, with real internet access) showed it returns a flat `403` on every
request, with both a custom and a standard browser `User-Agent` — almost
certainly bot protection blocking cloud/CI IP ranges outright, not
something a header change fixes.

Project Gutenberg's own site works fine, but its search-results page
(the one sorted by download count) carries its own explicit banner:
*"DON'T USE THIS PAGE FOR SCRAPING... you'll only get your IP blocked,"*
pointing instead to their sanctioned bulk feed, `catalog.rdf.bz2` — which
doesn't include popularity data at all.

So popularity here comes from Wikidata instead: it's a public API
explicitly built for bulk querying (no scraping concerns), and Wikipedia
sitelink count is a standard, widely-used notability proxy. Every result
already carries a confirmed Gutenberg ebook ID, so the practical outcome —
"the N most notable public-domain English books, each with a working
Gutenberg link" — is the same as the original design intended.

## Running it

**This has to run somewhere with real internet access.** The session that
built this tool runs in a sandboxed environment whose network policy blocks
Gutenberg, Gutendex, Open Library, and Wikidata outright (confirmed via
repeated 403s, not a guess) — so this was developed and debugged entirely
through live GitHub Actions runs (diagnostic steps whose logs were read
back), not locally. `compute_gaps.py` and `lang_utils.py` need no network
and were also verified offline against realistic fixture data.

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

Start with a small `--count`/`--limit` to confirm everything works before
committing to a full 1000-book run — `fetch_translations.py` does one
request per book at ~1/second, so 1000 books takes on the order of
20-30 minutes.

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

- Also query Wikidata's `P629`/`P407` (editions and their languages) as a
  second, corroborating source for translation coverage, to reduce false
  gaps from Open Library title/author mismatches.
- Filter `fetch_top_books.py` to fiction specifically (Wikidata has
  `P31`/genre properties) if the business doesn't want reference works,
  religious texts, or plays mixed into the ranking.
- Widen `data/languages.csv` — it's a plain CSV, easy to extend with more
  languages or better speaker-count data from a proper source.
