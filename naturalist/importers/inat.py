"""
iNaturalist importer. Uses the public API — no key required.
API docs: https://api.inaturalist.org/v1/docs/
"""

import time
from pathlib import Path
import requests
from naturalist.db import get_connection, DEFAULT_DB

INAT_API_BASE = "https://api.inaturalist.org/v1"
TYPE_RANK = {"site": 0, "county": 1, "state": 2, "country": 3}


def import_observations(inat_username: str, place_id: int = None,
                        taxon_group: str = None, db_path: Path = DEFAULT_DB,
                        max_pages: int = 50) -> int:
    """
    Fetch personal iNaturalist observations and import into observation table.
    iNat observations count as 'photographed' (source='inat').
    place_id examples: Okanogan County=1259, Washington=62, USA=1
    """
    with get_connection(db_path) as conn:
        taxon_map = {r["scientific_name"]: r["id"]
                     for r in conn.execute("SELECT id, scientific_name FROM taxon")}
        inat_id_map = {r["inat_taxon_id"]: r["id"]
                       for r in conn.execute(
                           "SELECT id, inat_taxon_id FROM taxon "
                           "WHERE inat_taxon_id IS NOT NULL")}
        location_map = {r["inat_place_id"]: r["id"]
                        for r in conn.execute(
                            "SELECT id, inat_place_id FROM location "
                            "WHERE inat_place_id IS NOT NULL")}
        count = 0
        for page in range(1, max_pages + 1):
            params = {"user_login": inat_username, "per_page": 200, "page": page,
                      "order": "desc", "order_by": "created_at",
                      "quality_grade": "research,needs_id"}
            if place_id:
                params["place_id"] = place_id
            if taxon_group:
                params["iconic_taxa"] = taxon_group
            results = requests.get(f"{INAT_API_BASE}/observations",
                                   params=params, timeout=30).json().get("results", [])
            if not results:
                break
            for obs in results:
                inat_taxon = obs.get("taxon", {})
                taxon_id = (inat_id_map.get(inat_taxon.get("id")) or
                            taxon_map.get(inat_taxon.get("name", "")))
                if not taxon_id:
                    continue
                # Prefer most specific matching location
                location_id = None
                for pid in [p.get("id") for p in obs.get("place_ids", [])]:
                    if pid not in location_map:
                        continue
                    candidate = conn.execute(
                        "SELECT id, type FROM location WHERE id = ?",
                        (location_map[pid],)
                    ).fetchone()
                    if not candidate:
                        continue
                    if location_id is None:
                        location_id = candidate["id"]
                    else:
                        existing_type = conn.execute(
                            "SELECT type FROM location WHERE id = ?",
                            (location_id,)
                        ).fetchone()["type"]
                        if TYPE_RANK.get(candidate["type"], 9) < TYPE_RANK.get(existing_type, 9):
                            location_id = candidate["id"]
                if not location_id:
                    continue
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO observation
                           (location_id, taxon_id, obs_date, count, source, source_id)
                           VALUES (?, ?, ?, '1', 'inat', ?)""",
                        (location_id, taxon_id,
                         obs.get("observed_on") or obs.get("created_at", "")[:10],
                         str(obs.get("id", "")))
                    )
                    count += 1
                except Exception:
                    pass
            conn.commit()
            print(f"  Page {page}: {len(results)} results")
            if len(results) < 200:
                break
            time.sleep(1)
    print(f"Imported {count} iNaturalist observations for {inat_username}")
    return count
