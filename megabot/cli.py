"""MegaBot CLI — command-line interface for managing MegaBot.

Usage::

    megabot run        Start the FastAPI orchestrator server
    megabot version    Print the installed version
    megabot health     Check if the server is healthy (hits /health)
    megabot init       Create a mega-config.yaml from the bundled template
"""

from __future__ import annotations

import argparse
import sys


def cmd_version(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Print the installed MegaBot version."""
    from megabot import __version__

    print(f"megabot {__version__}")  # noqa: T201


def cmd_run(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Start the MegaBot orchestrator (equivalent to ``python -m megabot.core.orchestrator``)."""
    # Import lazily to keep CLI startup fast
    import megabot.core.orchestrator as orch_mod

    orch_mod.main()


def cmd_health(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Hit the /health endpoint and report the result."""
    import json

    try:
        import httpx
    except ImportError:
        print("httpx is required for health checks. Install it: pip install httpx")  # noqa: T201
        sys.exit(1)

    url = "http://localhost:8000/health"
    try:
        resp = httpx.get(url, timeout=5.0)
        data = resp.json()
        print(json.dumps(data, indent=2))  # noqa: T201
        sys.exit(0 if resp.is_success else 1)
    except httpx.ConnectError:
        print(f"Could not connect to {url} — is MegaBot running?")  # noqa: T201
        sys.exit(1)


def cmd_init(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Create a mega-config.yaml from the bundled template."""
    import shutil
    from pathlib import Path

    template = Path(__file__).resolve().parent.parent / "mega-config.yaml.template"
    target = Path.cwd() / "mega-config.yaml"

    if target.exists():
        print(f"{target} already exists — not overwriting.")  # noqa: T201
        sys.exit(1)

    if not template.exists():
        print(f"Template not found at {template}")  # noqa: T201
        sys.exit(1)

    shutil.copy2(template, target)
    print(f"Created {target}")  # noqa: T201


def main() -> None:
    """Entry point for the ``megabot`` CLI."""
    parser = argparse.ArgumentParser(
        prog="megabot",
        description="MegaBot — Production-ready, local-first AI orchestrator",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Start the MegaBot orchestrator server")
    sub.add_parser("version", help="Print the installed version")
    sub.add_parser("health", help="Check server health (/health endpoint)")
    sub.add_parser("init", help="Create a mega-config.yaml from template")

    args = parser.parse_args()

    commands = {
        "run": cmd_run,
        "version": cmd_version,
        "health": cmd_health,
        "init": cmd_init,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
