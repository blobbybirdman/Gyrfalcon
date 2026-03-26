"""Database connection and schema management."""

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
CREATE TABLE IF NOT EXISTS location (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL CHECK(type IN ('country','state','county','site')),
    parent_id       INTEGER REFERENCES location(id),
    ebird_region    TEXT UNIQUE,
    inat_place_id   INTEGER,
    lat             REAL,
    lon             REAL
);

CREATE TABLE IF NOT EXISTS taxon (
    id              INTEGER PRIMARY KEY,
    common_name     TEXT,
    scientific_name TEXT NOT NULL,
    taxa_group      TEXT NOT NULL,
    ebird_code      TEXT UNIQUE,
    inat_taxon_id   INTEGER,
    family          TEXT,
    order_name      TEXT,
    taxonomic_order REAL
);

CREATE TABLE IF NOT EXISTS ebird_frequency (
    id              INTEGER PRIMARY KEY,
    location_id     INTEGER NOT NULL REFERENCES location(id),
    taxon_id        INTEGER NOT NULL REFERENCES taxon(id),
    week            INTEGER NOT NULL CHECK(week BETWEEN 1 AND 52),
    frequency       REAL NOT NULL CHECK(frequency BETWEEN 0 AND 1),
    sample_size     INTEGER,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(location_id, taxon_id, week)
);

CREATE TABLE IF NOT EXISTS observation (
    id              INTEGER PRIMARY KEY,
    location_id     INTEGER NOT NULL REFERENCES location(id),
    taxon_id        INTEGER NOT NULL REFERENCES taxon(id),
    obs_date        TEXT NOT NULL,
    count           TEXT,
    source          TEXT NOT NULL CHECK(source IN ('ebird','inat','manual')),
    source_id       TEXT,
    notes           TEXT,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, source_id, taxon_id)
);

CREATE TABLE IF NOT EXISTS knowledge (
    id              INTEGER PRIMARY KEY,
    taxon_id        INTEGER NOT NULL REFERENCES taxon(id),
    location_id     INTEGER REFERENCES location(id),
    researched      INTEGER NOT NULL DEFAULT 0,
    field_guide     INTEGER NOT NULL DEFAULT 0,
    deep            INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(taxon_id, location_id)
);

CREATE VIEW IF NOT EXISTS v_seen AS
    SELECT DISTINCT o.taxon_id, o.location_id FROM observation o;

CREATE VIEW IF NOT EXISTS v_photographed AS
    SELECT DISTINCT o.taxon_id, o.location_id
    FROM observation o WHERE o.source = 'inat';

CREATE VIEW IF NOT EXISTS v_peak_frequency AS
    SELECT location_id, taxon_id,
           MAX(frequency) AS peak_frequency,
           SUM(CASE WHEN frequency > 0 THEN 1 ELSE 0 END) AS weeks_present
    FROM ebird_frequency
    GROUP BY location_id, taxon_id;
"""


def init_db(db_path: Path = DEFAULT_DB):
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
    print(f"Database initialised: {db_path}")


def seed_locations(db_path: Path = DEFAULT_DB):
    locations = [
        ("United States", "country", None,            "US",       1),
        ("Washington",    "state",   "United States",  "US-WA",   62),
        ("Okanogan County", "county", "Washington",    "US-WA-047", 1259),
    ]
    with get_connection(db_path) as conn:
        id_map = {}
        for name, loc_type, parent_name, ebird_region, inat_place_id in locations:
            parent_id = id_map.get(parent_name)
            conn.execute(
                """INSERT OR IGNORE INTO location
                   (name, type, parent_id, ebird_region, inat_place_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, loc_type, parent_id, ebird_region, inat_place_id)
            )
            row = conn.execute(
                "SELECT id FROM location WHERE name = ?", (name,)
            ).fetchone()
            id_map[name] = row["id"]
        conn.commit()
    print("Locations seeded: United States > Washington > Okanogan County")
