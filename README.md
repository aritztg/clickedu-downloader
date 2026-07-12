# Clickedu Downloader

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aritztg/clickedu-downloader/badges/ruff.json)](https://github.com/aritztg/clickedu-downloader/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aritztg/clickedu-downloader/badges/tests.json)](https://github.com/aritztg/clickedu-downloader/actions/workflows/ci.yml)
[![Pylint](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/aritztg/clickedu-downloader/badges/pylint.json)](https://github.com/aritztg/clickedu-downloader/actions/workflows/ci.yml)

Download all photo albums from a [Clickedu](https://www.clickedu.eu/) school platform — preserving EXIF dates, album descriptions, and original file timestamps.

## Features

- **Full album download** — discovers and downloads every photo album
- **EXIF date injection** — extracts dates from UNIX-timestamp filenames and writes `DateTimeOriginal` / `DateTimeDigitized` tags
- **Server timestamps preserved** — sets the local file's modification time from the `Last-Modified` HTTP header (no fake EXIF dates)
- **Album descriptions** — saves the teacher's Catalan description as `description.txt` inside each album folder
- **Idempotent** — re-running only downloads new photos, never re-downloads
- **Progress bar** — shows album-level progress with `tqdm`

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

Photos are saved to `./downloads/` by default.

### Option 2: Clone and run

```bash
git clone https://github.com/aritztg/clickedu-downloader.git
cd clickedu-downloader

# Create .env with credentials
echo 'CLICKEDU_USER=your-username' > .env
echo 'CLICKEDU_PASS=your-password' >> .env

# Run with uv
uvx --from . clickedu-downloader
```

### Option 3: Interactive (no .env)

If no `.env` file or environment variables are present, the tool will prompt for credentials:

```bash
uvx --from git+https://github.com/aritztg/clickedu-downloader clickedu-downloader
# Clickedu username: your-username
# Clickedu password: ********
```

## Output structure

```
downloads/
├── BIRRETS I5/
│   ├── description.txt       ← Album description (Catalan)
│   ├── 0001.jpg
│   ├── 0002.jpg
│   └── ...
├── GIMCANA ST DOMENEC EI/
│   ├── description.txt
│   ├── 0001.jpg
│   └── ...
└── ...
```

## How it works

1. **Login** — authenticates with Clickedu via `curl-cffi` (Chrome fingerprint)
2. **Discovery** — paginates through the album listing to find all albums
3. **Download** — for each album, fetches the page, extracts the description and photo URLs, downloads them
4. **EXIF** — if the photo lacks `DateTimeOriginal`, tries to extract a date from the filename (UNIX timestamps, `YYYYMMDD_HHMMSS`, etc.)
5. **Timestamps** — sets the file's `mtime` from the server's `Last-Modified` header

## EXIF date extraction patterns

| Filename pattern | Example | EXIF injected? |
|---|---|---|
| UNIX milliseconds | `1781603067258.jpg` | ✅ Yes |
| `YYYYMMDD_HHMMSS` | `20260619_100923.jpg` | ✅ Yes |
| `IMG_YYYYMMDD_HHMMSS` | `IMG_20260619_101234.jpg` | ✅ Yes |
| Camera-style (`IMG_XXXX`) | `IMG_1606.JPG` | ❌ No (no timestamp) |

## Development

```bash
git clone https://github.com/aritztg/clickedu-downloader.git
cd clickedu-downloader
uv sync

# Lint
uv run ruff check src/

# Run locally
PYTHONPATH=src uv run python -m clickedu_downloader
```

## License

MIT
