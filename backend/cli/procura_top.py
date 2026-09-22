"""procura_top: an htop-style terminal dashboard for the Procura API.

Run from backend/ (with the API already running via `uvicorn main:app --reload`):
    python -m cli.procura_top

Polls http://localhost:8000 every 2 seconds and renders:
  - a process table, color-coded by state
  - resource utilization bars for each of the 5 simulated resources
  - a scrolling "AI SYSTEM" feed of the most recent diagnosis/recovery events

This is Procura's differentiator: the same OS-simulation data is viewable
either as a web dashboard or as a literal terminal process monitor.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
import json

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

API_BASE = "http://localhost:8000"
POLL_SECONDS = 2

STATE_COLORS = {
    "NEW": "grey62",
    "READY": "cyan",
    "RUNNING": "bold green",
    "BLOCKED": "bold yellow",
    "COMPLETED": "bright_black",
    "TERMINATED": "bold red",
}


def fetch_json(path: str) -> object:
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def build_process_table(processes: list[dict]) -> Table:
    table = Table(title="PROCESSES", expand=True, border_style="green")
    table.add_column("PID", justify="right", style="bold")
    table.add_column("NAME")
    table.add_column("STATE")
    table.add_column("PRIORITY")
    table.add_column("BURST", justify="right")
    table.add_column("MEM(MB)", justify="right")
    table.add_column("CPU(%)", justify="right")
    table.add_column("ERRORS", justify="right")

    for p in processes:
        color = STATE_COLORS.get(p["state"], "white")
        table.add_row(
            str(p["pid"]),
            p["name"][:28],
            Text(p["state"], style=color),
            str(p["priority"]),
            str(p["burst_time"]),
            str(p["memory_requirement"]),
            str(p["cpu_requirement"]),
            str(p["error_count"]),
        )
    return table


def build_resource_panel(resources: dict) -> Panel:
    util = resources.get("utilization", {}) if resources else {}
    lines = []
    for name, stats in util.items():
        pct = stats.get("utilization_pct", 0.0)
        bar_color = "green" if pct < 60 else ("yellow" if pct < 85 else "red")
        bar = ProgressBar(total=100, completed=min(pct, 100), width=30, complete_style=bar_color)
        label = Text(f"{name.upper():10}", style="bold")
        console_line = Group(label, bar, Text(f" {pct:5.1f}%  ({stats.get('allocated', 0)}/{stats.get('capacity', 0)})"))
        lines.append(console_line)

    waits = resources.get("waiting_for_graph", {}) if resources else {}
    if waits:
        wait_text = Text("\nWAIT-FOR GRAPH: ", style="bold red")
        wait_text.append(", ".join(f"{k}->{v}" for k, v in waits.items()))
        lines.append(wait_text)

    body = Group(*lines) if lines else Text("No resource data (is the API running?)")
    return Panel(body, title="RESOURCES", border_style="cyan")


def build_ai_feed(errors: list[dict]) -> Panel:
    lines = []
    for row in (errors or [])[:6]:
        ts = (row.get("detected_at") or "")[:19]
        line = Text()
        line.append(f"[{ts}] ", style="dim")
        line.append(f"{row.get('error_type', '?').upper()} ", style="bold red")
        line.append(f"pid={row.get('pid')} ", style="cyan")
        if row.get("action_type"):
            line.append(f"-> {row['action_type']}", style="bold green")
        lines.append(line)
        if row.get("diagnosis_text"):
            snippet = row["diagnosis_text"].strip().replace("\n", " ")[:100]
            lines.append(Text(f"    {snippet}...", style="dim italic"))
    if not lines:
        lines = [Text("No errors detected yet. POST /detect to run the detector.", style="dim")]
    return Panel(Group(*lines), title="AI SYSTEM ACTIVITY FEED", border_style="magenta")


def render(console: Console) -> Layout:
    processes = fetch_json("/processes") or []
    resources = fetch_json("/resources")
    errors = fetch_json("/errors")

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=1),
    )
    header_text = Text(f" PROCURA TOP  |  polling {API_BASE}  |  {time.strftime('%Y-%m-%d %H:%M:%S')} ", style="bold black on green")
    layout["header"].update(Panel(header_text, border_style="green"))
    layout["left"].update(Panel(build_process_table(processes), border_style="green") if processes else Panel(Text("No processes yet. Run seed_data.py or create some via the API."), border_style="red"))

    right_group = Group(build_resource_panel(resources), build_ai_feed(errors))
    layout["right"].update(right_group)
    return layout


def main() -> None:
    console = Console()
    try:
        with Live(render(console), console=console, refresh_per_second=1, screen=True) as live:
            while True:
                time.sleep(POLL_SECONDS)
                live.update(render(console))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
