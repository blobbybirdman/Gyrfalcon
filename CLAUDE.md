# Gyrfalcon — Naturalist Tool

Personal species tracking CLI. Replaces a set of per-location Notion databases
that don't scale or connect across locations. Python + SQLite.

## What This Is and Why It Exists

This tool handles the **tracking layer** of a naturalist practice:
- What species have been seen/photographed, where and when
- What species are present at a location but not yet on the personal list (targets)
- Frequency/abundance data to rank targets by findability
- Life lists and rollup at any geographic level

The **knowledge layer** (field guides, ecology notes, species accounts) lives
separately in a Sherpa knowledge base at ~/Sherpa/projects/naturalist/.
These two layers are deliberately separate: this repo = data and queries;
Sherpa = narrative knowledge and field notes.

## Current State

Notion databases being replaced (one per location, manually built as trip prep):
Washington State (active/primary), UK, Costa Rica (~237 birds, strong dataset),
Ecuador, Peru, California, Indonesia, Tanzania.

**Built so far:**
- Full SQLite schema: location, taxon, ebird_frequency, observation, knowledge tables
- Recursive CTE rollup: observations at child locations propagate to parents
- eBird importers: species list API, bar chart frequency data, personal CSV export
- iNaturalist importer: personal observations via public API
- Click CLI: init, add-location, import-species, import-barchart, import-ebird,
  import-inat, life-list, targets, status, summary
- Seeded location hierarchy: United States > Washington > Okanogan County

**Not yet built:**
- Notion migration scripts (CSV export per location → SQLite)
- Additional Washington counties (King US-WA-033, Yakima US-WA-077, Kittitas
  US-WA-037, Douglas US-WA-017, Jefferson US-WA-031, San Juan US-WA-055,
  Snohomish US-WA-061)
- Detection probability model (GLM: P(seen) = f(species, location, effort, season))
- Web/notebook analysis layer
- Multi-taxa frequency sources (iNaturalist/GBIF for plants, mammals, herps)

## Architecture

    cli.py                      Click CLI entry point
    naturalist/
      db.py                     Schema, init_db(), seed_locations()
      queries.py                life_list(), target_list(), species_status(),
                                location_summary()
      importers/
        ebird.py                import_species_list(), import_barchart(),
                                import_personal_csv()
        inat.py                 import_observations()
    data/                       gitignored; SQLite DB and raw source files

## Key Design Decisions

- SQLite — local, portable, no server
- Recursive CTE rollup — querying Washington automatically includes all counties
- eBird bar chart = target ranking — peak frequency across 52 weeks drives ordering
- iNat observations = photographed; eBird CSV = seen
- EBIRD_API_KEY env var required for import-species and import-barchart
- taxa_group field enables multi-taxa queries with same schema
- knowledge table is manually maintained; seen/photographed derived from observations

## Open Questions

- Interface: CLI for data ops; Jupyter notebooks for trip planning feels right —
  lightweight web UI (Flask) worth considering once data layer is solid
- Notion migration: need a script per database mapping Notion columns to schema
- Detection probability model: GLM; needs personal eBird checklist data
- Open source? Could be useful to the birding/naturalist community

## Location Hierarchy

    United States (US)
    └── Washington (US-WA)
        └── Okanogan County (US-WA-047)   ← primary focus

Add counties: python cli.py add-location "King County" county "Washington" --ebird-region US-WA-033

## Quickstart

    pip install click requests
    export EBIRD_API_KEY=your_key
    python cli.py init
    python cli.py import-species US-WA-047
    python cli.py import-barchart US-WA-047
    python cli.py import-ebird data/raw/MyEBirdData.csv
    python cli.py import-inat <username> --place-id 1259
    python cli.py targets "Okanogan County" --limit 25
