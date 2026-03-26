# Gyrfalcon — Agent Handoff Document

This file is the single source of truth for any agent (or human) picking up this
project. It must be kept current. See **Maintenance Instructions** below.

---

## Maintenance Instructions for Agents

Every time you complete a session that changes the project state, update this file
before finishing. Specifically:

- **Last Session** — replace the entire section with what you just did, in enough
  detail that the next agent needs no other context to understand the current state.
- **Next Steps** — reorder, add, remove, or refine items to reflect what should
  happen next. Mark completed items with ✓ and remove them once they have been
  superseded by at least one subsequent session.
- **Open Questions** — add new questions that came up; remove or answer ones that
  were resolved.
- **Known Issues** — add anything discovered; remove items once fixed.
- **Architecture / Design Decisions** — update only if a decision changed or a new
  significant decision was made. Do not rewrite stable sections on every pass.

If this file grows unwieldy, split it: create a referenced file (e.g.
`docs/design.md`) and add a pointer here. Always keep **Last Session**,
**Next Steps**, and **Known Issues** in this top-level file.

---

## What This Project Is

Personal naturalist species-tracking CLI. Replaces a set of per-location Notion
databases that do not scale or connect across locations.

**Two deliberate layers:**
- **This repo** — data and queries: what was seen, where, when, and how findable
  each species is.
- **Sherpa knowledge base** (`~/Sherpa/projects/naturalist/`) — narrative layer:
  field notes, species accounts, ecology. These two layers are intentionally
  separate and should stay that way.

Primary taxa: birds (eBird as the frequency backbone). Schema is taxa-group-aware
so plants, mammals, herps can be added later with the same structure.

Primary geography: Washington State, Okanogan County as the first focus location.
Other locations (UK, Costa Rica, Ecuador, Peru, California, Indonesia, Tanzania)
to be migrated from Notion later.

---

## Last Session

**Date:** 2026-03-26

Bootstrapped the repository from scratch. All core files pushed to branch
`claude/bootstrap-gyrfalcon-tracker-Lfavb`:

- `naturalist/db.py` — full SQLite schema + `init_db()` + `seed_locations()`
- `naturalist/queries.py` — `life_list()`, `target_list()`, `species_status()`,
  `location_summary()`, all with recursive CTE rollup
- `naturalist/importers/ebird.py` — species list API, bar chart frequency,
  personal CSV export
- `naturalist/importers/inat.py` — personal observations via public API
- `cli.py` — Click CLI wiring all commands
- `README.md`, `CLAUDE.md`, `.gitignore`

No code has been run against a real database yet. The implementation is complete
on paper but untested end-to-end.

---

## Current State

### Built and in the repo

| Component | File | Status |
|-----------|------|--------|
| SQLite schema | `naturalist/db.py` | Complete, untested live |
| Location seeding (US > WA > Okanogan) | `naturalist/db.py` | Complete |
| Recursive CTE rollup | `naturalist/queries.py` | Complete |
| eBird species list importer | `naturalist/importers/ebird.py` | Complete |
| eBird bar chart importer | `naturalist/importers/ebird.py` | Complete |
| eBird personal CSV importer | `naturalist/importers/ebird.py` | Complete |
| iNaturalist observations importer | `naturalist/importers/inat.py` | Complete |
| CLI: init, add-location | `cli.py` | Complete |
| CLI: import-species, import-barchart, import-ebird, import-inat | `cli.py` | Complete |
| CLI: life-list, targets, status, summary | `cli.py` | Complete |

### Not yet built

- Notion migration scripts (per-location CSV export → SQLite)
- Additional Washington counties: King (US-WA-033), Yakima (US-WA-077),
  Kittitas (US-WA-037), Douglas (US-WA-017), Jefferson (US-WA-031),
  San Juan (US-WA-055), Snohomish (US-WA-061)
- Detection probability model (GLM: P(seen) = f(species, location, effort, season))
- Jupyter notebook analysis layer
- Multi-taxa frequency sources (iNaturalist/GBIF for plants, mammals, herps)
- Any automated tests

---

## Next Steps (Prioritized)

1. **End-to-end smoke test** — run `python cli.py init` and `import-species
   US-WA-047` against a real eBird API key; confirm rows appear in the DB.
   Fix any bugs found. This is the gate before anything else.

2. **Import personal data** — run `import-barchart US-WA-047`,
   `import-ebird <MyEBirdData.csv>`, `import-inat <username> --place-id 1259`;
   verify `life-list`, `targets`, and `summary` return sensible output.

3. **Add remaining Washington counties** — use `add-location` for the 7 counties
   listed above; import bar chart data for each so targets can roll up statewide.

4. **Notion migration** — write a script per location that maps Notion CSV columns
   to the observation schema. Costa Rica (~237 birds) is the richest dataset and
   the best first target.

5. **Jupyter notebook layer** — a trip-planning notebook that pulls targets for a
   location, shows peak-frequency week heatmaps, and flags species with knowledge
   gaps (researched=0).

6. **Detection probability model** — GLM on personal eBird checklist data.
   Needs checklist-level effort data (duration, distance) from the eBird CSV,
   which is present in the MyData export but not yet parsed.

7. **Automated tests** — at minimum: schema init, seed, a round-trip import using
   fixture data, and the recursive CTE rollup.

---

## Architecture

```
cli.py                        Click CLI entry point
naturalist/
  db.py                       Schema, init_db(), seed_locations()
  queries.py                  life_list(), target_list(), species_status(),
                              location_summary()
  importers/
    ebird.py                  import_species_list(), import_barchart(),
                              import_personal_csv()
    inat.py                   import_observations()
data/                         gitignored — SQLite DB and raw source files
```

---

## Design Decisions and Rationale

**SQLite, not Postgres.**
Local, portable, zero server overhead. This is a personal tool that runs on one
machine. If it ever needs to be shared or web-hosted, reconsider.

**Recursive CTE for location rollup.**
A single query pattern handles any depth of hierarchy (country > state > county >
site) without application-level tree walking. Querying "Washington" automatically
includes all counties and sites beneath it.

**eBird bar chart as the target-ranking signal.**
Peak frequency across 52 weeks is the best single proxy for "how likely am I to
see this species if I go there." It beats range maps (presence/absence only) and
personal checklists (sparse for targets, by definition). Bar chart data is weekly
and covers all years of eBird data in a region.

**iNat observations = photographed; eBird CSV = seen.**
This is a deliberate semantic split. iNaturalist requires a photo (or sound) for
research-grade records, so source='inat' reliably means documented. eBird CSV
records may be sight records only.

**`taxa_group` column on taxon.**
Enables a single schema to handle birds, plants, mammals, herps without separate
tables. All queries filter by taxa_group; the default is 'bird' everywhere.

**`knowledge` table is manually maintained.**
The researched/field_guide/deep flags cannot be derived from observation data —
they reflect the owner's study state. They are set by hand (or by a future
knowledge-base sync script). Do not attempt to infer them automatically.

**`EBIRD_API_KEY` via environment variable.**
Never hardcode. The key is free but personal. Agents must not commit a key to the
repo; the `.gitignore` covers `.env` but the env-var pattern is the canonical
approach here.

**`data/` directory is fully gitignored.**
The SQLite database and raw source files (MyEBirdData.csv, Notion exports) are
personal data. They must never be committed.

---

## Data Sources and API Notes

### eBird API (requires `EBIRD_API_KEY`)
- Species list: `GET /v2/product/spplist/{region}` — returns species codes only;
  a second call to `/v2/ref/taxonomy/ebird` is needed for names and taxonomy.
  The taxonomy endpoint returns the full global list; filter by the species codes
  from the first call.
- Bar chart: `GET https://ebird.org/barchartData` — TSV format, not JSON.
  Columns 3–54 are weekly frequencies (weeks 1–52); columns 55–106 are sample
  sizes. The first two columns are common name and species code. Lines starting
  with "Sample" are headers to skip.
- Personal CSV: downloaded manually from ebird.org/downloadMyData. Fields used:
  `Common Name`, `Date`, `Count`, `State/Province`, `County`, `Submission ID`.

### iNaturalist API (no key required)
- Observations: `GET https://api.inaturalist.org/v1/observations`
- Paginate with `page` and `per_page=200`; stop when results < 200.
- `place_ids` on each observation is a list of all enclosing places — the importer
  picks the most specific one that matches a known location in the DB.
- `quality_grade=research,needs_id` captures both confirmed and pending IDs.
- Rate limit: 1 request/second is safe; the importer sleeps 1s between pages.

---

## Known Issues

- Bar chart importer matches taxa by `common_name` (the first TSV column). If an
  eBird taxonomy update renames a species, the match will silently fail and those
  frequency rows will be skipped. Mitigation: after import, check row count vs
  expected.
- `import_personal_csv` resolves location by state+county name substring match.
  County names that are substrings of other county names could theoretically
  match the wrong row, though this is unlikely in practice with the current small
  location set.
- The `observation` table has a `UNIQUE(source, source_id, taxon_id)` constraint.
  For eBird CSV imports where `Submission ID` is empty, multiple rows for the same
  species/date would violate this if re-imported. The `INSERT OR IGNORE` silently
  skips them — this is probably fine but worth knowing.
- No tests exist yet. All code is untested against real data.

---

## Open Questions

- **Notion migration format:** Notion CSV exports have inconsistent column names
  across databases. Need to inspect actual exports before writing migration scripts.
- **Detection model effort data:** The eBird MyData CSV includes `Duration (Min)`
  and `Distance Traveled (km)` — these are present but not currently parsed or
  stored. Worth adding an `effort` table or columns to observation before the
  model work begins.
- **Open source:** The schema and CLI could be useful to the birding community.
  Decision deferred until the tool is stable and personal data is cleanly
  separated from code.
- **Flask web UI:** Useful for trip planning on mobile. Not worth building until
  the data layer is solid and the Jupyter layer has been tried first.

---

## Environment Setup

```bash
pip install click requests
export EBIRD_API_KEY=your_key   # get free at https://ebird.org/api/keygen
python cli.py init
```

Drop personal data files in `data/raw/` (gitignored):
- `MyEBirdData.csv` — from ebird.org/downloadMyData
- Notion CSV exports — one per location database

```bash
python cli.py import-species US-WA-047
python cli.py import-barchart US-WA-047
python cli.py import-ebird data/raw/MyEBirdData.csv
python cli.py import-inat <username> --place-id 1259
python cli.py targets "Okanogan County" --limit 25
python cli.py summary "Washington"
```

## Location Hierarchy

```
United States (US)
└── Washington (US-WA)
    └── Okanogan County (US-WA-047)   ← primary focus
```

Add a county:
```bash
python cli.py add-location "King County" county "Washington" --ebird-region US-WA-033
```
