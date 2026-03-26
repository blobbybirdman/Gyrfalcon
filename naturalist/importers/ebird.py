"""
eBird importers.

Requires EBIRD_API_KEY environment variable.
Get a free key at https://ebird.org/api/keygen

Functions
---------
import_species_list   Fetch all species ever recorded in a region → taxon table.
import_barchart_region    Weekly frequency for an admin region → region_frequency.
import_barchart_location  Weekly frequency for a hotspot (L-code) → location_frequency.
import_hotspots           Discover top-N hotspots in a region → location table.
import_personal_csv       Personal MyData CSV → checklist + observation tables.
"""

import csv
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

from naturalist.db import get_connection, DEFAULT_DB

EBIRD_API = "https://api.ebird.org/v2"
EBIRD_BARCHART = "https://ebird.org/barchartData"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _key() -> str:
    k = os.environ.get("EBIRD_API_KEY")
    if not k:
        raise EnvironmentError(
            "Set EBIRD_API_KEY. Get a free key at https://ebird.org/api/keygen"
        )
    return k


def _headers() -> dict:
    return {"X-eBirdApiToken": _key()}


# ---------------------------------------------------------------------------
# Species list + taxonomy
# ---------------------------------------------------------------------------

def import_species_list(region: str, taxa_group: str = "bird",
                        db_path: Path = DEFAULT_DB) -> int:
    """
    Fetch all species codes ever recorded in a region, then pull full
    taxonomy for those codes, and upsert into the taxon table.

    taxa_group is stored as a convenience label (e.g. 'bird') alongside the
    full Linnaean hierarchy so queries can filter without knowing class names.
    """
    codes = requests.get(
        f"{EBIRD_API}/product/spplist/{region}",
        headers=_headers(), timeout=30
    ).json()

    taxonomy = {
        t["speciesCode"]: t
        for t in requests.get(
            f"{EBIRD_API}/ref/taxonomy/ebird",
            headers=_headers(),
            params={"fmt": "json", "locale": "en"},
            timeout=60
        ).json()
    }

    count = 0
    with get_connection(db_path) as conn:
        for code in codes:
            t = taxonomy.get(code)
            if not t:
                continue
            sci = t.get("sciName", "")
            genus = sci.split()[0] if sci else None
            conn.execute(
                """INSERT INTO taxon
                       (scientific_name, common_name, rank, taxa_group,
                        order_name, family, genus, ebird_code, taxonomic_order)
                   VALUES (?, ?, 'species', ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ebird_code) DO UPDATE SET
                       common_name     = excluded.common_name,
                       scientific_name = excluded.scientific_name,
                       taxa_group      = excluded.taxa_group,
                       family          = excluded.family,
                       order_name      = excluded.order_name,
                       genus           = excluded.genus,
                       taxonomic_order = excluded.taxonomic_order""",
                (sci, t.get("comName"), taxa_group,
                 t.get("order"), t.get("familyComName"), genus,
                 code, t.get("taxonOrder"))
            )
            count += 1
        conn.commit()
    print(f"Imported {count} species for {region}")
    return count


# ---------------------------------------------------------------------------
# Bar chart parsing (shared)
# ---------------------------------------------------------------------------

def _parse_barchart(text: str) -> list[dict]:
    """
    Parse eBird barchartData TSV.

    Columns: common_name, species_code, freq_wk1..52, sample_wk1..52
    Returns list of {name, code, freqs[52], samples[52]}.
    """
    records = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("Sample"):
            continue
        parts = line.split("\t")
        if len(parts) < 54:
            continue
        try:
            freqs = [float(x) if x else 0.0 for x in parts[2:54]]
            samples = (
                [int(float(x)) if x else 0 for x in parts[54:106]]
                if len(parts) > 54 else [None] * 52
            )
        except ValueError:
            continue
        records.append({
            "name": parts[0].strip(),
            "code": parts[1].strip(),
            "freqs": freqs,
            "samples": samples,
        })
    return records


def _fetch_barchart(r_code: str) -> str:
    resp = requests.get(
        EBIRD_BARCHART,
        params={"r": r_code, "bmo": 1, "emo": 12,
                "byr": 1900, "eyr": datetime.now().year, "fmt": "tsv"},
        headers=_headers(), timeout=60
    )
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Bar chart — admin region
# ---------------------------------------------------------------------------

def import_barchart_region(region: str, db_path: Path = DEFAULT_DB) -> int:
    """
    Import eBird bar chart weekly frequency data for an admin region
    (e.g. US-WA-047) into the region_frequency table.

    Species must already be in the taxon table (run import_species_list first).
    Matches by ebird_code first, then by common_name as fallback.
    """
    text = _fetch_barchart(region)

    with get_connection(db_path) as conn:
        reg = conn.execute(
            "SELECT id FROM region WHERE ebird_region = ?", (region,)
        ).fetchone()
        if not reg:
            raise ValueError(f"Region '{region}' not found. Run init first.")
        region_id = reg["id"]

        code_map = {r["ebird_code"]: r["id"] for r in conn.execute(
            "SELECT id, ebird_code FROM taxon WHERE ebird_code IS NOT NULL")}
        name_map = {r["common_name"]: r["id"] for r in conn.execute(
            "SELECT id, common_name FROM taxon WHERE common_name IS NOT NULL")}

        count = 0
        for rec in _parse_barchart(text):
            taxon_id = code_map.get(rec["code"]) or name_map.get(rec["name"])
            if not taxon_id:
                continue
            for i, freq in enumerate(rec["freqs"]):
                conn.execute(
                    """INSERT INTO region_frequency
                           (region_id, taxon_id, week, frequency, sample_size)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(region_id, taxon_id, week) DO UPDATE SET
                           frequency   = excluded.frequency,
                           sample_size = excluded.sample_size,
                           imported_at = datetime('now')""",
                    (region_id, taxon_id, i + 1, freq,
                     rec["samples"][i] if i < len(rec["samples"]) else None)
                )
                count += 1
        conn.commit()
    print(f"Bar chart imported for region {region}: {count} frequency records")
    return count


# ---------------------------------------------------------------------------
# Bar chart — specific hotspot
# ---------------------------------------------------------------------------

def import_barchart_location(ebird_location_id: str,
                              db_path: Path = DEFAULT_DB) -> int:
    """
    Import eBird bar chart frequency data for a specific hotspot (L-code)
    into the location_frequency table.

    The location must already exist in the location table
    (run import_hotspots first).
    """
    text = _fetch_barchart(ebird_location_id)

    with get_connection(db_path) as conn:
        loc = conn.execute(
            "SELECT id FROM location WHERE ebird_location_id = ?",
            (ebird_location_id,)
        ).fetchone()
        if not loc:
            raise ValueError(
                f"Location '{ebird_location_id}' not in DB. "
                "Run import-hotspots first."
            )
        location_id = loc["id"]

        code_map = {r["ebird_code"]: r["id"] for r in conn.execute(
            "SELECT id, ebird_code FROM taxon WHERE ebird_code IS NOT NULL")}
        name_map = {r["common_name"]: r["id"] for r in conn.execute(
            "SELECT id, common_name FROM taxon WHERE common_name IS NOT NULL")}

        count = 0
        for rec in _parse_barchart(text):
            taxon_id = code_map.get(rec["code"]) or name_map.get(rec["name"])
            if not taxon_id:
                continue
            for i, freq in enumerate(rec["freqs"]):
                conn.execute(
                    """INSERT INTO location_frequency
                           (location_id, taxon_id, week, frequency, sample_size)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(location_id, taxon_id, week) DO UPDATE SET
                           frequency   = excluded.frequency,
                           sample_size = excluded.sample_size,
                           imported_at = datetime('now')""",
                    (location_id, taxon_id, i + 1, freq,
                     rec["samples"][i] if i < len(rec["samples"]) else None)
                )
                count += 1
        conn.commit()
    print(f"Bar chart imported for {ebird_location_id}: {count} records")
    return count


# ---------------------------------------------------------------------------
# Hotspot discovery
# ---------------------------------------------------------------------------

def import_hotspots(region: str, top_n: int = 100,
                    with_barchart: bool = False,
                    db_path: Path = DEFAULT_DB) -> int:
    """
    Fetch eBird hotspots for a region, sort by numSpeciesAllTime,
    take top_n, and upsert into the location table.

    If with_barchart=True, also import bar chart data for each hotspot.
    Expects that the species list has already been imported so taxon
    records exist for frequency data to link to.
    """
    hotspots = requests.get(
        f"{EBIRD_API}/ref/hotspot/{region}",
        headers=_headers(),
        params={"fmt": "json"},
        timeout=30
    ).json()

    hotspots = sorted(
        hotspots, key=lambda h: h.get("numSpeciesAllTime", 0), reverse=True
    )[:top_n]

    with get_connection(db_path) as conn:
        region_map = {
            r["ebird_region"]: r["id"]
            for r in conn.execute(
                "SELECT id, ebird_region FROM region WHERE ebird_region IS NOT NULL"
            )
        }

        count = 0
        imported_l_codes = []
        for h in hotspots:
            # Resolve to most specific admin region in DB
            region_id = (
                region_map.get(h.get("subnational2Code")) or
                region_map.get(h.get("subnational1Code")) or
                region_map.get(h.get("countryCode"))
            )
            if not region_id:
                continue
            conn.execute(
                """INSERT INTO location
                       (name, type, region_id, ebird_location_id,
                        lat, lon, num_species_all_time, last_obs_date)
                   VALUES (?, 'hotspot', ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ebird_location_id) DO UPDATE SET
                       name                 = excluded.name,
                       num_species_all_time = excluded.num_species_all_time,
                       last_obs_date        = excluded.last_obs_date""",
                (h.get("locName"), region_id, h.get("locId"),
                 h.get("lat"), h.get("lng"),
                 h.get("numSpeciesAllTime"), h.get("latestObsDt"))
            )
            count += 1
            imported_l_codes.append(h.get("locId"))
        conn.commit()

    print(f"Imported {count} hotspots for {region}")

    if with_barchart:
        for i, l_code in enumerate(imported_l_codes, 1):
            print(f"  Bar chart {i}/{len(imported_l_codes)}: {l_code}")
            try:
                import_barchart_location(l_code, db_path)
                time.sleep(0.5)
            except Exception as e:
                print(f"    Skipped: {e}")

    return count


# ---------------------------------------------------------------------------
# Personal eBird CSV
# ---------------------------------------------------------------------------

def import_personal_csv(csv_path: Path, db_path: Path = DEFAULT_DB) -> tuple[int, int]:
    """
    Import personal eBird observations from a MyData CSV export.

    Creates checklist records (with effort: duration, distance) and
    observation records linked to those checklists.

    Region resolution order:
      1. County match under the state (most specific)
      2. State match
      Observations that cannot be resolved to a known region are skipped.

    Location resolution: matches on ebird_location_id (L-code) if the
    hotspot has already been imported via import_hotspots. Otherwise
    location_id on the observation is left NULL.

    Returns (checklists_imported, observations_imported).
    """
    csv_path = Path(csv_path)

    with get_connection(db_path) as conn:
        taxon_map = {r["common_name"]: r["id"] for r in conn.execute(
            "SELECT id, common_name FROM taxon WHERE common_name IS NOT NULL")}
        location_map = {r["ebird_location_id"]: r["id"] for r in conn.execute(
            "SELECT id, ebird_location_id FROM location "
            "WHERE ebird_location_id IS NOT NULL")}
        region_by_code = {r["ebird_region"]: r["id"] for r in conn.execute(
            "SELECT id, ebird_region FROM region WHERE ebird_region IS NOT NULL")}

        # Group all rows by Submission ID
        checklists: dict[str, list] = defaultdict(list)
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                sub_id = row.get("Submission ID", "").strip()
                if sub_id:
                    checklists[sub_id].append(row)

        cl_count = obs_count = skipped = 0

        for sub_id, rows in checklists.items():
            first = rows[0]

            # --- Resolve region ---
            state_code = first.get("State/Province", "").strip()
            county_name = first.get("County", "").strip()
            region_id = None

            if county_name and state_code:
                state_id = region_by_code.get(state_code)
                if state_id:
                    county_row = conn.execute(
                        """SELECT id FROM region
                           WHERE type = 'county' AND name LIKE ?
                             AND parent_id = ?""",
                        (f"%{county_name}%", state_id)
                    ).fetchone()
                    if county_row:
                        region_id = county_row["id"]

            if not region_id:
                region_id = region_by_code.get(state_code)

            if not region_id:
                skipped += len(rows)
                continue

            # --- Resolve location (optional) ---
            location_id = location_map.get(
                first.get("Location ID", "").strip()
            )

            # --- Parse effort ---
            def _int(val, default=None):
                try:
                    return int(float(val)) if val else default
                except (ValueError, TypeError):
                    return default

            def _float(val, default=None):
                try:
                    return float(val) if val else default
                except (ValueError, TypeError):
                    return default

            duration   = _int(first.get("Duration (Min)"))
            distance   = _float(first.get("Distance Traveled (km)"))
            observers  = _int(first.get("Number of Observers"), 1)
            complete   = 1 if first.get("All Obs Reported", "1") == "1" else 0

            # --- Upsert checklist ---
            conn.execute(
                """INSERT INTO checklist
                       (source, source_id, location_id, region_id, obs_date,
                        start_time, duration_minutes, distance_km,
                        observer_count, complete)
                   VALUES ('ebird', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET
                       duration_minutes = excluded.duration_minutes,
                       distance_km      = excluded.distance_km,
                       complete         = excluded.complete""",
                (sub_id, location_id, region_id,
                 first.get("Date", "").strip(),
                 first.get("Time", "").strip() or None,
                 duration, distance, observers, complete)
            )
            cl_id = conn.execute(
                "SELECT id FROM checklist WHERE source_id = ?", (sub_id,)
            ).fetchone()["id"]
            cl_count += 1

            # --- Import observations ---
            for row in rows:
                taxon_id = taxon_map.get(row.get("Common Name", "").strip())
                if not taxon_id:
                    skipped += 1
                    continue
                try:
                    conn.execute(
                        """INSERT INTO observation
                               (checklist_id, taxon_id, region_id, location_id,
                                obs_date, count, source, source_id, media)
                           VALUES (?, ?, ?, ?, ?, ?, 'ebird', ?, 0)
                           ON CONFLICT(source, source_id, taxon_id) DO NOTHING""",
                        (cl_id, taxon_id, region_id, location_id,
                         row.get("Date", "").strip(),
                         row.get("Count", "").strip(),
                         sub_id)
                    )
                    obs_count += 1
                except Exception:
                    skipped += 1

        conn.commit()

    print(
        f"Imported {cl_count} checklists, {obs_count} observations "
        f"from {csv_path.name} ({skipped} skipped)"
    )
    return cl_count, obs_count
