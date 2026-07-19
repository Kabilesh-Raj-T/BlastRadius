"""Click command-line interface for ChokePoint."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NoReturn

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from chokepoint.graph import GraphAnalyzer, GraphBuilder, TopologyDiff, diff_topologies
from chokepoint.graph.engine import AnalysisReport
from chokepoint.models import Topology
from chokepoint.parser import TopologyParseError, parse_topology_yaml_file
from chokepoint.report import (
    GeneratedReport,
    export_csv,
    export_mermaid,
    export_openapi,
    export_sarif,
    generate_security_report,
)
from chokepoint.visualization import (
    GraphvizRenderError,
    GraphvizVisualizer,
    render_interactive_html,
)

LOGGER = logging.getLogger("chokepoint")
console = Console()
error_console = Console(stderr=True)


class CliContext:
    """Runtime context shared by CLI commands."""

    def __init__(self, *, verbose: bool) -> None:
        """Create CLI context.

        Args:
            verbose: Whether verbose logging and exception details are enabled.
        """
        self.verbose = verbose


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--verbose", is_flag=True, help="Enable verbose colored logs.")
@click.pass_context
def cli(ctx: click.Context, *, verbose: bool) -> None:
    """Analyze infrastructure dependency choke points."""
    _configure_logging(verbose)
    ctx.obj = CliContext(verbose=verbose)
    if verbose:
        LOGGER.debug("Verbose logging enabled")


@cli.command()
@click.argument(
    "topology_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit structured JSON.")
@click.option("--markdown", is_flag=True, help="Emit Markdown.")
@click.option("--html", is_flag=True, help="Emit standalone HTML.")
@click.pass_obj
def analyze(
    ctx: CliContext,
    topology_path: Path,
    *,
    as_json: bool,
    markdown: bool,
    html: bool,
) -> None:
    """Analyze topology.yaml and print a risk summary."""
    try:
        quiet = as_json or html
        topology = _load_topology(topology_path, quiet=quiet)
        generated_report = _security_report(topology, quiet=quiet)
    except Exception as error:
        _fail(error, verbose=ctx.verbose)

    _emit_security_report(
        generated_report,
        as_json=as_json,
        markdown=markdown,
        html=html,
    )


@cli.command()
@click.argument(
    "topology_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit graph metrics as JSON.")
@click.option("--svg", is_flag=True, help="Render SVG with Graphviz.")
@click.option("--markdown", is_flag=True, help="Emit Markdown graph summary.")
@click.pass_obj
def graph(
    ctx: CliContext,
    topology_path: Path,
    *,
    as_json: bool,
    svg: bool,
    markdown: bool,
) -> None:
    """Inspect or render the topology graph."""
    try:
        topology = _load_topology(topology_path, quiet=as_json or svg)
        if svg:
            artifact = GraphvizVisualizer().render_svg(topology)
            click.echo(artifact.text, nl=False)
            return

        graph_model = GraphBuilder().build(topology)
        analysis = GraphAnalyzer().analyze(graph_model)
    except Exception as error:
        _fail(error, verbose=ctx.verbose)

    if as_json:
        click.echo(analysis.model_dump_json())
    elif markdown:
        console.print(Markdown(_graph_markdown(analysis)))
    else:
        table = Table(title="Graph Summary")
        table.add_column("Metric", style="bold cyan")
        table.add_column("Value", style="green")
        table.add_row("Nodes", str(analysis.node_count))
        table.add_row("Edges", str(analysis.edge_count))
        table.add_row("Connected", str(analysis.is_connected))
        table.add_row("Articulation points", str(len(analysis.articulation_points)))
        table.add_row("Bridges", str(len(analysis.bridges)))
        table.add_row("Cycles", str(len(analysis.cycles)))
        console.print(table)


@cli.command()
@click.argument(
    "topology_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit structured JSON.")
@click.option("--markdown", is_flag=True, help="Emit Markdown.")
@click.option("--html", is_flag=True, help="Emit standalone HTML.")
@click.pass_obj
def report(
    ctx: CliContext,
    topology_path: Path,
    *,
    as_json: bool,
    markdown: bool,
    html: bool,
) -> None:
    """Generate a risk report for topology.yaml."""
    try:
        quiet = as_json or html
        topology = _load_topology(topology_path, quiet=quiet)
        generated_report = _security_report(topology, quiet=quiet)
    except Exception as error:
        _fail(error, verbose=ctx.verbose)

    _emit_security_report(
        generated_report,
        as_json=as_json,
        markdown=markdown,
        html=html,
    )


@cli.command()
@click.argument(
    "topology_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "export_format",
    type=click.Choice(["sarif", "openapi", "csv", "mermaid", "html"]),
    required=True,
    help="Export format.",
)
@click.pass_obj
def export(ctx: CliContext, topology_path: Path, *, export_format: str) -> None:
    """Export topology or report artifacts."""
    try:
        topology = _load_topology(topology_path, quiet=True)
        if export_format == "sarif":
            click.echo(export_sarif(generate_security_report(topology)))
        elif export_format == "openapi":
            click.echo(export_openapi())
        elif export_format == "csv":
            click.echo(export_csv(topology), nl=False)
        elif export_format == "mermaid":
            click.echo(export_mermaid(topology), nl=False)
        else:
            click.echo(render_interactive_html(topology), nl=False)
    except Exception as error:
        _fail(error, verbose=ctx.verbose)


@cli.command()
@click.argument(
    "before_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "after_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit structured JSON.")
@click.pass_obj
def diff(
    ctx: CliContext,
    before_path: Path,
    after_path: Path,
    *,
    as_json: bool,
) -> None:
    """Diff two topology.yaml files."""
    try:
        before = _load_topology(before_path, quiet=True)
        after = _load_topology(after_path, quiet=True)
        topology_diff = diff_topologies(before, after)
    except Exception as error:
        _fail(error, verbose=ctx.verbose)

    if as_json:
        click.echo(topology_diff.model_dump_json(indent=2))
    else:
        click.echo(_diff_markdown(topology_diff))


@cli.command()
@click.argument(
    "topology_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True, help="Emit validation JSON.")
@click.pass_obj
def validate(ctx: CliContext, topology_path: Path, *, as_json: bool) -> None:
    """Validate topology.yaml."""
    try:
        topology = _load_topology(topology_path, quiet=as_json)
    except Exception as error:
        if as_json:
            console.print_json(json.dumps({"valid": False, "error": str(error)}))
            raise click.exceptions.Exit(1) from error
        _fail(error, verbose=ctx.verbose)

    payload = {
        "valid": True,
        "nodes": len(topology.nodes),
        "edges": len(topology.edges),
    }
    if as_json:
        click.echo(json.dumps(payload))
    else:
        console.print(
            f"[bold green]Valid topology[/]: "
            f"{payload['nodes']} node(s), {payload['edges']} edge(s)"
        )


def main() -> None:
    """Run the ChokePoint CLI."""
    cli()


def _load_topology(path: Path, *, quiet: bool) -> Topology:
    """Load a topology with progress output."""
    if quiet:
        return parse_topology_yaml_file(path)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"Parsing {path.name}", total=None)
        topology = parse_topology_yaml_file(path)
    LOGGER.info(
        "Loaded topology with %s nodes and %s edges",
        len(topology.nodes),
        len(topology.edges),
    )
    return topology


def _security_report(topology: Topology, *, quiet: bool) -> GeneratedReport:
    """Generate a security report with progress output."""
    if quiet:
        return generate_security_report(topology)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task("Generating security report", total=None)
        return generate_security_report(topology)


def _emit_security_report(
    report: GeneratedReport,
    *,
    as_json: bool,
    markdown: bool,
    html: bool,
) -> None:
    """Emit a security report in the requested format."""
    if as_json:
        click.echo(report.to_json())
    elif html:
        click.echo(report.to_html())
    elif markdown:
        click.echo(report.to_markdown())
    else:
        console.print(report.to_terminal())


def _graph_markdown(analysis: AnalysisReport) -> str:
    """Return a Markdown graph summary."""
    return "\n".join(
        [
            "# ChokePoint Graph Summary",
            "",
            f"- Nodes: `{analysis.node_count}`",
            f"- Edges: `{analysis.edge_count}`",
            f"- Connected: `{analysis.is_connected}`",
            f"- Articulation points: `{', '.join(analysis.articulation_points)}`",
            f"- Bridges: `{len(analysis.bridges)}`",
            f"- Cycles: `{len(analysis.cycles)}`",
        ]
    )


def _diff_markdown(diff: TopologyDiff) -> str:
    """Return a Markdown topology diff summary."""
    return "\n".join(
        [
            "# ChokePoint Topology Diff",
            "",
            f"- Added nodes: `{len(diff.added_nodes)}`",
            f"- Removed nodes: `{len(diff.removed_nodes)}`",
            f"- Changed nodes: `{len(diff.changed_nodes)}`",
            f"- Added edges: `{len(diff.added_edges)}`",
            f"- Removed edges: `{len(diff.removed_edges)}`",
        ]
    )


def _configure_logging(verbose: bool) -> None:
    """Configure colored CLI logging."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=error_console, rich_tracebacks=verbose)],
        force=True,
    )


def _fail(error: Exception, *, verbose: bool) -> NoReturn:
    """Render a helpful CLI error and exit."""
    if verbose:
        LOGGER.exception("Command failed")
    if isinstance(error, TopologyParseError | GraphvizRenderError | ValueError):
        raise click.ClickException(str(error)) from error
    raise click.ClickException(f"unexpected error: {error}") from error
