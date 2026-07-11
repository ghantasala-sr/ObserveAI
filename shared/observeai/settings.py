import os


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


SERVICE_NAME = env("SERVICE_NAME", "observeai-service")
ENVIRONMENT = env("ENVIRONMENT", "local")
OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
REDPANDA_BROKERS = env("REDPANDA_BROKERS", "redpanda:9092")
PAYMENT_SERVICE_URL = env("PAYMENT_SERVICE_URL", "http://payment-service:8000")
INVENTORY_SERVICE_URL = env("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
CART_SERVICE_URL = env("CART_SERVICE_URL", "http://cart-service:8000")
POSTGRES_DSN = env("POSTGRES_DSN", "postgresql://observeai:observeai@postgres:5432/observeai")
REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")
HTTP_TIMEOUT_SECONDS = float(env("HTTP_TIMEOUT_SECONDS", "2.0"))
KAFKA_MAX_RETRIES = int(env("KAFKA_MAX_RETRIES", "3"))
LOG_LEVEL = env("LOG_LEVEL", "INFO")
