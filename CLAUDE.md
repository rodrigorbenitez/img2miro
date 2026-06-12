# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Working end-to-end as of 2026-06-11; migrated from the Anthropic API to the Claude Agent SDK on 2026-06-12 (branch `feature/agent-sdk-migration`). On the dev laptop, Python 3.12 lives at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` and is **not on PATH in pre-existing shells**. The user runs conversions on a *different* PC that clones this repo and has its own `.env` — code changes only reach them after `git push`, and **that PC needs Claude Code installed** after pulling the Agent SDK migration (the first conversion opens the browser sign-in for the Claude account automatically).

## What this project is

`img2miro` — a Python CLI that converts a diagram image into editable items on a Miro board, aiming for a near-mirror copy of the source image (exact text, colors, fonts, positions):

```
python -m img2miro <image> --board <id>
```

- `--refine` (default on; `--no-refine` to disable): second vision pass that audits the extracted JSON against the image.
- Default test board: `uXjVHGiQvmg=`. There is no preview/confirmation step — the push happens immediately (user's explicit choice).

## Architecture

Pipeline: image → `extractor.py` (Claude Agent SDK → strict JSON, parsed and validated locally) → `schema.py` (pydantic v2 models; `extra="forbid"` is load-bearing — it emits `additionalProperties: false`, required by the CLI's `--json-schema` structured-output enforcement, and rejects hallucinated fields on local validation) → `layout.py` (geometric normalization) → `miro_client.py` (Miro REST API v2) → board items. `cli.py` orchestrates.

The model call (`extractor._agent_output`) runs one non-interactive agent turn through `claude_agent_sdk.query()` against the Claude Code CLI: `tools=["Read"]` is the agent's entire tool set (raster images are viewed via Read; SVG source is embedded in the prompt — no tool needed), `output_format={"type": "json_schema", ...}` constrains the response (lands in `ResultMessage.structured_output`; the text path through `_parse_diagram` strips markdown fences defensively and pydantic-validates either way). `_agent_output` is the seam tests fake — everything above it is network- and CLI-free.

Key design decisions (all from user feedback — keep them):

- **Icons/logos** extract as *empty* rectangles at exact position/size; their captions are separate `TextLabel` items (Miro `POST /texts`) placed exactly where the text sits in the image. Never put caption text inside an icon square — combined with text-fit it balloons the square (caused a bad regression once).
- **`layout.py` invariants**: text that overflows even at Miro's 10px font floor grows the shape (capped at 2× height); shapes overlapping a ≥1.2×-larger shape by ≥50% of their area get clamped fully inside it, below the container's title strip. Empty-text shapes are never grown.
- **Z-order** = Miro creation order: shapes largest-first, then text labels, then connectors.
- **Text fit metrics** in `miro_client.py` are deliberately conservative (CHAR_WIDTH 0.62, LINE_HEIGHT 1.4) — Miro renders wider than geometric estimates; underestimating hides text.

The mapping layer in `miro_client.py` (`shape_payload`, `text_payload`, `connector_payload`, `push_diagram`) is network-free: `push_diagram` accepts any object with `create_shape`/`create_text`/`create_connector`, so tests use a fake client.

- Vision model: `claude-fable-5` by default (user explicitly requested the most capable model; `--model` offers opus-4-8/sonnet-4-6 — Haiku excluded). There is no direct API client and no `stop_reason` to read — failures (including refusals) surface via `ResultMessage.is_error`/`errors` and are raised as `RuntimeError`. Usage bills the user's Claude subscription.
- **Input formats**: PNG/JPEG/GIF/WebP are viewed by the agent's Read tool. **SVG goes as source text** (the markup carries exact coordinates/colors/text — higher fidelity than rasterizing, no extra deps). Capped at 800KB (bigger usually means embedded rasters → tell the user to export PNG).
- Dependencies are limited to: `claude-agent-sdk`, `requests`, `pydantic`, `python-dotenv`. Do not add others. Tests use stdlib `unittest`.
- Credentials: `MIRO_ACCESS_TOKEN` from env or `.env` (gitignored; exists on both machines). Claude auth comes from the user's Claude account (browser sign-in, or `CLAUDE_CODE_OAUTH_TOKEN` on headless machines) — `cli.py` checks `claude auth status --json` at startup; if not signed in and the terminal is interactive, it launches the browser sign-in itself (`claude auth login --claudeai`) and continues after the user logs in, otherwise it fails fast with setup instructions. The user's explicit UX requirement: the user signs in with their Claude account in the browser — they should never need to know Claude Code CLI commands. `ANTHROPIC_API_KEY` is deliberately warned about and **deleted from the environment** at startup so the Claude Code subprocess can never silently bill it — do not remove that guard.

## Critical Miro API quirks

- On `POST /shapes`, always send `style.fillOpacity = "1.0"` and `style.borderOpacity = "1.0"` (as strings). Without these, shapes are created but invisible. Verified empirically — do not remove (locked by a unit test).
- `fontFamily` must be a value from Miro's fixed catalog; an invalid one 400s the shape. Only `open_sans`, `pt_serif`, `caveat` are used (mapped from sans/serif/handwritten).
- Numeric style fields (`fontSize`, `borderWidth`) are strings, with ranges 10–288 and 1–24.

## Development

- Install: `pip install -e .`
- Run: `python -m img2miro <image> --board <id>` (or the `img2miro` console script)
- Tests: `python -m unittest discover tests` — mapping + layout layers, fake Miro client; no network calls in tests.
- End-to-end verification: push a test image to board `uXjVHGiQvmg=` and confirm items render.
