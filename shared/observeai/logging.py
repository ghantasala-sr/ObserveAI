import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from shared.observeai.settings import LOG_LEVEL


SAFE_EXTRA_FIELDS = {
    "order_id",
    "user_id",
    "scenario",
    "error_type",
    "duration_ms",
    "topic",
    "decision",
    "risk_score",
}
SENSITIVE_KEYS = {"authorization", "card_number", "cvv", "password", "payment_token", "token"}


def _redact(value: Any):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(val)) for key, val in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        span_context = trace.get_current_span().get_span_context()
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service.name": self.service_name,
            "message": record.getMessage(),
            "trace_id": format(span_context.trace_id, "032x") if span_context.is_valid else None,
            "span_id": format(span_context.span_id, "016x") if span_context.is_valid else None,
        }
        for field in SAFE_EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = _redact(getattr(record, field))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service_name: str) -> logging.Logger:
    logger = logging.getLogger(service_name)
    logger.setLevel(LOG_LEVEL)
    logger.propagate = True

    if not any(getattr(handler, "_observeai_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter(service_name))
        handler._observeai_json = True
        logger.addHandler(handler)

    return logger
