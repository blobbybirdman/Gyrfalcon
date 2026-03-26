"""
eBird importers: species list API, bar chart frequency data, personal CSV export.
Requires EBIRD_API_KEY environment variable.
Get a key at https://ebird.org/api/keygen
"""

import csv
import os
from datetime import datetime
from pathlib import Path

import requests

from naturalist.db import get_connection, DEFAULT_DB

EBIRD_API_BASE = "https://api.ebird.org/v2"
EBIRD_BARCHART_URL = "https://ebird.org/barchartData"


def _get_api_key() -> str:
    key = os.environ.get("EBIRD_API_KEY")
    if not key:
        raise EnvironmentError(
            "Set EBIRD_API_KEY environment variable. "
            "Get a key at: https://ebird.org/api/keygen"
        )
    return key


def _headers() -> dict:
    return {"X-eBirdApiToken": _get_api_key()}


def import_species_list(region: str, taxa_group: str = "bird",
                        db_path: Path = DEFAULT_DB) -> int:
    """Fetch all species ever recorded in a region and upsert into taxon table."""
    species_codes = requests.get(
        f"{EBIRD_API_BASE}/product/spplist/{region}",
        headers=_headers(), timeout=30
    ).json()

    taxonomy = {
        t["speciesCode"]: t
        for t in requests.get(
            f"{EBIRD_API_BASE}/ref/taxonomy/ebird",
            headers=_headers(),
            params={"fmt": "json", "locale": "en"},
            timeout=60
        ).json()
    }

    count = 0
    with get_connection(db_path) as conn:
        for code in species_codes:
            t = taxonomy.get(code)
            if not t:
                continue
            conn.execute(
                """INSERT INTO taxon
                   (common_name, scientific_name, taxa_group,
                    ebird_code, family, order_name, taxonomic_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ebird_code) DO UPDATE SET
                     common_name = excluded.common_name,
                     scientific_name = excluded.scientific_name,
                     family = excluded.family,
                     order_name = excluded.order_name,
                     taxonomic_order = excluded.taxonomic_order""",
                (t.get("comName"), t.get("sciName"), taxa_group, code,
                 t.get("familyComName"), t.get("order"), t.get("taxonOrder"))
            )
            count += 1
        conn.commit()
    print(f"Imported {count} species for region {region}")
    return count


def import_barchart(region: str, db_path: Path = DEFAULT_DB) -> int:
    """Download eBird bar chart data (52 weekly frequencies) for a region."""
    resp = requests.get(
        EBIRD_BARCHART_URL,
        params={"r": region, "bmo": 1, "emo": 12,
                "byr": 1900, "eyr": datetime.now().year, "fmt": "tsv"},
        headers=_headers(), timeout=60
    )
    resp.raise_for_status()

    with get_connection(db_path) as conn:
        loc = conn.execute(
            "SELECT id FROM location WHERE ebird_region = ?", (region,)
        ).fetchone()
        if not loc:
            raise ValueError(f"Location '{region}' not found. Run init first.")
        location_id = loc["id"]

        count = 0
        for line in resp.text.splitlines():
            if not line.strip() or line.startswith("Sample"):
                continue
            parts = line.split("\t")
            if len(parts) < 54:
                continue
            taxon = conn.execute(
                "SELECT id FROM taxon WHERE common_name = ?", (parts[0],)
            ).fetchone()
            if not taxon:
                continue
            try:
                freqs = [float(x) if x else 0.0 for x in parts[2:54]]
                samples = [int(x) if x else 0 for x in parts[54:106]] if len(parts) > 54 else []
            except ValueError:
                continue
            for i, freq in enumerate(freqs):
                sample = samples[i] if i < len(samples) else None
                conn.execute(
                    """INSERT INTO ebird_frequency
                       (location_id, taxon_id, week, frequency, sample_size)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(location_id, taxon_id, week) DO UPDATE SET
                         frequency = excluded.frequency,
                         sample_size = excluded.sample_size,
                         imported_at = datetime('now')""",
                    (location_id, taxon["id"], i + 1, freq, sample)
                )
                count += 1
        conn.commit()
    print(f"Imported bar chart data for {region}: {count} frequency records")
    return count


def import_personal_csv(csv_path: Path, db_path: Path = DEFAULT_DB) -> int:
    """Import personal eBird observations from MyData CSV export."""
    csv_path = Path(csv_path)
    with get_connection(db_path) as conn:
        taxon_map = {r["common_name"]: r["id"]
                     for r in conn.execute("SELECT id, common_name FROM taxon")}
        location_map = {r["ebird_region"]: r["id"]
                        for r in conn.execute(
                            "SELECT id, ebird_region FROM location "
                            "WHERE ebird_region IS NOT NULL")}
        count = skipped = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                taxon_id = taxon_map.get(row.get("Common Name", "").strip())
                if not taxon_id:
                    skipped += 1
                    continue
                state = row.get("State/Province", "").strip()
                county = row.get("County", "").strip()
                location_id = None
                if state and county:
                    loc = conn.execute(
                        """SELECT id FROM location
                           WHERE type = 'county' AND name LIKE ?
                           AND parent_id = (SELECT id FROM location
                                            WHERE ebird_region = ?)""",
                        (f"%{county}%", state)
                    ).fetchone()
                    if loc:
                        location_id = loc["id"]
                if not location_id:
                    location_id = location_map.get(state)
                if not location_id:
                    skipped += 1
                    continue
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO observation
                           (location_id, taxon_id, obs_date, count, source, source_id)
                           VALUES (?, ?, ?, ?, 'ebird', ?)""",
                        (location_id, taxon_id,
                         row.get("Date", "").strip(),
                         row.get("Count", "").strip(),
                         row.get("Submission ID", "").strip())
                    )
                    count += 1
                except Exception:
                    skipped += 1
        conn.commit()
    print(f"Imported {count} observations from {csv_path.name} ({skipped} skipped)")
    return count
