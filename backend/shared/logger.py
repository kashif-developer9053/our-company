"""Per-module logging. Each module gets its own named logger so failures can be
traced to the module that produced them (part of the isolation guarantee)."""

import logging
import sys

_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-16s | %(message)s")
    )
    root = logging.getLogger("aiagency")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.propagate = False
    _configured = True


def get_logger(module: str) -> logging.Logger:
    """Return a namespaced logger, e.g. get_logger('crm') -> 'aiagency.crm'."""
    _configure_root()
    return logging.getLogger(f"aiagency.{module}")
