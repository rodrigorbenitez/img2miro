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
img2miro runs conversions through your Claude account (Pro or Max plan -
the free plan won't work). To set it up:
  1. Install Claude Code:  npm install -g @anthropic-ai/claude-code
     (or use the native installer from https://claude.com/claude-code)
  2. Sign in with your Claude account:  claude auth login
     (opens a browser page where you log in at claude.ai)
On headless machines, set CLAUDE_CODE_OAUTH_TOKEN instead (create one with
`claude setup-token`)."""


def _logged_in(claude: str) -> bool:
    try:
        proc = subprocess.run(
            [claude, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return bool(json.loads(proc.stdout).get("loggedIn"))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def _check_claude_code() -> None:
    """Ensure the Claude Code CLI is present and signed in to a Claude account.

    When not signed in and running in an interactive terminal, launch the
    browser sign-in (the user logs in with their Claude account) and continue
    once it completes. Otherwise fail fast with setup instructions.
    """
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("Claude Code CLI not found on PATH.\n" + CLAUDE_SETUP_HELP)

    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return

    if _logged_in(claude):
        return

    if sys.stdin.isatty():
        print(
            "You're not signed in to Claude yet. Opening the browser sign-in - "
            "log in there with your Claude account (Pro or Max plan), then the "
            "conversion will continue.",
            file=sys.stderr,
        )
        subprocess.run([claude, "auth", "login", "--claudeai"])
        if _logged_in(claude):
            return

    sys.exit("Claude sign-in required.\n" + CLAUDE_SETUP_HELP)


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
