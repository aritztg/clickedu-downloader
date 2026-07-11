"""Entry point for the CLI."""

import logging

from clickedu_downloader import ClickeduDownloader


def main() -> None:
    """Configure logging and run the album downloader."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    downloader = ClickeduDownloader()
    downloader.run()


if __name__ == "__main__":
    main()
