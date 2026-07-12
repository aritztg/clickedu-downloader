"""Entry point for the CLI."""

from __future__ import annotations

import argparse
import logging

from clickedu_downloader import ClickeduDownloader


def main() -> None:
    """Configure logging, parse CLI args, and run the album downloader."""
    parser = argparse.ArgumentParser(
        description="Download all photo albums from a Clickedu school platform.",
    )
    parser.add_argument(
        "--album", "-a",
        help="Download only albums matching this name (case-insensitive substring).",
    )
    parser.add_argument(
        "--output", "-o",
        default="downloads",
        help="Output directory for photos (default: downloads).",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Number of parallel download threads (default: 4).",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Discover albums and show what would be downloaded, but don't download.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--url",
        help="Clickedu site URL (default: Dominiques BCN).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    downloader = ClickeduDownloader(
        base_url=args.url,
        download_dir=args.output,
        workers=args.workers,
        dry_run=args.dry_run,
    )
    downloader.run(album_filter=args.album)


if __name__ == "__main__":
    main()
