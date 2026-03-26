#!/usr/bin/env python3
import click
from pathlib import Path
from naturalist.db import init_db, seed_locations, DEFAULT_DB
from naturalist.importers.ebird import import_species_list, import_barchart, import_personal_csv
from naturalist.importers.inat import import_observations
from naturalist import queries


@click.group()
@click.option("--db", default=str(DEFAULT_DB), help="Path to SQLite database")
@click.pass_context
def cli(ctx, db):
    ctx.ensure_object(dict)
    ctx.obj["db"] = Path(db)


@cli.command()
@click.pass_context
def init(ctx):
    """Initialise database schema and seed core locations."""
    init_db(ctx.obj["db"])
    seed_locations(ctx.obj["db"])


@cli.command("add-location")
@click.argument("name")
@click.argument("type", type=click.Choice(["country", "state", "county", "site"]))
@click.argument("parent")
@click.option("--ebird-region", default=None)
@click.option("--inat-place-id", default=None, type=int)
@click.pass_context
def add_location(ctx, name, type, parent, ebird_region, inat_place_id):
    """Add a location to the hierarchy."""
    from naturalist.db import get_connection
    with get_connection(ctx.obj["db"]) as conn:
        parent_row = conn.execute(
            "SELECT id FROM location WHERE name LIKE ?", (f"%{parent}%",)
        ).fetchone()
        if not parent_row:
            raise click.ClickException(f"Parent location not found: {parent}")
        conn.execute(
            """INSERT INTO location (name, type, parent_id, ebird_region, inat_place_id)
               VALUES (?, ?, ?, ?, ?)""",
            (name, type, parent_row["id"], ebird_region, inat_place_id)
        )
        conn.commit()
    click.echo(f"Added: {name} ({type}) under {parent}")


@cli.command("import-species")
@click.argument("region")
@click.option("--group", default="bird")
@click.pass_context
def cmd_import_species(ctx, region, group):
    """Import eBird species list for a region."""
    import_species_list(region, group, ctx.obj["db"])


@cli.command("import-barchart")
@click.argument("region")
@click.pass_context
def cmd_import_barchart(ctx, region):
    """Import eBird weekly frequency data for a region."""
    import_barchart(region, ctx.obj["db"])


@cli.command("import-ebird")
@click.argument("csv_path", type=click.Path(exists=True))
@click.pass_context
def cmd_import_ebird(ctx, csv_path):
    """Import personal eBird observations from MyData CSV export."""
    import_personal_csv(Path(csv_path), ctx.obj["db"])


@cli.command("import-inat")
@click.argument("username")
@click.option("--place-id", default=None, type=int)
@click.option("--taxon", default=None)
@click.pass_context
def cmd_import_inat(ctx, username, place_id, taxon):
    """Import personal iNaturalist observations."""
    import_observations(username, place_id, taxon, ctx.obj["db"])


@cli.command("life-list")
@click.argument("location")
@click.option("--group", default="bird")
@click.pass_context
def cmd_life_list(ctx, location, group):
    """Personal life list for a location (with rollup from child locations)."""
    results = queries.life_list(location, group, ctx.obj["db"])
    if not results:
        click.echo(f"No {group} observations found for '{location}'")
        return
    click.echo(f"\n{group.capitalize()} life list — {location} ({len(results)} species)\n")
    click.echo(f"{'#':<5} {'Common Name':<35} {'First Seen':<12} {'Family'}")
    click.echo("-" * 75)
    for i, sp in enumerate(results, 1):
        click.echo(f"{i:<5} {sp['common_name']:<35} {(sp['first_seen'] or ''):<12} {sp['family'] or ''}")


@cli.command("targets")
@click.argument("location")
@click.option("--group", default="bird")
@click.option("--limit", default=50)
@click.option("--min-freq", default=0.01, type=float)
@click.pass_context
def cmd_targets(ctx, location, group, limit, min_freq):
    """Species not yet seen at a location, sorted by peak frequency."""
    results = queries.target_list(location, group, min_freq, limit, ctx.obj["db"])
    if not results:
        click.echo("No targets found")
        return
    click.echo(f"\nTop targets — {location} — {group}\n")
    click.echo(f"{'#':<5} {'Common Name':<35} {'Peak Freq':>10}  {'Wks Present':>12}  {'Family'}")
    click.echo("-" * 80)
    for i, sp in enumerate(results, 1):
        freq = f"{sp['peak_frequency']*100:.1f}%" if sp['peak_frequency'] else "—"
        click.echo(f"{i:<5} {sp['common_name']:<35} {freq:>10}  {str(sp['weeks_present'] or '—'):>12}  {sp['family'] or ''}")


@cli.command("status")
@click.argument("species")
@click.argument("location")
@click.pass_context
def cmd_status(ctx, species, location):
    """Full status for a species at a location."""
    result = queries.species_status(species, location, ctx.obj["db"])
    if "error" in result:
        raise click.ClickException(result["error"])
    click.echo(f"\n{result['species']} ({result['scientific_name']})")
    click.echo(f"Location: {result['location']}\n")
    click.echo(f"  Seen:            {'Yes — ' + result['first_seen'] if result['seen'] else 'No'}")
    click.echo(f"  Photographed:    {'Yes' if result['photographed'] else 'No'}")
    click.echo(f"  Researched:      {'Yes' if result['researched'] else 'No'}")
    click.echo(f"  Field guide:     {'Yes' if result['field_guide_entry'] else 'No'}")
    click.echo(f"  Deep knowledge:  {'Yes' if result['deep_knowledge'] else 'No'}")
    if result["peak_frequency"] is not None:
        click.echo(f"\n  Peak frequency:  {result['peak_frequency']*100:.1f}% of checklists")
        click.echo(f"  Weeks present:   {result['weeks_present']}/52")


@cli.command("summary")
@click.argument("location")
@click.option("--group", default="bird")
@click.pass_context
def cmd_summary(ctx, location, group):
    """Summary statistics for a location (with rollup)."""
    result = queries.location_summary(location, group, ctx.obj["db"])
    click.echo(f"\n{result['location']} — {result['taxa_group']} summary")
    click.echo(f"  Recorded in region:  {result['total_recorded_in_region']}")
    click.echo(f"  Personal life list:  {result['personal_life_list']} ({result['pct_seen']}%)")
    click.echo(f"  Photographed:        {result['photographed']}")


if __name__ == "__main__":
    cli()
