"""Command-line entry point: python -m img2miro <image> --board <id>"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from .extractor import (
    BACKENDS,
    DEFAULT_BACKEND,
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    extract,
)
from .layout import normalize_layout
from .miro_client import MiroClient, push_diagram

DEFAULT_BOARD = "uXjVHGiQvmg="

BACKEND_LABELS = {
    "sdk": "Claude subscription (Claude Code sign-in; no API key needed)",
    "api": "Anthropic API key (ANTHROPIC_API_KEY; uses far fewer tokens)",
}

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
    """Ensure the Claude Code CLI is present, then sign the user in through the
    browser before any processing.

    The browser sign-in is launched on every run (a fresh login each time), so
    the user always authenticates with their Claude account up front and never
    has to know any CLI commands. Headless machines skip it by setting
    CLAUDE_CODE_OAUTH_TOKEN.
    """
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("Claude Code CLI not found on PATH.\n" + CLAUDE_SETUP_HELP)

    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return

    print(
        "Sign in to Claude in the browser window that opens (Pro or Max plan); "
        "the conversion continues once you're logged in.",
        file=sys.stderr,
    )
    subprocess.run([claude, "auth", "login", "--claudeai"])
    if not _logged_in(claude):
        sys.exit("Claude sign-in required.\n" + CLAUDE_SETUP_HELP)


def _choose_backend(default: str = DEFAULT_BACKEND) -> str:
    """Prompt for the extraction backend interactively. Returns ``default`` on
    empty input, an unrecognized choice, or a non-interactive run."""
    if not sys.stdin.isatty():
        return default

    print("Choose how to run the vision extraction:", file=sys.stderr)
    for index, name in enumerate(BACKENDS, start=1):
        suffix = " (default)" if name == default else ""
        print(f"  {index}) {BACKEND_LABELS[name]}{suffix}", file=sys.stderr)

    default_index = BACKENDS.index(default) + 1
    choice = input(f"Backend number [default {default_index}]: ").strip()
    if not choice:
        return default
    if choice.isdigit() and 1 <= int(choice) <= len(BACKENDS):
        return BACKENDS[int(choice) - 1]
    if choice in BACKENDS:
        return choice
    print(f"Unrecognized choice '{choice}'; using {default}.", file=sys.stderr)
    return default


def _choose_model(default: str = DEFAULT_MODEL) -> str:
    """Prompt for the vision model interactively. Returns ``default`` on empty
    input, an unrecognized choice, or a non-interactive run (piped/headless)."""
    if not sys.stdin.isatty():
        return default

    print("Choose the vision model:", file=sys.stderr)
    for index, name in enumerate(SUPPORTED_MODELS, start=1):
        suffix = " (default)" if name == default else ""
        print(f"  {index}) {name}{suffix}", file=sys.stderr)

    default_index = SUPPORTED_MODELS.index(default) + 1
    choice = input(f"Model number [default {default_index}]: ").strip()
    if not choice:
        return default
    if choice.isdigit() and 1 <= int(choice) <= len(SUPPORTED_MODELS):
        return SUPPORTED_MODELS[int(choice) - 1]
    if choice in SUPPORTED_MODELS:
        return choice
    print(f"Unrecognized choice '{choice}'; using {default}.", file=sys.stderr)
    return default


def main(argv: list[str] | None = None) -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="img2miro",
        description="Convert a diagram image into editable Miro board items.",
    )
    parser.add_argument("image", type=Path, help="Path to the diagram image")
    parser.add_argument("--board", default=DEFAULT_BOARD, help="Miro board id")
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=None,
        help=(
            "How to run extraction. Omit to choose interactively at startup. "
            "'sdk' bills your Claude subscription via Claude Code (no API key); "
            "'api' uses ANTHROPIC_API_KEY and consumes far fewer tokens."
        ),
    )
    parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        default=None,
        help=(
            "Claude model for vision extraction. Omit to choose interactively "
            f"at startup (default: {DEFAULT_MODEL}; fable is most capable, "
            "opus is the balanced default, sonnet is lightest/fastest)"
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

    # Validate cheap config before opening a browser so a misconfigured run
    # fails fast instead of after the user logs in.
    if not os.environ.get("MIRO_ACCESS_TOKEN"):
        sys.exit(
            "Missing environment variable: MIRO_ACCESS_TOKEN. "
            "Set it in the environment or in a .env file."
        )

    backend = args.backend or _choose_backend()

    if backend == "api":
        # Direct API call billed to the key; no Claude Code sign-in involved.
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit(
                "Missing environment variable: ANTHROPIC_API_KEY (required for "
                "the 'api' backend). Set it in the environment or in a .env "
                "file, or choose the 'sdk' backend instead."
            )
    else:
        # SDK path bills the Claude subscription; an API key would let the
        # Claude Code subprocess silently bill the key instead, so drop it.
        if "ANTHROPIC_API_KEY" in os.environ:
            print(
                "Warning: ANTHROPIC_API_KEY is set but ignored on the 'sdk' "
                "backend - conversions bill your Claude subscription. Choose "
                "the 'api' backend to use the key instead.",
                file=sys.stderr,
            )
            del os.environ["ANTHROPIC_API_KEY"]
        # Sign in via the browser before any processing.
        _check_claude_code()

    model = args.model or _choose_model()

    diagram = extract(args.image, refine=args.refine, model=model, backend=backend)
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
