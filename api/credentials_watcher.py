"""Hot-reload watcher for the project-root credentials.config file."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from watchfiles import Change, watch

from api.api_factory import CREDENTIALS_FILENAME

if TYPE_CHECKING:
    from api.api_factory import ApiFactory

logger = logging.getLogger(__name__)

# Short debounce: config edits should apply quickly, while still collapsing
# multi-event saves from editors.
DEFAULT_DEBOUNCE_MS = 250
DEFAULT_STEP_MS = 50


def _resolve_credentials_path(credentials_path: str | Path) -> Path:
    path = Path(credentials_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def start_credentials_watcher(
    factory: "ApiFactory",
    *,
    credentials_path: str | Path = CREDENTIALS_FILENAME,
    debounce_ms: int = DEFAULT_DEBOUNCE_MS,
    stop_event: threading.Event | None = None,
) -> threading.Thread:
    """
    Start a daemon thread that watches credentials.config and reloads factory.

    Only the fixed filename is considered. Existing Session clients are not
    mutated by reload; new sessions and GET /models use the reloaded config.
    """
    resolved = _resolve_credentials_path(credentials_path)
    watch_dir = resolved.parent
    target_name = resolved.name
    stop = stop_event or threading.Event()

    def _should_handle(change: Change, path: str) -> bool:
        try:
            return Path(path).resolve().name == target_name
        except OSError:
            return Path(path).name == target_name

    def _run() -> None:
        logger.info(
            "credentials watcher started: file=%s watch_dir=%s debounce_ms=%s",
            resolved,
            watch_dir,
            debounce_ms,
        )
        try:
            for changes in watch(
                str(watch_dir),
                watch_filter=_should_handle,
                debounce=debounce_ms,
                step=DEFAULT_STEP_MS,
                stop_event=stop,
                recursive=False,
            ):
                if stop.is_set():
                    break
                change_summary = sorted(
                    {
                        f"{change.name}:{Path(path).name}"
                        for change, path in changes
                    }
                )
                logger.info(
                    "credentials file change detected: events=%s path=%s",
                    change_summary,
                    resolved,
                )
                # Isolate each reload so a single failure never kills watching.
                try:
                    factory.reload_credentials()
                except Exception:
                    logger.exception(
                        "credentials reload raised unexpectedly; watcher continues: path=%s",
                        resolved,
                    )
        except Exception:
            logger.exception("credentials watcher stopped unexpectedly")
        finally:
            logger.info("credentials watcher stopped: file=%s", resolved)

    thread = threading.Thread(
        target=_run,
        name="credentials-watcher",
        daemon=True,
    )
    thread.start()
    return thread
