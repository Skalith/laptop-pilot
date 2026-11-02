from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

from .config import Agent2Config
from .service import run_service


def main() -> None:
    parser = argparse.ArgumentParser(description="LaptopPilot Agent 2 — laptop executor")
    parser.add_argument("--allowlist", default="", help="path to the local allow-list JSON file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    load_dotenv()

    config = Agent2Config.from_env()
    if args.allowlist:
        config.allowlist_path = args.allowlist

    errors = config.validate()
    if errors:
        raise SystemExit(f"Agent 2 config missing required values: {', '.join(errors)}")

    run_service(config)
    logging.getLogger("agent2.main").info("Agent 2 stopped")


if __name__ == "__main__":
    main()