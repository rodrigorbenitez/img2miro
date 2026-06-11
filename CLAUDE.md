# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Code is built, installed (`pip install -e .`), and unit-tested (6/6 passing as of 2026-06-11). Python 3.12 lives at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` and is **not on PATH in pre-existing shells** — invoke it by full path or start a fresh shell. Not yet done: end-to-end run against the Miro board, blocked on credentials (no `.env`, no env vars set).

## What this project is

`img2miro` — a Python CLI that converts a diagram image into editable items on a Miro board:

```
python -m img2miro <image> --board <id>
```

- `--refine` (default on): second Anthropic vision pass to correct the extracted JSON.
- `--yes`: skip the local preview confirmation step.
- Default test board: `uXjVHGiQvmg=`.

## Architecture

Pipeline: image → `extractor.py` (Anthropic vision → strict JSON via structured outputs) → `schema.py` (pydantic v2 models; `extra="forbid"` is load-bearing — it emits `additionalProperties: false`, required by the structured-outputs API) → `preview.py` (local SVG render for user confirmation) → `miro_client.py` (Miro REST API v2) → board items. `cli.py` orchestrates.

The mapping layer in `miro_client.py` (`shape_payload`, `connector_payload`, `push_diagram`) is deliberately network-free: `push_diagram` accepts any object with `create_shape`/`create_connector`, so tests use a fake client.

- Vision model: `claude-opus-4-8`, with streaming and adaptive thinking. (Spec said "claude-sonnet-4-20250514 or newer"; that ID is deprecated — opus-4-8 qualifies.)
- Dependencies are limited to: `anthropic`, `requests`, `pydantic`, `python-dotenv`. Do not add others.
- Credentials: read `ANTHROPIC_API_KEY` and `MIRO_ACCESS_TOKEN` from env or a `.env` file (python-dotenv). The Miro token already exists with `boards:read`/`boards:write` scopes; neither variable is set in the shell — check for a `.env` file.

## Critical Miro API quirk

On `POST /shapes`, always send `style.fillOpacity = "1.0"` and `style.borderOpacity = "1.0"` (as strings). Without these, shapes are created but invisible. Verified empirically by the user — do not remove.

## Development

- Install: `pip install -e .`
- Run: `python -m img2miro <image> --board <id>` (or the `img2miro` console script)
- Tests: `python -m unittest discover tests` — mapping layer only, with a fake Miro client; no network calls in tests.
- End-to-end verification: push a test image to board `uXjVHGiQvmg=` and confirm items render.
