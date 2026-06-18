#utils/logger.py, colored logger with file rotation

import logging
import logging.handlers
import sys
import pathlib
import datetime


#ANSI collors
_C = {
    "RESET":   "\033[0m",
    "BOLD":    "\033[1m",
    "CYAN":    "\033[96m",
    "GREEN":   "\033[92m",
    "YELLOW":  "\033[93m",
    "RED":     "\033[91m",
    "MAGENTA": "\033[95m",
    "BLUE":    "\033[94m",
    "GREY":    "\033[90m",
}

_LEVEL_COLORS = {
    "DEBUG":    _C["GREY"],
    "INFO":     _C["GREEN"],
    "WARNING":  _C["YELLOW"],
    "ERROR":    _C["RED"],
    "CRITICAL": _C["MAGENTA"],
}


class _ColorFormatter(logging.Formatter):
    FMT = "[{asctime}] [{levelname:<8}] [{name}] {message}"

    def format(self, record: logging.LogRecord) -> str:  #type: ignore[override]
        color = _LEVEL_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{_C['RESET']}"
        record.name = f"{_C['CYAN']}{record.name}{_C['RESET']}"
        record.asctime = (
            f"{_C['GREY']}"
            + datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            + _C["RESET"]
        )
        return super().format(record)

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, style="{", datefmt="%H:%M:%S")


class _PlainFormatter(logging.Formatter):
    FMT = "[{asctime}] [{levelname:<8}] [{name}] {message}"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, style="{", datefmt="%Y-%m-%d %H:%M:%S")


_initialized = False


def setup(log_dir: pathlib.Path, level: str = "INFO") -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    #console collored
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(_ColorFormatter())
    root.addHandler(ch)

    #file, daily rotation, keeps 30 days
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / "nao-api.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    fh.setFormatter(_PlainFormatter())
    root.addHandler(fh)

    #silence noisy third party library logs
    for noisy in ("urllib3", "httpx", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
