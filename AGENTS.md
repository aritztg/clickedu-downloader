# AGENTS.md — Clickedu Downloader

## Project

A Python CLI tool that downloads all photo albums from a [Clickedu](https://www.clickedu.eu/) school platform — preserving EXIF dates, album descriptions, and original server timestamps.

- **Language:** English (code, comments, docs)
- **Python:** 3.14+
- **Repo:** `aritztg/clickedu-downloader`

## Quick architecture

| Layer | What |
|---|---|
| `src/clickedu_downloader/downloader.py` | Core logic: auth → album discovery → photo download → EXIF/manifest — single `ClickeduDownloader` class |
| `src/clickedu_downloader/__main__.py` | CLI entry point: `argparse` → instantiate → `.run()` |
| `tests/test_downloader.py` | Unit tests (no network, no real auth) |

## Tech stack

| Tool | Purpose |
|---|---|
| `curl-cffi` | HTTP with Chrome fingerprint impersonation (anti-bot) |
| `beautifulsoup4` | HTML parsing (album pages, photo lists) |
| `piexif` | EXIF read/write (`DateTimeOriginal`, `DateTimeDigitized`) |
| `tenacity` | Retry with exponential backoff for failed photo downloads |
| `tqdm` | Progress bars (album-level + photo-level) |
| `python-dotenv` | `.env` credential loading |
| `uv` / `hatchling` | Package management + build |
| `ruff` | Linter (E, F, I, N, W, UP, SIM, LOG) |
| `pylint` | Static analysis (target: 10.00/10) |
| `pytest` | Unit tests |

## Key constraints

- **No network in tests** — tests use fixtures (`real_jpeg` from `downloads/`, HTML strings). Never call `login()` or real HTTP in unit tests.
- **Idempotent** — `download_photo()` skips if the file exists (case-insensitive `.jpg`/`.JPG`).
- **No fake EXIF** — only inject `DateTimeOriginal` if the filename contains a parseable timestamp. Server `Last-Modified` goes to filesystem `mtime` only, never into EXIF.
- **Credentials** — `.env` file only, never hardcoded. Fallback to interactive prompt if `.env` is absent.
- **Filenames** — photos saved as `0001.jpg`, `0002.jpg`, etc. Extension normalized to lowercase.

## Code style

- **Line length:** 120 (`ruff`, `pylint`)
- **Imports:** `from __future__ import annotations` in every module
- **Type hints:** all public methods + class attributes (`strict=true` compatible)
- **Docstrings:** Google-style for public API; concise `#` comments for internals
- **Naming:** `snake_case` for methods/vars, `PascalCase` for classes, `UPPER_CASE` for constants
- **Logging:** `logging.getLogger(__name__)` — use `logger.info/warning/error/debug`, never `print()`
- **Pylint exceptions:** only when genuinely unavoidable; comment `# pylint: disable=...` inline

## Testing

- **Runner:** `pytest -q`
- **Python path:** `pythonpath = ["src"]` in `pyproject.toml`
- **No network:** tests are offline-only
- **Real JPEG required:** `real_jpeg` fixture uses photos from `downloads/` folder; skip tests if none found
- **Target:** 100% pass rate, green CI badge

## CI/CD

- **Trigger:** push/PR to `main`
- **Jobs:** `ruff` → `test` + `lint` (parallel) → `badges` (on push only)
- **Badges:** `ruff` (passing/failing), `pytest` (N passed), `pylint` (X.XX/10, red if <9.0)
- **Badge storage:** `badges` branch (force-pushed with JSON shields.io endpoints)

## Commands (from repo root)

```bash
uv sync                    # Install deps
uv run ruff check src/ tests/   # Lint
uv run pytest -q           # Run tests
uv run pylint src/clickedu_downloader/  # Static analysis
uv run clickedu-downloader --help       # CLI help
uv run clickedu-downloader --dry-run    # Discover albums only
```

## Things to avoid

- ❌ Adding network-dependent tests
- ❌ Hardcoding credentials or URLs with secrets
- ❌ Using `print()` instead of `logging`
- ❌ Changing test behavior to accommodate linting — fix the code, not the test
- ❌ Injecting EXIF dates from `Last-Modified` (false dates = wrong photo ordering)
- ❌ Breaking idempotency — re-runs must be no-op for already-downloaded photos
