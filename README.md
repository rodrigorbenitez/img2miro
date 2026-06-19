# img2miro

Convert a diagram image into **editable items on a Miro board** — shapes, text, and connectors that mirror the original as closely as possible: same text, colors, fonts, positions, and arrow routing.

It works by sending the image to Claude (vision + structured outputs), extracting every element as strict JSON, normalizing the layout, and recreating it through the Miro REST API v2.

## Example

Left: the result on a Miro board, fully editable. Right: the original diagram (an AWS architecture from the AWS blog).

![Miro board result next to the original AWS architecture diagram](docs/example-result.jpeg)

Icons and logos can't be reproduced in Miro, so they become placeholder squares in the icon's dominant color, with their captions placed exactly where the text sits in the original.

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/rodrigorbenitez/img2miro.git
cd img2miro
pip install -e .
```

### Credentials

The tool needs two credentials, `ANTHROPIC_API_KEY` and `MIRO_ACCESS_TOKEN`. You can provide them either with a `.env` file or as regular environment variables in your terminal — both work on every platform. If both are set, the environment variables win.

**Option A — `.env` file (recommended: set once, works in every terminal)**

Copy the template in the project root and fill in your own values:

```bash
cp .env.example .env        # macOS/Linux
copy .env.example .env      # Windows
```

```
ANTHROPIC_API_KEY=sk-ant-...
MIRO_ACCESS_TOKEN=...
```

Format rules: one `KEY=value` per line, no quotes, no spaces around the `=`. Run the tool from the project directory (or a subdirectory) so the file is found.

**Option B — environment variables in the terminal**

macOS / Linux (bash or zsh):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export MIRO_ACCESS_TOKEN="your-miro-token"
```

Windows (PowerShell):

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:MIRO_ACCESS_TOKEN = "your-miro-token"
```

These last only for the current terminal session. To make them permanent:

- macOS / Linux: add the two `export` lines to your shell profile (`~/.zshrc` on macOS, `~/.bashrc` on most Linux), then open a new terminal.
- Windows: run `setx ANTHROPIC_API_KEY "sk-ant-..."` and `setx MIRO_ACCESS_TOKEN "your-miro-token"`, then open a new terminal (`setx` does not affect the current one).

**Getting the Anthropic API key**

1. Sign in at [console.anthropic.com](https://console.anthropic.com).
2. Go to **API Keys** and create a new key.
3. Copy it immediately (it's shown only once) — it starts with `sk-ant-`.

Note that conversions consume paid API credits (see [Costs](#costs)).

**Getting the Miro access token**

1. Sign in at [miro.com](https://miro.com) and open the [Developer Apps page](https://miro.com/app/settings/user-profile/apps) (Profile settings → Your apps → Create new app).
2. Create an app, and under **Permissions** enable the `boards:read` and `boards:write` scopes.
3. Click **Install app and get OAuth token** and install it on the team that owns your target board.
4. Copy the access token shown after installing.

You'll also need the **board id**: it's the part of the board URL after `/app/board/`, e.g. for `https://miro.com/app/board/uXjVAbCdEfG=/` the id is `uXjVAbCdEfG=`.

### Keeping credentials out of the repo

- `.env` is listed in `.gitignore`, so git never tracks it — your keys stay on your machine. Only `.env.example` (placeholders, no real values) is committed.
- Never paste real keys into `README.md`, code, commits, or issues. If a key does leak, revoke and regenerate it (Anthropic Console → API Keys; Miro → your app settings).
- Each machine you run the tool on needs its own credentials (its own `.env` or its own environment variables) — they deliberately do not travel through git.
- Terminal-set variables are just as safe as `.env` as long as you avoid putting the `export`/`setx` lines (with real values) in files that get committed.

## Usage

```bash
python -m img2miro path/to/diagram.png --board <your-board-id>
```

| Option | Description |
| --- | --- |
| `--board <id>` | Target Miro board id |
| `--model <name>` | Claude model: `claude-opus-4-8` (default), `claude-fable-5` (most capable, ~2.5× the cost), `claude-sonnet-4-6` (cheapest/fastest) |
| `--refine` / `--no-refine` | Second vision pass that audits the extraction against the image (default: on) |

Supported input formats: PNG, JPEG, GIF, WebP — and **SVG**, which is read as source markup for even higher fidelity (exact coordinates, colors, and text come straight from the file).

## How it works

1. **Extract** — Claude reads the image and returns strict JSON (validated against a pydantic schema via structured outputs): every shape with its geometry, colors, border style, font, and verbatim text; standalone text labels at their exact positions; every connector with its precise attachment points and arrowheads.
2. **Refine** (optional) — a second pass compares the JSON against the image field by field and corrects it.
3. **Normalize** — a geometric pass enforces what the model can't guarantee: text always fits its shape, nested shapes sit fully inside their containers, circles stay circular.
4. **Push** — shapes (largest first, for z-order), then text labels, then connectors are created on the board via the Miro REST API v2.

## Costs

Miro's API is free to use. Each conversion calls the Anthropic API: with the default model and refine pass, expect roughly $0.15–0.60 per image depending on diagram complexity. `--no-refine` halves it; `--model claude-sonnet-4-6` reduces it further.

## Limitations

- Icons/logos become colored placeholder squares (Miro has no icon items).
- Fonts map to Miro's catalog (Open Sans / PT Serif / Caveat) — exact typefaces can't be matched.
- Connector endpoints are pinned to the exact spots from the image, but the path between them is drawn by Miro's router.

## Development

```bash
python -m unittest discover tests
```

Tests cover the mapping and layout layers with a fake Miro client — no network calls.
