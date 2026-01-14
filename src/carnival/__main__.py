import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from carnival.config import CarnivalConfig
from carnival.manager import CarnivalManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Carnival - A lightweight process manager for Docker containers",
        prog="carnival",
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=os.environ.get("CARNIVAL_CONFIG_TOML"),
        help="Path to the configuration file (TOML); also `CARNIVAL_CONFIG_TOML` environment variable",
    )

    parser.add_argument(
        "-l",
        "--log-level",
        choices=["debug", "info", "warn", "error"],
        default=os.environ.get("CARNIVAL_LOG_LEVEL", "info"),
        help="Set log level (default: info); also `CARNIVAL_LOG_LEVEL` environment variable",
    )

    args = parser.parse_args()

    if not args.config:
        parser.error("No configuration file specified. Provide config path as argument or set CARNIVAL_CONFIG_TOML")

    return args


async def async_main() -> int:
    """
    Async main entry point.

    Returns:
        Exit code
    """
    args = parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = CarnivalConfig.from_file(args.config)
    manager = CarnivalManager(config)
    try:
        return await manager.run()
    except KeyboardInterrupt:
        return 130  # Standard exit code for SIGINT


def main() -> None:
    sys.exit(asyncio.run(async_main()))
