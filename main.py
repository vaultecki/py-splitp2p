# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
SplitP2P - Expense splitting without a central server.
Entry point: configures logging, then starts the GUI.

Usage:
    python main.py
"""

import logging
import sys


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("splitp2p.log", encoding="utf-8"),
        ],
    )
    # Silence noisy third-party loggers
    for lib in ("asyncio", "urllib3", "libp2p", "trio"):
        logging.getLogger(lib).setLevel(logging.WARNING)
    # Uncomment to debug P2P packet flow:
    # logging.getLogger("network").setLevel(logging.DEBUG)


if __name__ == "__main__":
    _setup_logging()
    logging.getLogger(__name__).info("SplitP2P starting")

    from gui import run
    run()
