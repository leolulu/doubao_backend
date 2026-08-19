"""Periodic model discovery watcher for auto-mode ChatCompletion providers."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.api_factory import ApiFactory

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 3600


def start_model_discovery_watcher(
    factory: "ApiFactory",
    *,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    stop_event: threading.Event | None = None,
) -> threading.Thread:
    """
    Start a daemon thread that periodically re-discovers auto-mode models.

    Calls factory.reload_auto_providers() every *interval_seconds*. Each call
    is isolated so a single failure never kills the watcher. Existing Session
    clients are not mutated; only the factory's client pool is refreshed.

    Returns the started daemon thread.
    """
    stop = stop_event or threading.Event()

    def _run() -> None:
        logger.info(
            "model discovery watcher started: interval_seconds=%s",
            interval_seconds,
        )
        while not stop.is_set():
            stop.wait(timeout=interval_seconds)
            if stop.is_set():
                break
            try:
                results = factory.reload_auto_providers()
                logger.info(
                    "model discovery watcher cycle completed: results=%s",
                    results,
                )
            except Exception:
                logger.exception(
                    "model discovery watcher cycle raised; watcher continues"
                )
        logger.info("model discovery watcher stopped")

    thread = threading.Thread(
        target=_run,
        name="model-discovery-watcher",
        daemon=True,
    )
    thread.start()
    return thread
