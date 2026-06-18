"""Entry point: ``python -m tcgmon`` (daemon) or ``--once`` (single sweep).

    python -m tcgmon                 # run forever on the schedule
    python -m tcgmon --once          # run every enabled target one time
    python -m tcgmon --list          # print configured targets and exit
    python -m tcgmon --signals 100   # dump the last N captured signals as JSON
    python -m tcgmon --config x.yaml # use a different targets file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal

from .config import load_settings
from .fetchers import registered
from .http import make_client
from .notifier import Notifier
from .scheduler import build_scheduler, run_target
from .store import StateStore


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


async def _run_once(settings, store, notifier) -> None:
    enabled = [t for t in settings.targets if t.enabled]
    await asyncio.gather(*(run_target(t, store, notifier) for t in enabled))


async def _run_forever(settings, store, notifier) -> None:
    scheduler = build_scheduler(settings, store, notifier)
    scheduler.start()
    log = logging.getLogger("tcgmon")
    log.info("running; Ctrl-C to stop")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # SIGINT/SIGTERM aren't both available on Windows; register what we can.
    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loop
            signal.signal(sig, lambda *_: stop.set())
    await stop.wait()
    scheduler.shutdown(wait=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tcgmon", description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="run every enabled target once, then exit")
    parser.add_argument("--list", action="store_true",
                        help="list configured targets and exit")
    parser.add_argument("--signals", nargs="?", type=int, const=50, default=None,
                        metavar="N",
                        help="dump the last N captured signals as JSON and exit")
    parser.add_argument("--config", default="targets.yaml",
                        help="path to targets YAML (default: targets.yaml)")
    args = parser.parse_args(argv)

    _setup_logging()
    settings = load_settings(args.config)

    if args.list:
        print(f"Registered fetchers: {', '.join(registered())}\n")
        for t in settings.targets:
            flag = "on " if t.enabled else "off"
            print(f"  [{flag}] {t.name:30s} {t.fetcher:14s} ~{t.interval_minutes}m")
        return 0

    if args.signals is not None:
        store = StateStore(settings.db_path)
        try:
            print(json.dumps(store.recent_signals(args.signals), indent=2))
        finally:
            store.close()
        return 0

    if not settings.ntfy_topic:
        logging.getLogger("tcgmon").warning(
            "NTFY_TOPIC not set — running in DRY-RUN (alerts printed, not pushed)"
        )

    store = StateStore(settings.db_path)
    notifier = Notifier(settings.ntfy_server, settings.ntfy_topic)
    try:
        if args.once:
            asyncio.run(_run_once(settings, store, notifier))
        else:
            asyncio.run(_run_forever(settings, store, notifier))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
