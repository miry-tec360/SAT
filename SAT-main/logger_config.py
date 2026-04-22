import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from logging.handlers import TimedRotatingFileHandler
from typing import Optional
from config import Config

LOG_MAX_BODY = 4000
SENSITIVE_KEYS = {"authorization", "password", "token", "access_token", "refresh_token", "secret"}

if not os.path.exists(Config.SCIM_LOG_DIR):
    os.makedirs(Config.SCIM_LOG_DIR)

LOG_FILE_PATH = os.path.join(Config.SCIM_LOG_DIR, Config.SCIM_LOG_FILE)

_logger = logging.getLogger("SCIM")
_logger.setLevel(getattr(logging, Config.SCIM_LOG_LEVEL, logging.INFO))
_logger.propagate = False

if not _logger.handlers:
    file_handler = TimedRotatingFileHandler(
        LOG_FILE_PATH,
        when="midnight",
        interval=1,
        backupCount=Config.SCIM_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, Config.SCIM_LOG_LEVEL, logging.INFO))
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, Config.SCIM_LOG_LEVEL, logging.INFO))
    console_handler.setFormatter(formatter)
    _logger.addHandler(console_handler)


def get_logger(name: Optional[str] = None):
    if not name:
        return _logger
    return logging.getLogger(f"SCIM.{name}")


def truncate_text(value, limit=LOG_MAX_BODY):
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def safe_json(value, limit=LOG_MAX_BODY):
    try:
        return truncate_text(json.dumps(value, ensure_ascii=False, default=_json_default), limit=limit)
    except Exception:
        return truncate_text(str(value), limit=limit)


def sanitize_dict(data):
    if not isinstance(data, dict):
        return data
    sanitized = {}
    for k, v in data.items():
        if str(k).lower() in SENSITIVE_KEYS:
            sanitized[k] = "***MASKED***"
        else:
            sanitized[k] = v
    return sanitized


def sanitize_headers(headers):
    if headers is None:
        return {}
    try:
        return sanitize_dict(dict(headers))
    except Exception:
        return {}


def sanitize_binds(binds):
    if binds is None:
        return None
    if isinstance(binds, dict):
        return sanitize_dict(binds)
    if isinstance(binds, (list, tuple)):
        return list(binds)
    return binds


LOGGER = _logger
