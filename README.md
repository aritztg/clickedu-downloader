# clickedu-downloader

Download all photo albums from Clickedu school platforms.

- Uses `curl_cffi` (TLS fingerprint impersonation)
- Python 3.14+
- Package manager: `uv`
- Linter: `ruff`

## Install

```bash
git clone https://github.com/aritztg/clickedu-downloader.git
cd clickedu-downloader
uv sync
```

## Usage

```bash
uv run clickedu-downloader
```

Photos are saved to `downloads/<album_name>/`. Each album folder contains
an `album_info.txt` with the album description. Photos get EXIF
`DateTimeOriginal` tags from the filename (e.g. `20241005_143000`) when
the original image lacks them.
