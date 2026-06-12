"""Command-line entry point: python -m img2miro <image> --board <id>"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from .extractor import DEFAULT_MODEL, SUPPORTED_MODELS, extract
from .layout import normalize_layout
from .miro_client import MiroClient, push_diagram

DEFAULT_BOARD = "uXjVHGiQvmg="

CLAUDE_SETUP_HELP = """\
img2miro runs conversions through Claude Code, billed to your Claude
subscription. To set it up:
  1. Install Claude Code:  npm install -g @anthropic-ai/claude-code
     (or use the native installer from https://claude.com/claude-code)
  2. Log in:               claude /login
Note: a Claude Pro or Max subscription is required - the free plan won't work.
On headless machines, set CLAUDE_CODE_OAUTH_TOKEN instead (create one with
`claude setup-token`)."""


def _check_claude_code() -> None:
    """Fail fast if the Claude Code CLI is missing or not authenticated."""
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("Claude Code CLI not found on PATH.\n" + CLAUDE_SETUP_HELP)

    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return

    try:
        proc = subprocess.run(
            [claude, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        status = {}
    if not status.get("loggedIn"):
        sys.exit("Claude Code is installed but not logged in.\n" + CLAUDE_SETUP_HELP)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()

    if "ANTHROPIC_API_KEY" in os.environ:
        print(
            "Warning: ANTHROPIC_API_KEY is set but is now ignored - conversions "
            "run through Claude Code and bill your Claude subscription, not the "
            "API key.",
            file=sys.stderr,
        )
        # Make sure the Claude Code subprocess can't inherit it either.
        del os.environ["ANTHROPIC_API_KEY"]

    parser = argparse.ArgumentParser(
        prog="img2miro",
        description="Convert a diagram image into editable Miro board items.",
    )
    parser.add_argument("image", type=Path, help="Path to the diagram image")
    parser.add_argument("--board", default=DEFAULT_BOARD, help="Miro board id")
    parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        default=DEFAULT_MODEL,
        help=(
            "Claude model used for vision extraction "
            f"(default: {DEFAULT_MODEL}; fable is most capable, "
            "opus is cheaper on usage limits, sonnet is lightest/fastest)"
        ),
    )
    parser.add_argument(
        "--refine",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run a second vision pass to correct the extraction (default: on)",
    )
    args = parser.parse_args(argv)

    if not args.image.is_file():
        sys.exit(f"Image not found: {args.image}")

    _check_claude_code()

    if not os.environ.get("MIRO_ACCESS_TOKEN"):
        sys.exit(
            "Missing environment variable: MIRO_ACCESS_TOKEN. "
            "Set it in the environment or in a .env file."
        )

    diagram = extract(args.image, refine=args.refine, model=args.model)
    diagram = normalize_layout(diagram)
    print(
        f"Extracted {len(diagram.nodes)} node(s), "
        f"{len(diagram.labels)} text label(s) and "
        f"{len(diagram.connectors)} connector(s)."
    )

    miro = MiroClient(os.environ["MIRO_ACCESS_TOKEN"], args.board)
    id_map, created, skipped = push_diagram(miro, diagram)
    print(
        f"Created {len(id_map)} shape(s), {len(diagram.labels)} text item(s) "
        f"and {created} connector(s)."
    )
    for connector in skipped:
        print(
            f"Warning: skipped connector {connector.from_id} -> {connector.to_id} "
            "(unknown endpoint id)",
            file=sys.stderr,
        )
    print(f"Board: {miro.board_url}")


if __name__ == "__main__":
    main()
