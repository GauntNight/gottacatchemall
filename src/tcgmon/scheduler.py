"""Job orchestration: one independent, jittered job per target.

Design rule #3: jitter every interval and isolate failures — a single
source erroring or timing out must not block the others. Each job owns a
try/except and the fetcher itself fails soft to UNKNOWN.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import Settings, Target
from .fetchers import get_fetcher
from .http import jittered, make_client
from .notifier import Notifier
from .store import StateStore

log = logging.getLogger("tcgmon.scheduler")


async def run_target(target: Target, store: StateStore, notifier: Notifier) -> None:
    """Fetch one target, record observations, fire alerts on edges."""
    fetcher = get_fetcher(target.fetcher)
    try:
        async with make_client() as client:
            observations = await fetcher(target, client)
            alerts = []
            for obs in observations:
                alert = store.record(target.name, obs)
                if alert:
                    alerts.append(alert)
            for alert in alerts:
                await notifier.send(alert, client)
        log.info(
            "[%s] %d observed, %d alert(s)",
            target.name, len(observations), len(alerts),
        )
    except Exception:  # noqa: BLE001 — isolate: never let one job kill others
        log.exception("[%s] job crashed", target.name)


def build_scheduler(settings: Settings, store: StateStore,
                    notifier: Notifier) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    enabled = [t for t in settings.targets if t.enabled]
    for target in enabled:
        # Spread the base interval once (so two 10-min jobs don't lock-step),
        # then let the trigger re-jitter each fire by ±spread.
        seconds = jittered(target.interval_seconds, settings.jitter_spread)
        per_fire_jitter = max(1, int(target.interval_seconds * settings.jitter_spread))
        scheduler.add_job(
            run_target,
            trigger=IntervalTrigger(seconds=seconds, jitter=per_fire_jitter),
            args=(target, store, notifier),
            id=target.name,
            name=target.name,
            max_instances=1,
            coalesce=True,
        )
        log.info(
            "scheduled %-28s every ~%.1f min (%s)",
            target.name, seconds / 60, target.fetcher,
        )
    log.info("%d target(s) scheduled", len(enabled))
    return scheduler
