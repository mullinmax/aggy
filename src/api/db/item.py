from pydantic import field_validator, StringConstraints, HttpUrl, model_validator
from datetime import datetime
import base64
import logging
import dateparser
import httpx
from bleach import clean
from typing import ClassVar, Optional, List, Dict
import html
import json
import warnings
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from config import config
from .base import AggyBaseModel, get_db_con
from typing_extensions import Annotated
from utils import get_ollama_connection

# Item content is whatever the feed gave us, and plenty of feeds put a bare URL
# in the description. Running it through the sanitizer is correct -- there's
# just nothing to parse -- but BeautifulSoup warns that it "looks more like a
# URL than HTML", once per item, which buries real ingest errors in the log.
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


# Ollama rejects an over-long embedding prompt with a 500 whose message names
# the context length; it has no dedicated error type to catch instead.
_CONTEXT_LENGTH_ERROR_MARKERS = (
    "exceeds the context length",
    "input length exceeds",
    "input is too large",
    "too large to process",
)


def _is_context_length_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _CONTEXT_LENGTH_ERROR_MARKERS)


def _fetch_error_detail(error: Exception) -> str:
    """Short, log-friendly description of a failed image fetch."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    return f"{type(error).__name__}: {error}"


class ImageEmbedError(Exception):
    """A preview image could not be turned into an embedding.

    Raised for every reason an item can fail: the picture couldn't be
    downloaded from any candidate URL, the host answered with something that
    isn't an image, or the embedding service rejected/failed on it. The message
    is short enough to store on the row so a stuck item can be diagnosed
    without digging through logs.
    """


# TODO test that urls are preserved and hashed fully. htps://example.com/0 seems to be truncated to htps://example.com/
class ItemBase(AggyBaseModel):
    url: HttpUrl
    author: Optional[str] = None
    date_published: Optional[datetime] = None
    image_url: Optional[str] = None
    # Rich media extracted at ingest time (gifs, videos, galleries): a list
    # of {"type": "image"|"gif"|"video", "url": ..., "poster": ...} dicts.
    media: Optional[List[Dict[str, Optional[str]]]] = None
    # Text embeddings of the article body, keyed by model name.
    embeddings: Optional[Dict[str, List[float]]] = None
    # Embeddings of the preview image, keyed by vision model name. Kept apart
    # from the text embeddings so the recommender scores each piece on its own.
    image_embeddings: Optional[Dict[str, List[float]]] = None

    @property
    def key(self):
        return f"ITEM:{self.url_hash}"

    @property
    def url_hash(self):
        return self.__insecure_hash__(str(self.url))

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute("SELECT 1 FROM items WHERE url_hash = %s", (self.url_hash,))
            return cur.fetchone() is not None

    def _row_values(self) -> dict:
        data = self.model_dump()
        return {
            "url_hash": self.url_hash,
            "url": str(self.url),
            "title": data.get("title"),
            "author": data.get("author"),
            "domain": data.get("domain"),
            "excerpt": data.get("excerpt"),
            "content": data.get("content"),
            "image_url": data.get("image_url"),
            "media": json.dumps(data["media"])
            if data.get("media") is not None
            else None,
            "date_published": data.get("date_published"),
            "embeddings": json.dumps(data["embeddings"])
            if data.get("embeddings") is not None
            else None,
            "image_embeddings": json.dumps(data["image_embeddings"])
            if data.get("image_embeddings") is not None
            else None,
        }

    def create(self, overwrite=False):
        if not overwrite and self.exists():
            raise ValueError(f"Item with url_hash {self.key} already exists")

        v = self._row_values()
        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO items (url_hash, url, title, author, domain, excerpt, "
                "content, image_url, media, date_published, embeddings, "
                "image_embeddings) "
                "VALUES (%(url_hash)s, %(url)s, %(title)s, %(author)s, %(domain)s, "
                "%(excerpt)s, %(content)s, %(image_url)s, %(media)s, "
                "%(date_published)s, %(embeddings)s, %(image_embeddings)s) "
                "ON CONFLICT (url_hash) DO UPDATE SET "
                "url = EXCLUDED.url, title = EXCLUDED.title, author = EXCLUDED.author, "
                "domain = EXCLUDED.domain, excerpt = EXCLUDED.excerpt, "
                "content = EXCLUDED.content, image_url = EXCLUDED.image_url, "
                "media = EXCLUDED.media, "
                "date_published = EXCLUDED.date_published, "
                "embeddings = EXCLUDED.embeddings, "
                "image_embeddings = EXCLUDED.image_embeddings",
                v,
            )

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        data = dict(row)
        data.pop("url_hash", None)
        data.pop("created_at", None)
        return cls(**data)

    @classmethod
    def read(cls, url_hash):
        with cls.db_con() as cur:
            cur.execute(
                "SELECT url, title, author, domain, excerpt, content, image_url, "
                "media, date_published, embeddings, image_embeddings "
                "FROM items WHERE url_hash = %s",
                (url_hash,),
            )
            row = cur.fetchone()

        return cls.from_row(row)

    def update(self, **updates):
        for field, value in updates.items():
            setattr(self, field, value)
        self.create(overwrite=True)

    def delete(self):
        with self.db_con() as cur:
            cur.execute("DELETE FROM items WHERE url_hash = %s", (self.url_hash,))

    @model_validator(mode="after")
    def sanitize_and_fix_links(self):
        soup = BeautifulSoup(str(self.content), "html.parser")

        # remove all script tags
        [s.extract() for s in soup("script")]

        # remove all style tags
        [s.extract() for s in soup("style")]

        base_url = str(self.url)

        # Find all <a> tags with a relative href attribute
        for a_tag in soup.find_all("a", href=True):
            # Check if the link is relative
            href = a_tag["href"]
            parsed_href = urlparse(href)
            if not parsed_href.netloc:
                # Join the relative link with the base URL
                absolute_url = urljoin(base_url, href)
                a_tag["href"] = absolute_url

        # Find and fix relative src in <img> tags
        for img_tag in soup.find_all("img", src=True):
            src = img_tag["src"]
            parsed_src = urlparse(src)
            if not parsed_src.netloc:
                absolute_url = urljoin(base_url, src)
                img_tag["src"] = absolute_url

        # Sanitize the potentially modified HTML
        self.content = clean(
            str(soup),
            tags=["p", "b", "i", "u", "a", "img", "table", "tr", "td", "th"],
            attributes={
                "a": ["href", "title"],
                "img": ["src", "alt"],
                "table": [],  # Add any table-related attributes if needed
                "tr": [],
                "td": ["colspan", "rowspan"],
                "th": ["colspan", "rowspan"],
            },
            strip=True,
        )
        return self

    @field_validator("date_published", mode="before")
    @classmethod
    def parse_date_published(cls, v):
        if v is None:
            return None
        parsed_date = dateparser.parse(str(v))
        if parsed_date:
            return parsed_date
        raise ValueError("Invalid date format")

    @field_validator(
        "title", "author", "domain", "excerpt", mode="before", check_fields=False
    )
    @classmethod
    def remove_html_tags(cls, v):
        if v:
            # Unescape last: clean() escapes as part of sanitizing, so
            # unescaping first only fed it an "&" to turn back into "&amp;",
            # and the entity was displayed literally. These fields are
            # rendered as text, never as markup, so plain characters are what
            # they should hold.
            return html.unescape(
                clean(str(v), tags=[], attributes={}, strip=True)
            ).strip()
        return v

    def __str__(self):
        non_printable = ["url_hash", "key", "embeddings", "image_embeddings", "media"]
        # all fields besides url_hash, key, and item_embeddings
        print_attrs = [
            f"{k.upper()} {getattr(self, k)}"
            for k in self.__fields__.keys()
            if k not in non_printable
        ]
        return "\n".join(print_attrs)

    # Conservative lower bound on characters per token. Real tokenizers
    # average ~4 chars/token for prose, but dense content (URLs, code,
    # markup) can be ~3, so we budget at 3 to guarantee the character-capped
    # prompt stays under the token context window.
    #
    # Annotated ClassVar so these stay plain class attributes: pydantic turns
    # an unannotated underscore-prefixed attribute into a private attribute
    # descriptor, which reads back as a ModelPrivateAttr off the class.
    _CHARS_PER_TOKEN: ClassVar[int] = 3
    # How many times to halve the prompt when the estimate above turns out to
    # have been too generous anyway. Each retry costs one Ollama round trip,
    # and four halvings take even a full context window down to a sixteenth of
    # its size, which no realistic tokenizer overshoots.
    _EMBEDDING_SHRINK_ATTEMPTS: ClassVar[int] = 4

    def embedding_prompt(self, num_ctx: int) -> str:
        """The text embedded for this item, truncated so it fits the model's
        context window. Ollama processes an embedding prompt in a single
        physical batch, so anything longer than ``num_ctx`` tokens is rejected
        with a 500 and the item ends up with no embedding at all. We cap the
        prompt by characters (a conservative proxy for tokens) to stay safely
        inside the window."""
        prompt = str(self)
        char_budget = num_ctx * self._CHARS_PER_TOKEN
        if len(prompt) > char_budget:
            prompt = prompt[:char_budget]
        return prompt

    def add_embedding(self, model_name: str, force_refresh=False) -> None:
        if not self.embeddings:
            self.embeddings = {}

        if model_name in self.embeddings and not force_refresh:
            return

        ollama = get_ollama_connection()

        # get the embedding
        ollama_embedding_model = config.get("OLLAMA_EMBEDDING_MODEL")
        num_ctx = config.get_int("OLLAMA_EMBEDDING_NUM_CTX")
        prompt = self.embedding_prompt(num_ctx)

        # embedding_prompt caps the prompt by characters, which is only an
        # estimate of its token count -- text that tokenizes densely (CJK,
        # base64, long URLs) can still overflow the window and come back as a
        # 500. Halve and retry rather than leave the item unembedded forever:
        # a shortened embedding is a far better signal than none at all.
        for attempt in range(self._EMBEDDING_SHRINK_ATTEMPTS + 1):
            try:
                embedding = ollama.embeddings(
                    model=ollama_embedding_model,
                    prompt=prompt,
                    # num_batch must match num_ctx: an embedding prompt is
                    # processed in one batch, so a small physical batch
                    # (Ollama's 2048 default) rejects longer inputs even when
                    # the context window is large.
                    options={"num_ctx": num_ctx, "num_batch": num_ctx},
                )["embedding"]
                break
            except Exception as e:
                too_long = _is_context_length_error(e)
                if not too_long or attempt == self._EMBEDDING_SHRINK_ATTEMPTS:
                    raise
                prompt = prompt[: len(prompt) // 2]
                logging.warning(
                    f"Embedding prompt for {self.url} exceeded the model's "
                    f"context window; retrying with {len(prompt)} characters"
                )

        # add the embedding to self
        self.embeddings[ollama_embedding_model] = embedding

    @property
    def embeddable_image_url(self) -> Optional[str]:
        """The picture this item actually shows, for embedding purposes.

        Usually ``image_url``, but a scraped item doesn't always have one:
        reddit RSS entries carry their thumbnail only as an ``<img>`` inside the
        entry body, and the post JSON that would turn it into a real
        ``image_url`` is the request most likely to be rate-limited away. The UI
        already falls back to the first image in the content when rendering a
        card, so those items look like they have a preview while the recommender
        sees no picture at all. Fall back the same way so the two agree.

        Deliberately not written back to ``image_url``: that column drives which
        image the reader promotes out of the article body into the hero slot,
        and a content image belongs in both places at once.
        """
        return embeddable_image_url(self.image_url, self.content)

    @staticmethod
    def _image_fetch_headers() -> Dict[str, str]:
        """Headers used when downloading a preview image.

        Image CDNs — reddit's above all — answer requests that don't look like
        a browser with a 403. httpx's default ``python-httpx/x.y`` agent is
        exactly what they block, which is why reddit previews render fine in
        the page (the browser fetches them directly) but never reached the
        embedding service when we fetched them server-side. The article
        scrapers keep their descriptive ``aggy/...`` agent; only the image
        fetch pretends to be the ``<img>`` tag the CDN expects.
        """
        return {
            "User-Agent": config.get("IMAGE_FETCH_USER_AGENT"),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    @staticmethod
    def _image_fetch_urls(image_url: str) -> List[str]:
        """The URLs to try, in order, for one preview image.

        A stored image URL isn't always fetchable as-is:

        * URLs scraped out of HTML (or out of reddit's JSON before we started
          asking for ``raw_json=1``) can still carry ``&amp;`` entities, which
          corrupt the query string — and reddit signs its preview URLs over
          that query string, so a mangled one is rejected outright.
        * reddit's signed preview host serves the same asset unsigned from
          ``i.redd.it``, which works even when the signature doesn't.
        """
        urls = [image_url]

        unescaped = html.unescape(image_url)
        if unescaped not in urls:
            urls.append(unescaped)

        for url in list(urls):
            parsed = urlparse(url)
            if parsed.netloc.lower() == "preview.redd.it" and parsed.path:
                unsigned = urlunparse(("https", "i.redd.it", parsed.path, "", "", ""))
                if unsigned not in urls:
                    urls.append(unsigned)

        return urls

    @staticmethod
    def _fetch_image_base64(image_url: str) -> str:
        """Download the preview image and return it base64-encoded."""
        timeout = config.get_int("IMAGE_EMBED_TIMEOUT_SECONDS")
        response = httpx.get(
            image_url,
            timeout=timeout,
            follow_redirects=True,
            headers=ItemBase._image_fetch_headers(),
        )
        response.raise_for_status()
        # a host that refuses the request often answers 200 with an HTML
        # notice; sending that on would fail in the embedding service with a
        # far less obvious error
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        if content_type and not content_type.startswith("image/"):
            raise ValueError(f"expected an image, got content-type '{content_type}'")
        return base64.b64encode(response.content).decode("ascii")

    def add_image_embedding(self, model_name: str, force_refresh=False) -> None:
        """Embed the item's preview image via the CLIP image-embedding service
        (src/image_embed) so the recommender can score the picture itself rather
        than only whether one exists.

        No-op when the item has no image or the service isn't configured. Stored
        in ``image_embeddings`` (keyed by model name), kept separate from the
        text ``embeddings`` so the two pieces are never blended into one signal.

        A failure here is swallowed (logged, embedding left absent) because the
        callers are ingest paths where an unfetchable thumbnail must not cost
        the article itself. The backfill calls :func:`embed_image` directly so
        it can record *why* an item failed.
        """
        image_url = self.embeddable_image_url
        if not image_url:
            return

        if config.get("IMAGE_EMBED_HOST", None) is None:
            return

        if self.image_embeddings is None:
            self.image_embeddings = {}

        if model_name in self.image_embeddings and not force_refresh:
            return

        try:
            embedding = embed_image(image_url)
        except ImageEmbedError as e:
            logging.warning(f"No image embedding for {self.url}: {e}")
            return

        if embedding:
            self.image_embeddings[model_name] = embedding


# ---------------------------------------------------------------------------
# Image embedding, without an Item
#
# The backfill works over tens of thousands of rows, so it deliberately doesn't
# hydrate an ItemLoose per candidate: that costs a SELECT of the full article
# body, a pydantic parse, and a re-sanitize of the content per item, and writing
# the result back through Item.update() rewrites every column of the row. These
# functions take the two columns the work actually needs and the DB helpers
# below touch only the embedding columns.
# ---------------------------------------------------------------------------


def embeddable_image_url(
    image_url: Optional[str], content: Optional[str]
) -> Optional[str]:
    """The picture an item actually shows, given its ``image_url``/``content``.

    See :attr:`ItemBase.embeddable_image_url` for why the content fallback
    exists.
    """
    if image_url:
        return image_url
    if not content:
        return None
    # content is stored sanitized, with relative srcs already made absolute
    img = BeautifulSoup(content, "html.parser").find("img", src=True)
    return img["src"] if img else None


def embed_image(image_url: str) -> List[float]:
    """Download a preview image and return its CLIP embedding vector.

    Raises :class:`ImageEmbedError` — with a message short enough to store on
    the item — when the picture can't be fetched from any candidate URL or the
    embedding service won't produce a vector for it.
    """
    image_base64 = None
    failures = []
    for candidate in ItemBase._image_fetch_urls(image_url):
        try:
            image_base64 = ItemBase._fetch_image_base64(candidate)
            break
        except Exception as e:
            failures.append(f"{candidate} ({_fetch_error_detail(e)})")

    if image_base64 is None:
        raise ImageEmbedError(f"could not fetch image: {'; '.join(failures)}")

    host = config.get("IMAGE_EMBED_HOST", None)
    port = config.get_int("IMAGE_EMBED_PORT")
    timeout = config.get_int("IMAGE_EMBED_TIMEOUT_SECONDS")
    try:
        response = httpx.post(
            f"http://{host}:{port}/embed",
            json={"image_base64": image_base64},
            timeout=timeout,
        )
        response.raise_for_status()
        embedding = response.json().get("embedding")
    except Exception as e:
        raise ImageEmbedError(f"embedding service failed: {_fetch_error_detail(e)}")

    if not embedding:
        raise ImageEmbedError("embedding service returned no vector")

    return embedding


# Error messages are stored so a stuck item can be diagnosed from the row; a
# fetch failure that tried several candidate URLs can otherwise run to a few
# hundred characters of little extra value.
_MAX_STORED_IMAGE_EMBED_ERROR = 500

# Candidates for the backfill: items that show a picture but have no vector for
# the model in use. Failing items are held off with an exponential backoff on
# their attempt count, and dropped from consideration entirely once they've
# burned through `max_attempts` -- without that, a batch of permanently
# unfetchable images is re-selected and re-failed on every pass and the queue
# never reaches the items behind them.
#
# Never-attempted items come first so a fresh backlog is always making progress;
# within a tier the newest go first, since those are what the recommender is
# about to rank.
_BACKFILL_CANDIDATES_SQL = """
SELECT url_hash, url, image_url, content
FROM items
WHERE (image_url IS NOT NULL OR content ILIKE '%%<img%%')
  AND (image_embeddings IS NULL OR NOT jsonb_exists(image_embeddings, %(model)s))
  AND image_embed_attempts < %(max_attempts)s
  AND (
        image_embed_failed_at IS NULL
        OR image_embed_failed_at <= NOW() - make_interval(secs =>
            LEAST(
                %(retry_minutes)s * power(2, image_embed_attempts - 1),
                %(max_retry_minutes)s
            ) * 60)
      )
ORDER BY image_embed_attempts ASC, created_at DESC
LIMIT %(limit)s
"""


def image_embed_backfill_candidates(
    model_name: str,
    limit: int,
    max_attempts: int,
    retry_minutes: float,
    max_retry_minutes: float,
) -> List[dict]:
    """Rows the image-embedding backfill should try this pass."""
    with get_db_con() as cur:
        cur.execute(
            _BACKFILL_CANDIDATES_SQL,
            {
                "model": model_name,
                "limit": limit,
                "max_attempts": max_attempts,
                "retry_minutes": float(retry_minutes),
                "max_retry_minutes": float(max_retry_minutes),
            },
        )
        return [dict(row) for row in cur.fetchall()]


def save_image_embedding(
    url_hash: str, model_name: str, embedding: List[float]
) -> None:
    """Merge one image embedding into an item, touching nothing else.

    The attempt counter is cleared: the item is healthy again, so a later model
    change starts it from a full retry budget rather than from whatever failures
    it accumulated under the old one.
    """
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET "
            "image_embeddings = COALESCE(image_embeddings, '{}'::jsonb) "
            "  || jsonb_build_object(%s, %s::jsonb), "
            "image_embed_attempts = 0, "
            "image_embed_failed_at = NULL, "
            "image_embed_error = NULL "
            "WHERE url_hash = %s",
            (model_name, json.dumps(embedding), url_hash),
        )


def record_image_embed_failure(url_hash: str, error: str) -> None:
    """Count a failed image-embedding attempt so the item backs off."""
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET "
            "image_embed_attempts = image_embed_attempts + 1, "
            "image_embed_failed_at = NOW(), "
            "image_embed_error = %s "
            "WHERE url_hash = %s",
            (error[:_MAX_STORED_IMAGE_EMBED_ERROR], url_hash),
        )


def reset_image_embed_attempts(url_hash: str) -> None:
    """Give an item a fresh retry budget.

    Called when a re-scrape turns up a different preview image: the old URL's
    failures say nothing about the new one, and without this an item that
    exhausted its attempts would never be tried again even after the thing that
    was broken about it got fixed.
    """
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = 0, "
            "image_embed_failed_at = NULL, image_embed_error = NULL "
            "WHERE url_hash = %s AND image_embed_attempts > 0",
            (url_hash,),
        )


class ItemStrict(ItemBase):
    title: Annotated[str, StringConstraints(strict=True, min_length=1)]
    domain: str
    excerpt: str
    content: str


class ItemLoose(ItemStrict):
    title: Optional[str] = None
    domain: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None

    @classmethod
    def merge_instances(cls, items: List["ItemLoose"]) -> "ItemLoose":
        # make sure all items are non-null
        items = [item for item in items if item]

        if not items:
            raise ValueError("No items to merge")

        # Initialize the best instance with the first item's values
        best = cls(
            url=items[0].url,
            author=items[0].author,
            date_published=items[0].date_published,
            title=items[0].title,
            image_url=items[0].image_url,
            media=items[0].media,
            domain=items[0].domain,
            excerpt=items[0].excerpt,
            content=items[0].content,
        )

        def longest(*items):
            return max(*items, key=len)

        def shortest(*items):
            return min(*items, key=len)

        for item in items[1:]:  # Start from the second item
            # prefer non-null values
            best.title = best.title or item.title
            best.image_url = best.image_url or item.image_url
            best.media = best.media or item.media
            best.domain = best.domain or item.domain
            best.excerpt = best.excerpt or item.excerpt
            best.content = best.content or item.content
            best.author = best.author or item.author
            best.date_published = best.date_published or item.date_published

            # pick the title closest to 100 characters
            if best.title and item.title:
                if abs(100 - len(item.title)) < abs(100 - len(best.title)):
                    best.title = item.title

            # TODO take the largest image (needs caching server)

            # take the shortest domain
            if best.domain and item.domain:
                best.domain = shortest(best.domain, item.domain)

            # take the largest excerpt between 10 and 250 characters long
            if best.excerpt and item.excerpt:
                item_len = len(item.excerpt)
                if 10 < item_len < 250:
                    best_len = len(best.excerpt)
                    if 10 < best_len < 250:
                        best.excerpt = longest(best.excerpt, item.excerpt)
                    else:
                        best.excerpt = item.excerpt

            # prefer content with html, then longest
            if best.content and item.content:
                if "<" in item.content and "<" not in best.content:
                    best.content = item.content
                else:
                    best.content = longest(best.content, item.content)

            if best.author and item.author and len(item.author):
                best.author = shortest(best.author, item.author)

            # use the oldest date if there are multiple
            if best.date_published and item.date_published:
                best.date_published = min(best.date_published, item.date_published)

        if not best.excerpt and best.content:
            best.excerpt = best.content[:250]

        return best
