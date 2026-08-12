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
    # Image (thumbnail) embeddings are produced by a dedicated CLIP service
    # (src/image_embed), since Ollama can't embed images.
    "IMAGE_EMBED_HOST",
    "IMAGE_EMBED_PORT",
    "IMAGE_EMBED_MODEL",
    "IMAGE_EMBED_TIMEOUT_SECONDS",
    "IMAGE_EMBED_BACKFILL_INTERVAL_MINUTES",
    "IMAGE_EMBED_BACKFILL_BATCH_SIZE",
    "IMAGE_EMBED_BACKFILL_CONCURRENCY",
    "IMAGE_EMBED_MAX_ATTEMPTS",
    "IMAGE_EMBED_RETRY_MINUTES",
    "IMAGE_EMBED_MAX_RETRY_MINUTES",
    "IMAGE_FETCH_USER_AGENT",
    "OLLAMA_ANALYSIS_MODEL",
    "OLLAMA_ANALYSIS_NUM_CTX",
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
    "REDDIT_BLOCK_THRESHOLD",
    "REDDIT_BLOCK_COOLDOWN_SECONDS",
    "REDDIT_MAX_BLOCK_COOLDOWN_SECONDS",
]

DEFAULT_CONFIG = {
    "SOURCE_READ_INTERVAL_MINUTES": 60,
    "SOURCE_INGESTION_RUN_INTERVAL_SECONDS": 15,
    "PYTEST_RUNTIME_TYPE": "local",
    "JWT_ALGORITHM": "HS256",
    "OLLAMA_PORT": 11434,
    # Context window (and physical batch size) used when embedding items.
    # Ollama defaults to 2048; items longer than that get a 500 "input too
    # large to process" and end up with no embedding. nomic-embed-text
    # supports up to 8192 tokens, so we raise the default to match.
    "OLLAMA_EMBEDDING_NUM_CTX": 8192,
    # The CLIP image-embedding service (src/image_embed). IMAGE_EMBED_HOST is
    # unset by default so a deployment without the service simply skips image
    # embeddings and falls back to the has-image presence flag; the bundled
    # docker-compose sets the host, enabling it out of the box. IMAGE_EMBED_MODEL
    # is the label the vectors are stored under and must match the model the
    # service actually runs.
    "IMAGE_EMBED_PORT": 8000,
    "IMAGE_EMBED_MODEL": "clip-ViT-B-32",
    "IMAGE_EMBED_TIMEOUT_SECONDS": 30,
    # Items missing an image embedding are retried on this interval, a batch at
    # a time. Image hosts fail transiently (rate limits, timeouts, expired CDN
    # URLs), so a single pass at start up leaves items permanently unembedded.
    # The batch is worked a few items at a time because the job spends nearly
    # all of its time waiting on image hosts; at one item at a time a backlog of
    # tens of thousands of pictures never catches up with ingestion.
    "IMAGE_EMBED_BACKFILL_INTERVAL_MINUTES": 15,
    "IMAGE_EMBED_BACKFILL_BATCH_SIZE": 500,
    "IMAGE_EMBED_BACKFILL_CONCURRENCY": 4,
    # How a failing item is retried. Plenty of preview images are gone for good
    # (expired reddit signatures, deleted uploads, hosts that answer a scraper
    # with HTML), so attempts are counted on the row: each failure pushes the
    # next try out exponentially -- IMAGE_EMBED_RETRY_MINUTES, doubling, capped
    # at IMAGE_EMBED_MAX_RETRY_MINUTES -- and after IMAGE_EMBED_MAX_ATTEMPTS the
    # item leaves the queue entirely. Without that, permanently broken images
    # fill every batch and the rest of the backlog is never reached.
    "IMAGE_EMBED_MAX_ATTEMPTS": 6,
    "IMAGE_EMBED_RETRY_MINUTES": 60,
    "IMAGE_EMBED_MAX_RETRY_MINUTES": 60 * 24 * 3,
    # Preview images are downloaded with a browser user agent because image
    # CDNs (reddit's especially) answer non-browser agents with a 403 — the
    # image renders in the page but never reaches the embedding service.
    "IMAGE_FETCH_USER_AGENT": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # Text-generation model used to propose CSS selectors when creating a
    # source from a bare website URL. Any Ollama chat model that supports
    # structured (JSON schema) output works; qwen3:4b is small and reliable.
    "OLLAMA_ANALYSIS_MODEL": "qwen3:4b",
    # Web pages are large even after condensing, so the analysis model gets a
    # bigger context window than Ollama's 2048 default. Also leaves room for
    # the thinking trace on reasoning models.
    "OLLAMA_ANALYSIS_NUM_CTX": 32768,
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
    # Reddit answers HTTP 403 ("Blocked") to endpoints it won't serve this host
    # at all -- typically the .json API from a datacenter IP, while the public
    # RSS feeds keep working. Waiting between those requests doesn't help, so
    # this many consecutive 403s stops that kind of request for a cooldown
    # instead, doubling on each re-trip up to the ceiling. Values are seconds.
    "REDDIT_BLOCK_THRESHOLD": 3,
    "REDDIT_BLOCK_COOLDOWN_SECONDS": 900.0,
    "REDDIT_MAX_BLOCK_COOLDOWN_SECONDS": 21600.0,
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
