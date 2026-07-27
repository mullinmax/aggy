from pydantic import field_validator, StringConstraints, HttpUrl, model_validator
from datetime import datetime
import base64
import logging
import dateparser
import httpx
from bleach import clean
from typing import Optional, List, Dict
import html
import json
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from config import config
from .base import AggyBaseModel
from typing_extensions import Annotated
from utils import get_ollama_connection


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
    _CHARS_PER_TOKEN = 3

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
        embedding = ollama.embeddings(
            model=ollama_embedding_model,
            prompt=self.embedding_prompt(num_ctx),
            # num_batch must match num_ctx: an embedding prompt is processed in
            # one batch, so a small physical batch (Ollama's 2048 default)
            # rejects longer inputs even when the context window is large.
            options={"num_ctx": num_ctx, "num_batch": num_ctx},
        )["embedding"]

        # add the embedding to self
        self.embeddings[ollama_embedding_model] = embedding

    @staticmethod
    def _fetch_image_base64(image_url: str) -> str:
        """Download the preview image and return it base64-encoded."""
        timeout = config.get_int("IMAGE_EMBED_TIMEOUT_SECONDS")
        response = httpx.get(image_url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return base64.b64encode(response.content).decode("ascii")

    def add_image_embedding(self, model_name: str, force_refresh=False) -> None:
        """Embed the item's preview image via the CLIP image-embedding service
        (src/image_embed) so the recommender can score the picture itself rather
        than only whether one exists.

        No-op when the item has no image or the service isn't configured. Stored
        in ``image_embeddings`` (keyed by model name), kept separate from the
        text ``embeddings`` so the two pieces are never blended into one signal.
        """
        if not self.image_url:
            return

        host = config.get("IMAGE_EMBED_HOST", None)
        if host is None:
            return

        if self.image_embeddings is None:
            self.image_embeddings = {}

        if model_name in self.image_embeddings and not force_refresh:
            return

        try:
            image_base64 = self._fetch_image_base64(self.image_url)
        except Exception as e:
            logging.error(f"Error fetching image {self.image_url}: {e}")
            return

        port = config.get_int("IMAGE_EMBED_PORT")
        timeout = config.get_int("IMAGE_EMBED_TIMEOUT_SECONDS")
        response = httpx.post(
            f"http://{host}:{port}/embed",
            json={"image_base64": image_base64},
            timeout=timeout,
        )
        response.raise_for_status()
        embedding = response.json().get("embedding")
        if embedding:
            self.image_embeddings[model_name] = embedding


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
