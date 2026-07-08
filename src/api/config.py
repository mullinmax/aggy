import os

KNOWN_CONFIG_VALUES = [
    "SOURCE_READ_INTERVAL_MINUTES",
    "SOURCE_INGESTION_RUN_INTERVAL_SECONDS",
    "PYTEST_RUNTIME_TYPE",
    "JWT_ALGORITHM",
    "JWT_SECRET",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "EXTRACT_HOST",
    "EXTRACT_PORT",
    "OLLAMA_HOST",
    "OLLAMA_PORT",
    "OLLAMA_USER",
    "OLLAMA_PASSWORD",
    "OLLAMA_EMBEDDING_MODEL",
    "OLLAMA_EMBEDDING_NUM_CTX",
    "RSS_BRIDGE_HOST",
    "RSS_BRIDGE_PORT",
    "BUILD_VERSION",
    "JWT_EXPIRATION_DAYS",
    "SIGNUP_ENABLED",
    "RANKING_INTERVAL_MINUTES",
    # Reddit is rate-limited far more aggressively than most feeds, so it gets
    # its own (slower) default check frequency and a global adaptive throttle.
    "REDDIT_SOURCE_READ_INTERVAL_MINUTES",
    "REDDIT_MIN_REQUEST_INTERVAL_SECONDS",
    "REDDIT_MAX_REQUEST_INTERVAL_SECONDS",
    "REDDIT_INITIAL_REQUEST_INTERVAL_SECONDS",
]

DEFAULT_CONFIG = {
    "SOURCE_READ_INTERVAL_MINUTES": 30,
    "SOURCE_INGESTION_RUN_INTERVAL_SECONDS": 15,
    "PYTEST_RUNTIME_TYPE": "local",
    "JWT_ALGORITHM": "HS256",
    "OLLAMA_PORT": 11434,
    # Context window (and physical batch size) used when embedding items.
    # Ollama defaults to 2048; items longer than that get a 500 "input too
    # large to process" and end up with no embedding. nomic-embed-text
    # supports up to 8192 tokens, so we raise the default to match.
    "OLLAMA_EMBEDDING_NUM_CTX": 8192,
    "RSS_BRIDGE_PORT": 80,
    "BUILD_VERSION": "0.0.0-beta",
    "DB_PORT": 5432,
    "DB_USER": "aggy",
    "DB_NAME": "aggy",
    "JWT_EXPIRATION_DAYS": 7,
    "SIGNUP_ENABLED": True,
    "RANKING_INTERVAL_MINUTES": 15,
    # Reddit forces subreddit sources to "top today", which is fully covered by
    # checking roughly twice a day (12h); this keeps us well under Reddit's
    # anonymous request limits.
    "REDDIT_SOURCE_READ_INTERVAL_MINUTES": 720,
    # Adaptive global throttle for all reddit.com requests. The delay between
    # requests floats between the min (fastest we'll ever go) and max (deep
    # backoff), starting at the initial value; it shrinks cautiously on success
    # and grows exponentially on HTTP 429. Values are seconds.
    "REDDIT_MIN_REQUEST_INTERVAL_SECONDS": 2.0,
    "REDDIT_MAX_REQUEST_INTERVAL_SECONDS": 900.0,
    "REDDIT_INITIAL_REQUEST_INTERVAL_SECONDS": 5.0,
}

FALSEY_STRINGS = {"", "0", "false", "no", "off"}


class ConfigError(Exception):
    """Custom exception for configuration errors."""

    pass


# Sentinel distinguishing "no default given" from an explicit default of None,
# so config.get(key, None) on an unset optional key returns None instead of
# raising (which aborted ingestion on deployments without e.g. Ollama).
_UNSET = object()


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.config = {}

    def get(self, key, default=_UNSET):
        if key not in KNOWN_CONFIG_VALUES:
            raise ConfigError(
                f"Tried to get unknown configuration key: '{key}'. Are you sure this is correct?"
            )

        if key not in self.config:
            env_value = os.getenv(key)
            if env_value is not None:
                self.config[key] = env_value
            elif key in DEFAULT_CONFIG:
                self.config[key] = DEFAULT_CONFIG[key]
            elif default is not _UNSET:
                return default
            else:
                raise ConfigError(
                    f"Tried to get unset known configuration key: '{key}' with no default value"
                )

        return self.config[key]

    def get_int(self, key, default=_UNSET):
        # env values always come back as strings; coerce for numeric config
        return int(self.get(key, default=default))

    def get_float(self, key, default=_UNSET):
        # env values always come back as strings; coerce for numeric config
        return float(self.get(key, default=default))

    def get_bool(self, key, default=_UNSET):
        value = self.get(key, default=default)
        if isinstance(value, str):
            return value.strip().lower() not in FALSEY_STRINGS
        return bool(value)

    def set(self, key, value):
        self.config[key] = value


config = Config()
