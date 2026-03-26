# Naturalist Tool

Personal species tracking tool: life lists, targets, and frequency data
across hierarchical locations. Built around eBird and iNaturalist data.

## Setup

    pip install click requests
    python cli.py init

An eBird API key is required for importing species lists and bar chart data.
Get one free at https://ebird.org/api/keygen, then:

    export EBIRD_API_KEY=your_key_here

## Quickstart — Okanogan County

    python cli.py import-species US-WA-047
    python cli.py import-barchart US-WA-047
    python cli.py import-ebird data/raw/MyEBirdData.csv
    python cli.py import-inat <your-inat-username> --place-id 1259
    python cli.py summary "Okanogan County"
    python cli.py life-list "Okanogan County"
    python cli.py targets "Okanogan County" --limit 25
    python cli.py summary "Washington"        # rollup from all counties

## Commands

| Command | Description |
|---------|-------------|
| `init` | Initialise DB and seed locations (USA > Washington > Okanogan County) |
| `add-location NAME TYPE PARENT` | Add a location to the hierarchy |
| `import-species REGION` | Import eBird species list for a region |
| `import-barchart REGION` | Import eBird weekly frequency data |
| `import-ebird CSV` | Import personal eBird MyData CSV export |
| `import-inat USERNAME` | Import personal iNaturalist observations |
| `life-list LOCATION` | Personal life list with rollup from child locations |
| `targets LOCATION` | Species not yet seen, sorted by findability |
| `status SPECIES LOCATION` | Full status for one species at one location |
| `summary LOCATION` | Counts: recorded / seen / photographed |

## Location Hierarchy

Rollup is automatic: querying Washington includes all county observations.

    United States (US)
    └── Washington (US-WA)
        └── Okanogan County (US-WA-047)
            └── [sites — add with add-location]

Add more counties or sites:

    python cli.py add-location "King County" county "Washington" --ebird-region US-WA-033
    python cli.py add-location "Sun Mountain" site "Okanogan County"

## eBird Region Codes

| Location | Code |
|----------|------|
| USA | US |
| Washington | US-WA |
| Okanogan County | US-WA-047 |
| King County | US-WA-033 |
| Yakima County | US-WA-077 |
| Kittitas County | US-WA-037 |
| Douglas County | US-WA-017 |
| Jefferson County | US-WA-031 |
| San Juan County | US-WA-055 |
| Snohomish County | US-WA-061 |

## Data Directory

    data/
      raw/           drop source files here (gitignored)
      processed/     intermediate files (gitignored)
      naturalist.db  SQLite database (gitignored)
