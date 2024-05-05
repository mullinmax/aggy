# config_manager.py
import os

DEFAULT_CONFIG = {
    "FEEDS_TO_INGEST_KEY": "FEED-KEYS-TO-INGEST",
    "FEED_INGESTION_PERIOD": 1800,
    "PYTEST_REDIS_DOCKER_NETWORK": "traefik_default",
    "PYTEST_RUNTIME_TYPE": "local",
    "JWT_ALGORITHM": "HS256",
}


class ConfigError(Exception):
    """Custom exception for configuration errors."""

    pass


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.config = {}

    def get(self, key, default=None):
        if key not in self.config:
            env_value = os.getenv(key)
            if env_value is not None:
                self.config[key] = env_value
            elif key in DEFAULT_CONFIG:
                self.config[key] = DEFAULT_CONFIG[key]
            elif default:
                return default
            else:
                raise ConfigError(
                    f"Configuration key '{key}' is not set and no default value provided."
                )
        return self.config[key]

    def set(self, key, value):
        self.config[key] = value


config = Config()
