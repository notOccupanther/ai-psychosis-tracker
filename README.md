# AI Psychosis Watch

Source for [aipsychosis.watch](https://aipsychosis.watch) — a tracker of reported
AI-induced psychological harm: dependency, delusion, identity confusion and
reality distortion.

## How it updates

Everything needed to update the site lives in this repository and runs on
GitHub Actions. Nothing depends on an external machine, which is what caused
the site to silently stop updating after 31 May 2026.

`.github/workflows/weekly-update.yml` runs every **Monday at 08:00 UTC**:

1. `scripts/test_pipeline.py` — offline test suite, runs first so a broken
   parser fails the job before any network call.
2. `scripts/scrape.py` — fetches candidates, filters, appends to `data.json`.
3. `scripts/generate_rss.py` — regenerates `feed.xml`.
4. Commits and pushes, which triggers the GitHub Pages build.

Run it by hand from the Actions tab ("Weekly update" → Run workflow). It takes a
`dry_run` input that reports what it would add without committing.

`.github/workflows/tests.yml` runs on every push to `main` and every pull
request: the test suite, plus a check that the derived fields in `data.json`
still match what `common.recompute()` produces from the cases.

## Data model

`data.json` in the repo root is the **single source of truth**. There is no
database. Each run reads it, adds what is new, recomputes the derived fields and
writes it back, so the whole pipeline is reproducible from a clean checkout.

`index.html` fetches `data.json` and `commentary.json` at page load, relative to
the site root. Pages serves the **repository root**, so only files at the top
level are published.

Derived fields (`trend`, `categories`, `severity_counts`, `date_range`,
`total_cases`, `generated_at`) are rebuilt by `common.recompute()` — never edit
them by hand.

### Sources

| Source | Key required |
|---|---|
| PubMed (E-utilities) | no |
| arXiv | no |
| Semantic Scholar | no |
| RSS (Guardian, Futurism, PsyPost, WIRED, MIT TR, Ars Technica, 404 Media, TechCrunch) | no |
| Brave News Search | `BRAVE_API_KEY` secret — skipped if absent |

A single source failing is logged and the run continues. If *every* source
fails, the run refuses to write `data.json` rather than publishing an empty
tracker.

### Filtering

A candidate must match an AI term **and** either a psychological-harm term or a
relational term (`scripts/classify.py`). Requiring both keeps out articles that
merely mention "delusion" in an unrelated context.

Category and severity are assigned by keyword. That is deliberately coarser than
the hand-curated labels already in `data.json` — new entries are written with
`"needs_review": true` so a weekly Claude pass can refine them.

## Local use

```bash
python scripts/test_pipeline.py           # offline tests, no network
python scripts/scrape.py --dry-run        # show what would be added
python scripts/scrape.py --days 30        # wider look-back, writes data.json
python scripts/generate_rss.py            # rebuild feed.xml
```

Python 3.11+, standard library only.

## Maintenance notes

- **GitHub disables scheduled workflows after 60 days of repository
  inactivity.** Weekly commits normally reset that clock; if the tracker ever
  goes quiet again, check the Actions tab first.
- `commentary.json` is written weekly by a Claude routine, not by this
  workflow.
- There used to be a `public/` directory mirroring the root files. It was not
  served by Pages and had drifted months out of date — the Week 22 commentary
  was written there and never appeared on the site. It has been removed; the
  repository root is the only published location.
