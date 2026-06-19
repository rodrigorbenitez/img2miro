"""Command-line entry point: python -m img2miro <image> --board <id>"""

import argparse
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .extractor import DEFAULT_MODEL, SUPPORTED_MODELS, extract
from .layout import normalize_layout
from .miro_client import MiroClient, push_diagram

DEFAULT_BOARD = "uXjVHGiQvmg="


def main(argv: list[str] | None = None) -> None:
    load_dotenv()

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
            f"(default: {DEFAULT_MODEL}; opus is the default, "
            "fable is most capable at ~2.5x the cost, sonnet is cheapest/fastest)"
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

    missing = [
        name
        for name in ("ANTHROPIC_API_KEY", "MIRO_ACCESS_TOKEN")
        if not os.environ.get(name)
    ]
    if missing:
        sys.exit(
            f"Missing environment variable(s): {', '.join(missing)}. "
            "Set them in the environment or in a .env file."
        )

    client = anthropic.Anthropic()
    diagram = extract(client, args.image, refine=args.refine, model=args.model)
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
    # Open centered on the largest new shape (first created) so the diagram is
    # in view even when the board already holds distant items.
    focus_id = next(iter(id_map.values()), None)
    print(f"Board: {miro.focus_url(focus_id)}")


if __name__ == "__main__":
    main()
