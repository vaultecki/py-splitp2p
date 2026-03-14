# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

"""
ThaOTP – Encrypted P2P Messenger
Entry point: sets up logging, then launches the GUI.

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
            logging.FileHandler("thaOTP.log", encoding="utf-8"),
        ],
    )
    # Quiet noisy third-party loggers
    for noisy in ("asyncio", "urllib3", "libp2p"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


if __name__ == "__main__":
    _setup_logging()
    logging.getLogger(__name__).info("Starting ThaOTP")

    from gui import run
    run()
