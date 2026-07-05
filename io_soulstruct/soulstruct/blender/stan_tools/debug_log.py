"""Debug logging helpers for Stan's Tools."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soulstruct.blender.utilities import LoggingOperator

__all__ = [
    "STAN_TOOLS_LOGGER",
    "stan_debug",
    "stan_info",
    "stan_warning",
    "ensure_stan_tools_file_logging",
    "stan_tools_log_path",
]

STAN_TOOLS_LOGGER = logging.getLogger("soulstruct.stan_tools")
_IO_LOGGER = logging.getLogger("soulstruct.io")

_FILE_HANDLER: logging.FileHandler | None = None
_FILE_HANDLER_PATH: Path | None = None


def stan_tools_log_path() -> Path:
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    return Path(temp_dir) / "soulstruct-stan-tools.log"


def ensure_stan_tools_file_logging(enabled: bool) -> None:
    """Attach or remove a shared file handler for Stan's Tools debug output."""
    global _FILE_HANDLER, _FILE_HANDLER_PATH

    if enabled:
        log_path = stan_tools_log_path()
        if _FILE_HANDLER is not None and _FILE_HANDLER_PATH == log_path:
            return

        if _FILE_HANDLER is not None:
            for logger in (STAN_TOOLS_LOGGER, _IO_LOGGER):
                logger.removeHandler(_FILE_HANDLER)
            _FILE_HANDLER.close()
            _FILE_HANDLER = None
            _FILE_HANDLER_PATH = None

        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        for logger in (STAN_TOOLS_LOGGER, _IO_LOGGER):
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)

        _FILE_HANDLER = handler
        _FILE_HANDLER_PATH = log_path
        STAN_TOOLS_LOGGER.debug("Stan's Tools file logging enabled: %s", log_path)
        return

    if _FILE_HANDLER is None:
        return

    for logger in (STAN_TOOLS_LOGGER, _IO_LOGGER):
        logger.removeHandler(_FILE_HANDLER)
    _FILE_HANDLER.close()
    _FILE_HANDLER = None
    _FILE_HANDLER_PATH = None


def stan_debug(operator: LoggingOperator | None, msg: str) -> None:
    STAN_TOOLS_LOGGER.debug(msg)
    if operator is not None and getattr(operator, "debug", None) is not None:
        operator.debug(msg)


def stan_info(operator: LoggingOperator | None, msg: str) -> None:
    STAN_TOOLS_LOGGER.info(msg)
    if operator is not None and getattr(operator, "info", None) is not None:
        operator.info(msg)


def stan_warning(operator: LoggingOperator | None, msg: str) -> None:
    STAN_TOOLS_LOGGER.warning(msg)
    if operator is not None and getattr(operator, "warning", None) is not None:
        operator.warning(msg)
