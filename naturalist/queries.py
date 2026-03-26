"""
Core queries: life list, targets, frequency rankings, rollup.
All location queries support rollup — parent location includes all children.
"""

from pathlib import Path
from naturalist.db import get_connection, DEFAULT_DB


def _child_location_ids(conn, location_id: int) -> list[int]:
    rows = conn.execute(
        """WITH RECURSIVE children(id) AS (
               SELECT id FROM location WHERE id = ?
               UNION ALL
               SELECT l.id FROM location l
               JOIN children c ON l.parent_id = c.id
           )
           SELECT id FROM children""",
        (location_id,)
    ).fetchall()
    return [r["id"] for r in rows]


def _resolve_location(conn, location_name: str):
    row = conn.execute(
        "SELECT * FROM location WHERE name LIKE ?", (f"%{location_name}%",)
    ).fetchone()
    if not row:
        raise ValueError(f"Location not found: '{location_name}'")
    return row


def life_list(location_name: str, taxa_group: str = "bird",
              db_path: Path = DEFAULT_DB) -> list[dict]:
    with get_connection(db_path) as conn:
        loc = _resolve_location(conn, location_name)
        child_ids = _child_location_ids(conn, loc["id"])
        placeholders = ",".join("?" * len(child_ids))
        rows = conn.execute(
            f"""SELECT DISTINCT t.common_name, t.scientific_name,
                       t.family, t.order_name, t.taxonomic_order,
                       MIN(o.obs_date) AS first_seen
                FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE o.location_id IN ({placeholders}) AND t.taxa_group = ?
                GROUP BY t.id
                ORDER BY t.taxonomic_order""",
            (*child_ids, taxa_group)
        ).fetchall()
    return [dict(r) for r in rows]


def target_list(location_name: str, taxa_group: str = "bird",
                min_peak_frequency: float = 0.0,
                limit: int = 50,
                db_path: Path = DEFAULT_DB) -> list[dict]:
    with get_connection(db_path) as conn:
        loc = _resolve_location(conn, location_name)
        child_ids = _child_location_ids(conn, loc["id"])
        placeholders = ",".join("?" * len(child_ids))
        rows = conn.execute(
            f"""SELECT t.common_name, t.scientific_name, t.family, t.order_name,
                       pf.peak_frequency, pf.weeks_present
                FROM v_peak_frequency pf
                JOIN taxon t ON pf.taxon_id = t.id
                WHERE pf.location_id = ? AND t.taxa_group = ?
                  AND pf.peak_frequency >= ?
                  AND t.id NOT IN (
                      SELECT DISTINCT taxon_id FROM observation
                      WHERE location_id IN ({placeholders})
                  )
                ORDER BY pf.peak_frequency DESC
                LIMIT ?""",
            (loc["id"], taxa_group, min_peak_frequency, *child_ids, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def species_status(common_name: str, location_name: str,
                   db_path: Path = DEFAULT_DB) -> dict:
    with get_connection(db_path) as conn:
        taxon = conn.execute(
            "SELECT * FROM taxon WHERE common_name LIKE ?", (f"%{common_name}%",)
        ).fetchone()
        if not taxon:
            return {"error": f"Species not found: {common_name}"}
        loc = _resolve_location(conn, location_name)
        child_ids = _child_location_ids(conn, loc["id"])
        placeholders = ",".join("?" * len(child_ids))
        seen = conn.execute(
            f"""SELECT MIN(obs_date) AS first_seen, MAX(obs_date) AS last_seen,
                       COUNT(*) AS n_observations
                FROM observation
                WHERE taxon_id = ? AND location_id IN ({placeholders})""",
            (taxon["id"], *child_ids)
        ).fetchone()
        photographed = conn.execute(
            f"""SELECT COUNT(*) AS n_photos FROM observation
                WHERE taxon_id = ? AND source = 'inat'
                  AND location_id IN ({placeholders})""",
            (taxon["id"], *child_ids)
        ).fetchone()
        knowledge = conn.execute(
            """SELECT researched, field_guide, deep FROM knowledge
               WHERE taxon_id = ? AND (location_id = ? OR location_id IS NULL)
               ORDER BY location_id DESC LIMIT 1""",
            (taxon["id"], loc["id"])
        ).fetchone()
        freq = conn.execute(
            """SELECT peak_frequency, weeks_present FROM v_peak_frequency
               WHERE taxon_id = ? AND location_id = ?""",
            (taxon["id"], loc["id"])
        ).fetchone()
    return {
        "species": taxon["common_name"],
        "scientific_name": taxon["scientific_name"],
        "location": location_name,
        "seen": bool(seen and seen["n_observations"]),
        "first_seen": seen["first_seen"] if seen else None,
        "last_seen": seen["last_seen"] if seen else None,
        "n_observations": seen["n_observations"] if seen else 0,
        "photographed": bool(photographed and photographed["n_photos"]),
        "researched": bool(knowledge and knowledge["researched"]),
        "field_guide_entry": bool(knowledge and knowledge["field_guide"]),
        "deep_knowledge": bool(knowledge and knowledge["deep"]),
        "peak_frequency": freq["peak_frequency"] if freq else None,
        "weeks_present": freq["weeks_present"] if freq else None,
    }


def location_summary(location_name: str, taxa_group: str = "bird",
                     db_path: Path = DEFAULT_DB) -> dict:
    with get_connection(db_path) as conn:
        loc = _resolve_location(conn, location_name)
        child_ids = _child_location_ids(conn, loc["id"])
        placeholders = ",".join("?" * len(child_ids))
        total_recorded = conn.execute(
            """SELECT COUNT(*) AS n FROM taxon WHERE taxa_group = ?
               AND id IN (SELECT DISTINCT taxon_id FROM ebird_frequency
                          WHERE location_id = ?)""",
            (taxa_group, loc["id"])
        ).fetchone()["n"]
        total_seen = conn.execute(
            f"""SELECT COUNT(DISTINCT taxon_id) AS n FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE o.location_id IN ({placeholders}) AND t.taxa_group = ?""",
            (*child_ids, taxa_group)
        ).fetchone()["n"]
        total_photo = conn.execute(
            f"""SELECT COUNT(DISTINCT taxon_id) AS n FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE o.location_id IN ({placeholders})
                  AND o.source = 'inat' AND t.taxa_group = ?""",
            (*child_ids, taxa_group)
        ).fetchone()["n"]
    return {
        "location": location_name,
        "taxa_group": taxa_group,
        "total_recorded_in_region": total_recorded,
        "personal_life_list": total_seen,
        "photographed": total_photo,
        "pct_seen": round(100 * total_seen / total_recorded, 1) if total_recorded else 0,
    }
