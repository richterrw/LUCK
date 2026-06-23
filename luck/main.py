"""Entrypoint for the LUCK SPCX options day-trading agent."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .agent import Agent
from .broker import AlpacaBroker
from .config import confirm_live_mode, load_config


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SPCX options day-trading agent")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single evaluation and exit")
    parser.add_argument("--dry-run", action="store_true", help="never place orders; log intended actions")
    args = parser.parse_args(argv)

    _setup_logging()
    log = logging.getLogger("luck")

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    cfg = load_config(args.config)

    live = cfg.is_live
    if live and not args.dry_run:
        if not confirm_live_mode():
            log.error("Live confirmation not given. Aborting.")
            return 1
        log.warning("LIVE REAL-MONEY MODE ENABLED")
    else:
        log.info("Running in %s mode%s",
                 "PAPER" if not live else "LIVE",
                 " (dry-run, no orders)" if args.dry_run else "")

    try:
        broker = AlpacaBroker(live=live)
    except RuntimeError as exc:
        log.error("Broker init failed: %s", exc)
        return 1

    agent = Agent(broker, cfg, dry_run=args.dry_run)

    if args.once:
        agent.step()
        return 0

    log.info("Starting loop for %s (poll every %ds). Ctrl-C to stop.",
             cfg.symbol, cfg.polling.interval_seconds)
    try:
        while True:
            agent.step()
            if agent.risk_state.halted:
                log.warning("Halted for the day. Exiting loop.")
                break
            time.sleep(cfg.polling.interval_seconds)
    except KeyboardInterrupt:
        log.info("Interrupted. Flattening open positions before exit.")
        agent._flatten_all("shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
