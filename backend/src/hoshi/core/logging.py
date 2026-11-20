from logging.config import dictConfig
from pathlib import Path
from typing import Any

from hoshi.core.config import Settings

LOG_BACKUP_COUNT = 14
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(settings: Settings) -> None:
    """配置应用与 Uvicorn 的控制台及按天滚动文件日志。"""

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": LOG_FORMAT,
                "datefmt": LOG_DATE_FORMAT,
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "standard",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_path),
                "when": "midnight",
                "interval": 1,
                "backupCount": LOG_BACKUP_COUNT,
                "encoding": "utf-8",
                "formatter": "standard",
            },
        },
        "loggers": {
            "hoshi": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "file"],
                "level": settings.log_level,
                "propagate": False,
            },
        },
    }
    dictConfig(config)
