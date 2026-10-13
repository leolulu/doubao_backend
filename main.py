import logging
import sys

from api.credentials_watcher import start_credentials_watcher
from api.model_discovery_watcher import start_model_discovery_watcher
from server.web_server import app, sm
from server.request_protection import configure_protection_logging


def _configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


if __name__ == "__main__":
    _configure_logging()
    configure_protection_logging()
    start_credentials_watcher(sm.api_factory)
    start_model_discovery_watcher(sm.api_factory)
    app.run(debug=False, port=11301, host="0.0.0.0")
