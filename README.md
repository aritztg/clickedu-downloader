# Clickedu Downloader

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aritztg/clickedu-downloader/badges/ruff.json)](https://github.com/aritztg/clickedu-downloader/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aritztg/clickedu-downloader/badges/tests.json)](https://github.com/aritztg/clickedu-downloader/actions/workflows/ci.yml)
[![Pylint](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aritztg/clickedu-downloader/badges/pylint.json)](https://github.com/aritztg/clickedu-downloader/actions/workflows/ci.yml)

Download all photo albums from a [Clickedu](https://www.clickedu.eu/) school platform — preserving EXIF dates, album descriptions, and original file timestamps.

## Features

| Category | Feature |
|---|---|
| 🔍 **Discovery** | Auto-discovers every photo album across all pages |
| ⚡ **Parallel** | Multi-threaded downloads with configurable worker count (default: 4) |
| 🔄 **Retry** | Exponential backoff (2s → 4s → 8s) on failed photos via `tenacity` |
| ✅ **Integrity** | Verifies `Content-Length` against actual bytes downloaded |
| 📅 **EXIF dates** | Extracts dates from UNIX-timestamp filenames, writes `DateTimeOriginal` / `DateTimeDigitized` |
| 🕐 **Server timestamps** | Sets local file `mtime` from `Last-Modified` HTTP header (no fake EXIF dates) |
| 📝 **Descriptions** | Saves the teacher's description as `description.txt` in each album folder |
| 📋 **Manifest** | Generates `albums.json` with metadata for every album (photos, EXIF date range, failures) |
| 📊 **Summary** | Reports Downloaded / Cached / Failed counts, with per-album error breakdown |
| 🏷️ **CLI** | Full argparse: `--album`, `--dry-run`, `--output`, `--workers`, `--verbose` |
| 🔁 **Idempotent** | Re-running only downloads new photos; never re-downloads existing ones |
| 📈 **Progress** | `tqdm` progress bars at album + photo level |

## Requirements

- Python 3.14+
- Clickedu credentials (username + password)

## Quick start

### Option 1: uvx (no clone needed)

```bash
# Create a .env file with your credentials
echo 'CLICKEDU_USER=your-username' > .env
echo 'CLICKEDU_PASS=your-password' >> .env

# Run directly from GitHub
uvx --from git+https://github.com/aritztg/clickedu-downloader clickedu-downloader
```

### Option 2: Clone and run

```bash
git clone https://github.com/aritztg/clickedu-downloader.git
cd clickedu-downloader

echo 'CLICKEDU_USER=your-username' > .env
echo 'CLICKEDU_PASS=your-password' >> .env

uvx --from . clickedu-downloader
```

### Option 3: Interactive (no .env)

If no `.env` file or environment variables are present, the tool will prompt for credentials:

```bash
uvx --from git+https://github.com/aritztg/clickedu-downloader clickedu-downloader
# Clickedu username: your-username
# Clickedu password: ********
```

## CLI Reference

```
clickedu-downloader [OPTIONS]
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `--album` | `-a` | *(all)* | Download only albums matching this name (case-insensitive substring) |
| `--output` | `-o` | `downloads` | Output directory for photos |
| `--workers` | `-w` | `4` | Number of parallel download threads |
| `--dry-run` | `-n` | *(off)* | Discover albums and show what would be downloaded, without actually downloading |
| `--verbose` | `-v` | *(off)* | Enable debug-level logging |
| `--url` | | Dominiques BCN | Clickedu site URL |

### Examples

```bash
# Download everything (default)
clickedu-downloader

# Download a single album
clickedu-downloader --album "BIRRETS I5"

# Dry-run to see what's new
clickedu-downloader --dry-run

# Aggressive parallel download + custom output folder
clickedu-downloader --workers 8 --output ~/Pictures/Colegio

# Verbose logging for debugging
clickedu-downloader --album "GIMCANA" --verbose
```

## Output structure

```
downloads/
├── albums.json                    ← Manifest with all albums metadata
├── BIRRETS I5/
│   ├── description.txt            ← Album description (Catalan)
│   ├── 0001.jpg
│   ├── 0002.jpg
│   └── ...
├── GIMCANA ST DOMENEC EI/
│   ├── description.txt
│   ├── 0001.jpg
│   └── ...
└── ...
```

### `albums.json` manifest

```json
[
  {
    "name": "BIRRETS I5",
    "description": "Els nens fan els birrets de graduació...",
    "photos": 47,
    "downloaded": 12,
    "cached": 35,
    "failed": 0,
    "earliest_date": "2026-05-12T10:04:23",
    "latest_date": "2026-06-10T14:30:15"
  }
]
```

## How it works

1. **Login** — authenticates with Clickedu via `curl-cffi` (Chrome fingerprint impersonation)
2. **Discovery** — paginates through the album listing to find all albums
3. **Download** — fetches each album page, extracts description + photo URLs, downloads photos in parallel with retry
4. **EXIF** — if the photo lacks `DateTimeOriginal`, extracts a date from the filename (UNIX timestamps, `YYYYMMDD_HHMMSS`, etc.)
5. **Integrity** — verifies that `Content-Length` matches the actual bytes written to disk
6. **Timestamps** — sets the file's `mtime` from the server's `Last-Modified` header
7. **Manifest** — writes `albums.json` with per-album stats and EXIF date ranges

## EXIF date extraction patterns

| Filename pattern | Example | EXIF injected? |
|---|---|---|
| UNIX milliseconds (13 digits) | `1781603067258.jpg` | ✅ Yes |
| UNIX seconds (10 digits) | `1717000000.jpg` | ✅ Yes |
| `YYYYMMDD_HHMMSS` | `20260619_100923.jpg` | ✅ Yes |
| `IMG_YYYYMMDD_HHMMSS` | `IMG_20260619_101234.jpg` | ✅ Yes |
| `YYYY-MM-DD HH:MM` / ISO | `2024-10-05 14:30.jpg` | ✅ Yes |
| `YYYYMMDD-HHMM` | `20241005-1430.jpg` | ✅ Yes |
| Camera-style (`IMG_XXXX`) | `IMG_1606.JPG` | ❌ No (no timestamp) |

## Development

```bash
git clone https://github.com/aritztg/clickedu-downloader.git
cd clickedu-downloader
uv sync

# Lint
uv run ruff check src/ tests/

# Tests
uv run pytest -q

# Pylint
uv run pylint src/clickedu_downloader/

# Run locally
uv run clickedu-downloader --dry-run
```

## License

MIT
