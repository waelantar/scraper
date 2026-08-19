"""Command-line entry point for the crawler."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from python_engine.orchestrator import Crawler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m python_engine",
        description="Crawl a site into the Polyglot Engine SQLite cache.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="crawl a seed URL")
    crawl.add_argument("--seed", required=True, help="starting URL")
    crawl.add_argument("--db-path", default="data/pages.db", help="SQLite cache path")
    crawl.add_argument("--num-workers", type=int, default=4, help="worker count")
    crawl.add_argument("--max-depth", type=int, default=1, help="maximum link depth")
    crawl.add_argument("--max-urls", type=int, default=50, help="maximum URLs to attempt")
    crawl.add_argument(
        "--allow-cross-domain",
        action="store_true",
        help="follow links outside the seed domain",
    )
    crawl.add_argument(
        "--no-robots",
        action="store_true",
        help="do not consult robots.txt (not recommended for live sites)",
    )
    crawl.add_argument(
        "--crawl-delay",
        type=float,
        default=1.0,
        help="minimum seconds between requests to one domain",
    )

    return parser


def run_crawl(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    crawler = Crawler(
        seed_urls=[args.seed],
        db_path=str(db_path),
        num_workers=args.num_workers,
        max_depth=args.max_depth,
        max_urls=args.max_urls,
        same_domain=not args.allow_cross_domain,
        respect_robots=not args.no_robots,
        crawl_delay=args.crawl_delay,
    )
    crawler.crawl()
    print(json.dumps(crawler.get_stats(), indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "crawl":
        return run_crawl(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
