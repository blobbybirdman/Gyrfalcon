"""Database schema, connection, and seed data."""

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).parent.parent / "data" / "naturalist.db"


def get_connection(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
-- Full Linnaean hierarchy, denormalized for query simplicity.
-- taxa_group is a convenience label (bird/mammal/plant/insect/etc) for
-- filtering without needing to know the exact class name.
CREATE TABLE IF NOT EXISTS taxon (
    id              INTEGER PRIMARY KEY,
    scientific_name TEXT NOT NULL,
    common_name     TEXT,
    rank            TEXT NOT NULL DEFAULT 'species',
    taxa_group      TEXT,
    kingdom         TEXT,
    phylum          TEXT,
    class           TEXT,
    order_name      TEXT,
    family          TEXT,
    genus           TEXT,
    ebird_code      TEXT UNIQUE,
    inat_taxon_id   INTEGER UNIQUE,
    gbif_taxon_id   INTEGER,
    taxonomic_order REAL
);

-- Administrative geographic hierarchy (country > state > county).
-- This is the rollup hierarchy for life lists and regional lists.
-- Frequency data attaches here.
CREATE TABLE IF NOT EXISTS region (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL CHECK(type IN ('country','state','county')),
    parent_id       INTEGER REFERENCES region(id),
    ebird_region    TEXT UNIQUE,
    inat_place_id   INTEGER
);

-- Specific sites and hotspots used for trip planning.
-- Each location belongs to a containing admin region (county usually).
-- Observations at a location roll up through location.region_id.
CREATE TABLE IF NOT EXISTS location (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT NOT NULL,
    type                 TEXT NOT NULL DEFAULT 'hotspot'
                             CHECK(type IN ('hotspot','site','patch','reserve','other')),
    region_id            INTEGER NOT NULL REFERENCES region(id),
    ebird_location_id    TEXT UNIQUE,
    inat_place_id        INTEGER,
    lat                  REAL,
    lon                  REAL,
    num_species_all_time INTEGER,
    num_checklists       INTEGER,
    last_obs_date        TEXT
);

-- eBird bar chart weekly frequency data at the admin region level.
-- frequency = fraction of checklists the species appeared on (0.0-1.0).
-- mean_effort_minutes: mean checklist duration for that region/week.
--   NULL until back-filled from personal CSV data.
--   Used to compute P(1hr) = 1 - (1 - frequency)^(60/mean_effort_minutes).
--   Falls back to raw frequency as proxy when NULL.
CREATE TABLE IF NOT EXISTS region_frequency (
    id                  INTEGER PRIMARY KEY,
    region_id           INTEGER NOT NULL REFERENCES region(id),
    taxon_id            INTEGER NOT NULL REFERENCES taxon(id),
    week                INTEGER NOT NULL CHECK(week BETWEEN 1 AND 52),
    frequency           REAL    NOT NULL CHECK(frequency BETWEEN 0 AND 1),
    sample_size         INTEGER,
    mean_effort_minutes REAL,
    imported_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(region_id, taxon_id, week)
);

-- Same as region_frequency but at the specific hotspot/location level.
-- P(1hr) lookup at trip planning time prefers this over region_frequency.
CREATE TABLE IF NOT EXISTS location_frequency (
    id                  INTEGER PRIMARY KEY,
    location_id         INTEGER NOT NULL REFERENCES location(id),
    taxon_id            INTEGER NOT NULL REFERENCES taxon(id),
    week                INTEGER NOT NULL CHECK(week BETWEEN 1 AND 52),
    frequency           REAL    NOT NULL CHECK(frequency BETWEEN 0 AND 1),
    sample_size         INTEGER,
    mean_effort_minutes REAL,
    imported_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(location_id, taxon_id, week)
);

-- Placeholder for iNat-sourced frequency data (non-bird taxa).
-- obs_count / observer_count gives a relative frequency proxy.
-- Calibration to P(1hr) for non-bird taxa is an open problem.
CREATE TABLE IF NOT EXISTS inat_frequency (
    id              INTEGER PRIMARY KEY,
    region_id       INTEGER NOT NULL REFERENCES region(id),
    taxon_id        INTEGER NOT NULL REFERENCES taxon(id),
    month           INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
    obs_count       INTEGER NOT NULL DEFAULT 0,
    observer_count  INTEGER,
    year_span       INTEGER,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(region_id, taxon_id, month)
);

-- A single observing outing. Groups observations and stores effort data.
-- eBird CSV: one checklist per Submission ID, with duration/distance.
-- iNat: no checklist concept; checklist_id is NULL on those observations.
CREATE TABLE IF NOT EXISTS checklist (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL CHECK(source IN ('ebird','inat')),
    source_id        TEXT UNIQUE,
    location_id      INTEGER REFERENCES location(id),
    region_id        INTEGER NOT NULL REFERENCES region(id),
    obs_date         TEXT NOT NULL,
    start_time       TEXT,
    duration_minutes INTEGER,
    distance_km      REAL,
    observer_count   INTEGER NOT NULL DEFAULT 1,
    complete         INTEGER NOT NULL DEFAULT 1
);

-- Personal observations. Sync-only — eBird and iNat are canonical sources.
-- region_id is always the most specific admin region (county if known).
-- location_id is the specific hotspot/site (nullable).
-- media=1 means photo/sound documented (all iNat; eBird defaults to 0).
CREATE TABLE IF NOT EXISTS observation (
    id              INTEGER PRIMARY KEY,
    checklist_id    INTEGER REFERENCES checklist(id),
    taxon_id        INTEGER NOT NULL REFERENCES taxon(id),
    region_id       INTEGER NOT NULL REFERENCES region(id),
    location_id     INTEGER REFERENCES location(id),
    obs_date        TEXT NOT NULL,
    count           TEXT,
    source          TEXT NOT NULL CHECK(source IN ('ebird','inat')),
    source_id       TEXT,
    media           INTEGER NOT NULL DEFAULT 0,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, source_id, taxon_id)
);

-- Manual knowledge/study flags per taxon, optionally per region.
-- Not derived from observations; maintained by hand or future sync.
CREATE TABLE IF NOT EXISTS knowledge (
    id          INTEGER PRIMARY KEY,
    taxon_id    INTEGER NOT NULL REFERENCES taxon(id),
    region_id   INTEGER REFERENCES region(id),
    researched  INTEGER NOT NULL DEFAULT 0,
    field_guide INTEGER NOT NULL DEFAULT 0,
    deep        INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(taxon_id, region_id)
);

-- A named trip (big day, field trip, holiday, etc.).
CREATE TABLE IF NOT EXISTS trip (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    start_date  TEXT,
    end_date    TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Locations within a trip with planned effort.
-- visit_date determines which week's frequency data to use for P(1hr).
-- planned_hours drives P(location) = 1 - (1 - P(1hr))^planned_hours.
CREATE TABLE IF NOT EXISTS trip_location (
    id            INTEGER PRIMARY KEY,
    trip_id       INTEGER NOT NULL REFERENCES trip(id),
    location_id   INTEGER NOT NULL REFERENCES location(id),
    visit_date    TEXT NOT NULL,
    planned_hours REAL NOT NULL,
    visit_order   INTEGER,
    notes         TEXT
);

-- Global life list: any taxon observed at least once anywhere.
CREATE VIEW IF NOT EXISTS v_life_list AS
    SELECT DISTINCT taxon_id FROM observation;

-- Regional seen list: taxon seen in each specific region.
-- Use with recursive CTE on region for rollup.
CREATE VIEW IF NOT EXISTS v_seen_in_region AS
    SELECT DISTINCT taxon_id, region_id FROM observation;

-- Peak frequency per region/taxon across all 52 weeks.
CREATE VIEW IF NOT EXISTS v_region_peak_frequency AS
    SELECT region_id, taxon_id,
           MAX(frequency)                                        AS peak_frequency,
           SUM(CASE WHEN frequency > 0 THEN 1 ELSE 0 END)       AS weeks_present
    FROM region_frequency
    GROUP BY region_id, taxon_id;

-- Peak frequency per location/taxon across all 52 weeks.
CREATE VIEW IF NOT EXISTS v_location_peak_frequency AS
    SELECT location_id, taxon_id,
           MAX(frequency)                                        AS peak_frequency,
           SUM(CASE WHEN frequency > 0 THEN 1 ELSE 0 END)       AS weeks_present
    FROM location_frequency
    GROUP BY location_id, taxon_id;
"""


def init_db(db_path: Path = DEFAULT_DB):
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
    print(f"Database initialised: {db_path}")


def seed_regions(db_path: Path = DEFAULT_DB):
    """Seed the core US > Washington > Okanogan County region hierarchy."""
    regions = [
        ("United States",    "country", None,            "US",        1),
        ("Washington",       "state",   "United States", "US-WA",     62),
        ("Okanogan County",  "county",  "Washington",    "US-WA-047", 1259),
    ]
    with get_connection(db_path) as conn:
        id_map = {}
        for name, rtype, parent_name, ebird_region, inat_place_id in regions:
            parent_id = id_map.get(parent_name)
            conn.execute(
                """INSERT OR IGNORE INTO region
                   (name, type, parent_id, ebird_region, inat_place_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, rtype, parent_id, ebird_region, inat_place_id)
            )
            row = conn.execute(
                "SELECT id FROM region WHERE name = ?", (name,)
            ).fetchone()
            id_map[name] = row["id"]
        conn.commit()
    print("Seeded: United States > Washington > Okanogan County")
