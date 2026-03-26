"""
Core queries: life list, regional lists, year lists, targets, P(1hr).

All regional queries use recursive CTE rollup — querying Washington
automatically includes all counties beneath it.
"""

import math
from pathlib import Path

from naturalist.db import get_connection, DEFAULT_DB


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _child_region_ids(conn, region_id: int) -> list[int]:
    rows = conn.execute(
        """WITH RECURSIVE children(id) AS (
               SELECT id FROM region WHERE id = ?
               UNION ALL
               SELECT r.id FROM region r
               JOIN children c ON r.parent_id = c.id
           )
           SELECT id FROM children""",
        (region_id,)
    ).fetchall()
    return [r["id"] for r in rows]


def _resolve_region(conn, region_name: str):
    row = conn.execute(
        "SELECT * FROM region WHERE name LIKE ?", (f"%{region_name}%",)
    ).fetchone()
    if not row:
        raise ValueError(f"Region not found: '{region_name}'")
    return row


def taxa_filter(taxa_group: str) -> tuple[str, list]:
    """
    Return (sql_fragment, params) for filtering taxon rows by group.

    taxa_group can be any of: bird, mammal, reptile, amphibian, plant,
    insect, fungi, all — or a raw class/order/family value prefixed with
    'class:', 'order:', or 'family:' for fine-grained filtering.

    Examples:
        taxa_filter('bird')          → "t.taxa_group = ?", ['bird']
        taxa_filter('all')           → "1=1", []
        taxa_filter('order:Odonata') → "t.order_name = ?", ['Odonata']
        taxa_filter('family:Apidae') → "t.family = ?", ['Apidae']
    """
    if taxa_group == "all":
        return "1=1", []
    if ":" in taxa_group:
        field, value = taxa_group.split(":", 1)
        col_map = {"class": "t.class", "order": "t.order_name",
                   "family": "t.family", "genus": "t.genus"}
        col = col_map.get(field)
        if col:
            return f"{col} = ?", [value]
    return "t.taxa_group = ?", [taxa_group]


# ---------------------------------------------------------------------------
# Life list
# ---------------------------------------------------------------------------

def life_list(taxa_group: str = "bird", year: str = None,
              db_path: Path = DEFAULT_DB) -> list[dict]:
    """
    Global life list — all species observed regardless of location.
    Pass year='2025' to get a year list instead.
    """
    taxa_sql, taxa_params = taxa_filter(taxa_group)
    year_clause = "AND strftime('%Y', o.obs_date) = ?" if year else ""
    year_params = [year] if year else []

    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""SELECT t.common_name, t.scientific_name, t.family,
                       t.order_name, t.class, t.taxonomic_order,
                       MIN(o.obs_date) AS first_seen,
                       MAX(o.obs_date) AS last_seen,
                       MAX(o.media)    AS photographed
                FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE {taxa_sql} {year_clause}
                GROUP BY t.id
                ORDER BY t.taxonomic_order, t.common_name""",
            (*taxa_params, *year_params)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Regional list
# ---------------------------------------------------------------------------

def regional_list(region_name: str, taxa_group: str = "bird",
                  year: str = None,
                  db_path: Path = DEFAULT_DB) -> list[dict]:
    """
    Species observed in a region, with rollup from all child regions.
    Pass year='2025' for a year list.
    """
    taxa_sql, taxa_params = taxa_filter(taxa_group)
    year_clause = "AND strftime('%Y', o.obs_date) = ?" if year else ""
    year_params = [year] if year else []

    with get_connection(db_path) as conn:
        reg = _resolve_region(conn, region_name)
        child_ids = _child_region_ids(conn, reg["id"])
        ph = ",".join("?" * len(child_ids))
        rows = conn.execute(
            f"""SELECT t.common_name, t.scientific_name, t.family,
                       t.order_name, t.class, t.taxonomic_order,
                       MIN(o.obs_date) AS first_seen,
                       MAX(o.obs_date) AS last_seen,
                       MAX(o.media)    AS photographed
                FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE o.region_id IN ({ph}) AND {taxa_sql} {year_clause}
                GROUP BY t.id
                ORDER BY t.taxonomic_order, t.common_name""",
            (*child_ids, *taxa_params, *year_params)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Target list
# ---------------------------------------------------------------------------

def target_list(region_name: str, taxa_group: str = "bird",
                life_targets_only: bool = False,
                min_peak_frequency: float = 0.01,
                limit: int = 50,
                db_path: Path = DEFAULT_DB) -> list[dict]:
    """
    Species with frequency data in a region that have not yet been seen.

    life_targets_only=True  → unseen globally (true lifers)
    life_targets_only=False → unseen in this region (regional targets,
                               may already be on life list elsewhere)
    """
    taxa_sql, taxa_params = taxa_filter(taxa_group)

    with get_connection(db_path) as conn:
        reg = _resolve_region(conn, region_name)
        child_ids = _child_region_ids(conn, reg["id"])
        ph = ",".join("?" * len(child_ids))

        if life_targets_only:
            seen_clause = "t.id NOT IN (SELECT DISTINCT taxon_id FROM observation)"
            seen_params: list = []
        else:
            seen_clause = (
                f"t.id NOT IN ("
                f"  SELECT DISTINCT taxon_id FROM observation"
                f"  WHERE region_id IN ({ph})"
                f")"
            )
            seen_params = list(child_ids)

        rows = conn.execute(
            f"""SELECT t.common_name, t.scientific_name, t.family,
                       t.order_name, t.class,
                       rf.peak_frequency, rf.weeks_present
                FROM v_region_peak_frequency rf
                JOIN taxon t ON rf.taxon_id = t.id
                WHERE rf.region_id = ? AND {taxa_sql}
                  AND rf.peak_frequency >= ?
                  AND {seen_clause}
                ORDER BY rf.peak_frequency DESC
                LIMIT ?""",
            (reg["id"], *taxa_params, min_peak_frequency,
             *seen_params, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# P(1hr) lookup
# ---------------------------------------------------------------------------

def p_1hr(taxon_id: int, week: int,
          location_id: int = None, region_id: int = None,
          db_path: Path = DEFAULT_DB) -> float | None:
    """
    P(species seen | 1 hour of active observing) for a given week.

    Prefers location-level frequency; falls back to region-level.
    Formula: 1 - (1 - f)^(60 / mean_effort_minutes)
    Falls back to raw f when mean_effort_minutes is not yet populated.
    Returns None if no frequency data exists.
    """
    with get_connection(db_path) as conn:
        row = None
        if location_id:
            row = conn.execute(
                """SELECT frequency, mean_effort_minutes
                   FROM location_frequency
                   WHERE location_id = ? AND taxon_id = ? AND week = ?""",
                (location_id, taxon_id, week)
            ).fetchone()
        if row is None and region_id:
            row = conn.execute(
                """SELECT frequency, mean_effort_minutes
                   FROM region_frequency
                   WHERE region_id = ? AND taxon_id = ? AND week = ?""",
                (region_id, taxon_id, week)
            ).fetchone()
        if row is None:
            return None
        return _compute_p1hr(row["frequency"], row["mean_effort_minutes"])


def _compute_p1hr(frequency: float, mean_effort_minutes: float | None) -> float:
    if frequency <= 0:
        return 0.0
    if mean_effort_minutes and mean_effort_minutes > 0:
        return 1.0 - math.pow(1.0 - frequency, 60.0 / mean_effort_minutes)
    return frequency  # raw frequency as proxy


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def region_summary(region_name: str, taxa_group: str = "bird",
                   db_path: Path = DEFAULT_DB) -> dict:
    """Counts: species recorded in region / seen / photographed."""
    taxa_sql, taxa_params = taxa_filter(taxa_group)

    with get_connection(db_path) as conn:
        reg = _resolve_region(conn, region_name)
        child_ids = _child_region_ids(conn, reg["id"])
        ph = ",".join("?" * len(child_ids))

        total_recorded = conn.execute(
            f"""SELECT COUNT(DISTINCT rf.taxon_id) AS n
                FROM region_frequency rf
                JOIN taxon t ON rf.taxon_id = t.id
                WHERE rf.region_id = ? AND {taxa_sql}""",
            (reg["id"], *taxa_params)
        ).fetchone()["n"]

        total_seen = conn.execute(
            f"""SELECT COUNT(DISTINCT o.taxon_id) AS n
                FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE o.region_id IN ({ph}) AND {taxa_sql}""",
            (*child_ids, *taxa_params)
        ).fetchone()["n"]

        total_photo = conn.execute(
            f"""SELECT COUNT(DISTINCT o.taxon_id) AS n
                FROM observation o
                JOIN taxon t ON o.taxon_id = t.id
                WHERE o.region_id IN ({ph}) AND {taxa_sql}
                  AND o.media = 1""",
            (*child_ids, *taxa_params)
        ).fetchone()["n"]

    return {
        "region": region_name,
        "taxa_group": taxa_group,
        "total_recorded_in_region": total_recorded,
        "personal_list": total_seen,
        "photographed": total_photo,
        "pct_seen": round(100 * total_seen / total_recorded, 1) if total_recorded else 0,
    }
