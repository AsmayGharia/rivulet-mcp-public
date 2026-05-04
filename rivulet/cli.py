"""
Rivulet CLI — `rivulet design`, `rivulet iterate`, `rivulet presets`.

Help text matches the spec in the plan exactly.
All output to stdout; all errors to stderr. --json flag outputs single-line JSON.
Loading spinner uses rich with branded DEP droplet frames (stderr only).
CI/non-TTY: spinner and color are automatically disabled.
"""
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv

# Load .env from current directory if present
load_dotenv()

__version__ = "0.1.0"

# ── Branded spinner ───────────────────────────────────────────────────────────
# Frames evoke a DEP droplet activating.
# Post-ship: replace with extracted logo GIF frames (see TODOS.md).
RIVULET_FRAMES = ["○", "◌", "◐", "◉", "●", "◎", "◌"]

app = typer.Typer(
    name="rivulet",
    help=(
        "Rivulet MCP — DEP experiment protocol designer\n\n"
        "Design and iterate on microfluidics experiment protocols using\n"
        "natural language. Connects to Claude Desktop via MCP."
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "Examples:\n"
        "  rivulet design \"screen 5 kinase inhibitors against T-cells\"\n"
        "  rivulet presets\n"
        "  rivulet iterate plan.json \"add 3 more drug concentrations\""
    ),
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"rivulet-mcp {__version__}")
        typer.echo("Report issues: https://github.com/AsmayGharia/rivulet-mcp/issues")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit"),
    ] = None,
) -> None:
    pass


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        typer.echo(
            "Error: ANTHROPIC_API_KEY not set.\nRun: export ANTHROPIC_API_KEY=sk-ant-...",
            err=True,
        )
        raise typer.Exit(1)
    return key


def _is_tty() -> bool:
    return sys.stderr.isatty() and not os.environ.get("NO_COLOR") and not os.environ.get("CI")


def _print_result(data: dict | list, as_json: bool) -> None:
    """Print result to stdout. --json = compact single-line; default = pretty-printed."""
    if as_json:
        typer.echo(json.dumps(data, separators=(",", ":")))
    else:
        typer.echo(json.dumps(data, indent=2))


def _run_with_spinner(message: str, fn):
    """Run fn(on_progress) while showing a branded spinner + thinking lines to stderr.

    fn must accept a single on_progress callable (or None in non-TTY mode).
    """
    if _is_tty():
        from rich.console import Console, Group
        from rich.spinner import Spinner
        from rich.live import Live
        from rich.text import Text

        console = Console(stderr=True)
        lines: list[str] = []

        def _render():
            spinner = Spinner("dots", text=message, style="cyan")
            if not lines:
                return spinner
            return Group(spinner, *[Text(l, style="dim") for l in lines])

        with Live(_render(), console=console, refresh_per_second=8) as live:
            def _on_progress(line: str):
                lines.append(line)
                live.update(_render())

            return fn(_on_progress)
    else:
        typer.echo(message, err=True)
        return fn(None)


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command(
    help="Design an experiment from natural language.",
    epilog=(
        "Example:\n"
        "  rivulet design \"screen 5 kinase inhibitors against T-cells\""
    ),
)
def design(
    prompt: Annotated[str, typer.Argument(help="Natural language experiment description")],
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON (for piping)")] = False,
) -> None:
    api_key = _get_api_key()

    def _call(on_progress):
        from rivulet._planner_wrapper import call_planner_sync
        return call_planner_sync(prompt, api_key, on_progress=on_progress)

    try:
        plan = _run_with_spinner("Designing experiment...", _call)
    except RuntimeError as e:
        msg = str(e)
        if "timed out" in msg.lower():
            typer.echo(f"Error: Anthropic timed out after 30s. Try again.", err=True)
        else:
            typer.echo(f"Error: {msg}", err=True)
        raise typer.Exit(1)

    _print_result(plan.model_dump(), json_output)


@app.command(
    help=(
        "Revise an ExperimentPlan based on feedback.\n\n"
        "PLAN is a path to an ExperimentPlan JSON file, or '-' to read from stdin.\n"
        "FEEDBACK describes what to change."
    ),
    epilog=(
        "Examples:\n"
        "  rivulet iterate plan.json \"add 3 more drug concentrations\"\n"
        "  rivulet design \"screen 5 drugs\" | rivulet iterate - \"add NK cells\""
    ),
)
def iterate(
    plan: Annotated[str, typer.Argument(help="Path to ExperimentPlan JSON file, or '-' to read from stdin")],
    feedback: Annotated[str, typer.Argument(help="Feedback text describing what to change")],
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON (for piping)")] = False,
) -> None:
    api_key = _get_api_key()

    # Load plan from file or stdin
    if plan == "-":
        try:
            raw = sys.stdin.read()
        except Exception as e:
            typer.echo(f"Error: Failed to read from stdin: {e}", err=True)
            raise typer.Exit(1)
    else:
        plan_path = Path(plan)
        if not plan_path.exists():
            typer.echo(
                f"Error: '{plan}' not found. Run 'rivulet design \"...\"' first, or use '-' to read from stdin.",
                err=True,
            )
            raise typer.Exit(1)
        try:
            raw = plan_path.read_text()
        except OSError as e:
            typer.echo(f"Error: Could not read '{plan}': {e}", err=True)
            raise typer.Exit(1)

    # Validate plan JSON
    try:
        plan_data = json.loads(raw)
    except json.JSONDecodeError:
        typer.echo(
            f"Error: '{plan}' is not a valid ExperimentPlan. Run 'rivulet design \"...\"' to generate one.",
            err=True,
        )
        raise typer.Exit(1)

    from rivulet.models import ExperimentPlan
    try:
        prior_plan = ExperimentPlan(**{k: v for k, v in plan_data.items() if k in ExperimentPlan.model_fields})
    except Exception:
        typer.echo(
            f"Error: '{plan}' is not a valid ExperimentPlan. Run 'rivulet design \"...\"' to generate one.",
            err=True,
        )
        raise typer.Exit(1)

    iterate_prompt = (
        f"Revise this DEP experiment protocol based on the following feedback.\n\n"
        f"Current plan (JSON):\n{prior_plan.model_dump_json(indent=2)}\n\n"
        f"Feedback: {feedback}\n\n"
        f"Return only the revised plan JSON, following the same schema."
    )

    def _call(on_progress):
        from rivulet._planner_wrapper import call_planner_sync
        return call_planner_sync(iterate_prompt, api_key, on_progress=on_progress)

    try:
        revised = _run_with_spinner("Iterating protocol...", _call)
    except RuntimeError as e:
        msg = str(e)
        if "timed out" in msg.lower():
            typer.echo(f"Error: Anthropic timed out after 30s. Try again.", err=True)
        else:
            typer.echo(f"Error: {msg}", err=True)
        raise typer.Exit(1)

    _print_result(revised.model_dump(), json_output)


@app.command(help="List built-in experiment presets.")
def presets(
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON (for piping)")] = False,
) -> None:
    from rivulet.presets import PRESETS

    if json_output or not _is_tty():
        _print_result(PRESETS, json_output)
        return

    # TTY: rich table
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(show_header=True, header_style="bold", min_width=80)
    table.add_column("Name", style="cyan", min_width=16)
    table.add_column("Mode", min_width=14)
    table.add_column("Description")

    for p in PRESETS:
        table.add_row(p["name"], p["mode"], p["description"])

    console.print(table)
