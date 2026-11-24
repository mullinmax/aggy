import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urlparse

from constants import SOURCE_READ_INTERVAL_MINUTES
from db.base import get_db_con
from db.feed import Feed
from db.item import (
    ImageEmbedError,
    ItemLoose,
    embed_image,
    embeddable_image_url,
    fetch_image_base64,
    image_embed_backfill_candidates,
    record_image_embed_failure,
    reset_image_embed_attempts,
    save_image_embedding,
)
from db.source import Source
from db.task_run import (
    KIND_IMAGE_EMBED_BACKFILL,
    KIND_SOURCE_INGEST,
    KIND_SOURCE_RESCRAPE,
    STATUS_ERROR,
    STATUS_OK,
    finish_run,
    prune_runs,
    set_run_target,
    start_run,
    task_run,
)
from db.source_attempt import (
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    prune_attempts,
    record_attempt,
)
from ingest import host_circuit
from ingest.errors import IngestError
from ingest.backends import UNSCHEDULED_KINDS, get_backend
from ingest.host_circuit import HostUnavailable, source_host
from ingest.source import ingest_source
from ingest.item.reddit import REMOVAL_NOTICES, ingest_reddit_item, is_reddit_post
from ingest.item.open_graph import ingest_open_graph_item
from ingest.item.mercury import ingest_mercury_item
from db.user import User
from utils import get_ollama_connection
from config import config

# Item fields whose text feeds the embedding prompt (see ItemBase.__str__):
# a change in any of them means the stored embedding is stale.
_EMBEDDING_TEXT_FIELDS = (
    "title",
    "author",
    "date_published",
    "domain",
    "excerpt",
    "content",
)

# Item fields re-collected by a re-scrape. A change in any of them is worth
# persisting, and — for voted items — worth retraining the feed's models on.
_RESCRAPE_FIELDS = _EMBEDDING_TEXT_FIELDS + ("image_url", "media")


def source_ingestion_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            for source in feed.sources:
                # a manual source (saved links) has no URL to poll
                if not get_backend(source.kind).scheduled:
                    continue
                source.trigger_ingest(now=False)


def source_ingestion_job() -> None:
    """Pop the next due source and ingest it.

    Mirrors the previous Redis ZMPOP-based queue: pick the source with the
    smallest ``next_ingest_at``, only proceed if it's actually due, and then
    bump its next ingest time forward.

    All time comparison happens in SQL so it is done against the database
    clock; ``next_ingest_at`` is a TIMESTAMPTZ and comparing it to a naive
    Python ``datetime.now()`` silently pushes ingestion hours into the
    future whenever the app and database timezones differ.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT user_hash, feed_hash, name_hash FROM sources "
            "WHERE next_ingest_at <= NOW() + interval '1 minute' "
            "AND kind <> ALL(%s) "
            "ORDER BY next_ingest_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
            (UNSCHEDULED_KINDS,),
        )
        row = cur.fetchone()

        if not row:
            return

        cur.execute(
            "UPDATE sources SET next_ingest_at = NOW() + "
            "make_interval(mins => COALESCE(ingest_interval_minutes, %s)) "
            "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
            (
                SOURCE_READ_INTERVAL_MINUTES,
                row["user_hash"],
                row["feed_hash"],
                row["name_hash"],
            ),
        )

    source = None
    # Opened before the source is even read, so a pass that dies on the read
    # still leaves a record of having been attempted. The branches below close
    # it on the way out; a skip is recorded as an error with its reason, since
    # the page's job is to show that the pass did not do any work and why.
    run_id = start_run(KIND_SOURCE_INGEST, user_hash=row["user_hash"])
    try:
        source = Source.read(
            user_hash=row["user_hash"],
            feed_hash=row["feed_hash"],
            source_hash=row["name_hash"],
        )
        set_run_target(run_id, source.name)
        logging.info(f"Ingesting source '{source.name}' ({source.url})")
        _ingest_with_circuit(source)
        source.mark_ingested()
        finish_run(run_id, detail=f"ingested '{source.name}'")
    except HostUnavailable as e:
        # Not a failure of this source: its site is in cooldown and was never
        # contacted. Logged at info because a broken site produces one of these
        # per source per cycle, and they are the breaker working, not news.
        logging.info(f"Skipping source '{source.name}': {e}")
        source.mark_ingest_error(str(e))
        finish_run(run_id, STATUS_ERROR, f"skipped: {e}")
        return
    except IngestError as e:
        # An ordinary bad day on the open web: the site is down, the feed came
        # back empty, a bridge complained. One line, no traceback — the reason
        # is already written for a person, and it is stored on the source and
        # shown beside it in the UI.
        logging.warning(f"{_source_label(source, row)}: {e}")
        if source is not None:
            source.mark_ingest_error(str(e))
        finish_run(run_id, STATUS_ERROR, str(e))
        return
    except Exception as e:
        # Anything that isn't an IngestError got here without being explained,
        # which makes it a bug — that one keeps its traceback.
        logging.exception(f"{_source_label(source, row)} failed unexpectedly: {e}")
        if source is not None:
            source.mark_ingest_error(str(e))
        finish_run(run_id, STATUS_ERROR, f"{type(e).__name__}: {e}")
        return


def _source_label(source, row) -> str:
    """How a source is named in the log. The name and URL are what identify
    it to a person; the hash is a last resort for a source we couldn't even
    read back."""
    if source is None:
        return f"Source {row['name_hash']}"
    return f"Source '{source.name}' ({source.url})"


def _ingest_with_circuit(source: Source) -> None:
    """Ingest a source, reporting the outcome to the per-site breaker.

    Feed sources are exempt: they read another feed out of our own database
    rather than fetching a site, so there is no host whose reliability they
    could speak to.
    """
    if source.is_feed_source:
        ingest_source(source=source)
        return

    host = source_host(str(source.url))

    try:
        host_circuit.check(str(source.url))
    except HostUnavailable:
        record_attempt(
            user_hash=source.user_hash,
            feed_hash=source.feed_hash,
            source_hash=source.name_hash,
            host=host,
            outcome=OUTCOME_SKIPPED,
        )
        raise

    try:
        ingest_source(source=source)
    except Exception as e:
        host_circuit.record_failure(str(source.url))
        record_attempt(
            user_hash=source.user_hash,
            feed_hash=source.feed_hash,
            source_hash=source.name_hash,
            host=host,
            outcome=OUTCOME_ERROR,
            error=str(e),
        )
        raise

    host_circuit.record_success(str(source.url))
    record_attempt(
        user_hash=source.user_hash,
        feed_hash=source.feed_hash,
        source_hash=source.name_hash,
        host=host,
        outcome=OUTCOME_OK,
    )


def prune_ingest_attempts_job() -> None:
    """Drop the attempt and task-run history that has aged out.

    Both are append-one-row-per-pass histories on the same schedule, so they are
    trimmed together rather than by two jobs doing the same thing.
    """
    prune_runs()
    try:
        deleted = prune_attempts()
    except Exception as e:
        logging.error(f"Pruning ingest attempt history failed: {e}")
        return
    if deleted:
        logging.info(f"Pruned {deleted} ingest attempt(s) from history")


def ingest_source_now(source: Source) -> None:
    """Ingest a freshly-added source immediately (outside the schedule).

    Pushes the next scheduled run out first so the interval job doesn't
    double-ingest, then runs the ingest inline.
    """
    source.push_next_ingest()
    try:
        logging.info(f"Ingesting new source '{source.name}' ({source.url})")
        ingest_source(source=source)
        source.mark_ingested()
    except IngestError as e:
        logging.warning(f"First check of source '{source.name}' ({source.url}): {e}")
        source.mark_ingest_error(str(e))
    except Exception as e:
        logging.exception(f"First check of source '{source.name}' failed: {e}")
        source.mark_ingest_error(str(e))


# The target recorded for a manually triggered pass over every source an
# account owns. Distinct from the per-source passes the scheduler records, so
# the tasks page can tell them apart -- and so "is this already running" asks
# about another batch rather than about whichever single source the scheduler
# happens to be working on right now.
ALL_SOURCES_TARGET = "all sources"


def user_sources(user_hash: str) -> list:
    """Every source an account owns, once.

    The same feed URL can be a source of several feeds, and re-fetching or
    re-scraping it once per feed is the same work done twice; deduplicated on
    the URL so a manual pass costs what it looks like it costs.
    """
    seen = set()
    sources = []
    for feed in Feed.read_all(user_hash=user_hash):
        for source in feed.sources:
            if source.url in seen:
                continue
            seen.add(source.url)
            sources.append(source)
    return sources


def ingest_user_sources(user_hash: str) -> None:
    """Fetch every source an account owns, now, outside the schedule.

    One run is recorded for the batch rather than one per source: the scheduler
    already records a pass per source, and a manual sweep is one thing the
    person asked for, not fifty.
    """
    sources = user_sources(user_hash)
    logging.info(f"Ingesting {len(sources)} source(s) on request")

    with task_run(KIND_SOURCE_INGEST, user_hash, ALL_SOURCES_TARGET) as run:
        failed = 0
        for source in sources:
            try:
                ingest_source_now(source)
            except Exception as e:
                # ingest_source_now records the failure on the source itself;
                # the batch keeps going, because one dead site must not cost
                # the person the other forty-nine.
                failed += 1
                logging.warning(f"Ingesting source '{source.name}' failed: {e}")
        run.detail = f"{len(sources)} source(s) ingested" + (
            f", {failed} failed" if failed else ""
        )


def rescrape_user_sources(user_hash: str) -> None:
    """Re-scrape every source an account owns, now.

    The expensive one: every stored item of every source is re-fetched from its
    original site and re-embedded. Recorded as one run for the batch, whose
    detail says how far it got.
    """
    sources = user_sources(user_hash)
    logging.info(f"Re-scraping {len(sources)} source(s) on request")

    with task_run(KIND_SOURCE_RESCRAPE, user_hash, ALL_SOURCES_TARGET) as run:
        failed = 0
        for source in sources:
            try:
                rescrape_source(source)
            except Exception as e:
                failed += 1
                logging.exception(f"Re-scraping source '{source.name}' failed: {e}")
        run.detail = f"{len(sources)} source(s) re-scraped" + (
            f", {failed} failed" if failed else ""
        )


def _feeds_with_votes_on(url_hash: str) -> set:
    """(user_hash, feed_hash) pairs that have cast a vote on this item."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT DISTINCT user_hash, feed_hash FROM item_states "
            "WHERE item_url_hash = %s AND score IS NOT NULL",
            (url_hash,),
        )
        return {(row["user_hash"], row["feed_hash"]) for row in cur.fetchall()}


def _replace_with_fresh_pictures(
    merged: ItemLoose,
    stored: ItemLoose,
    reddit_item: Optional[ItemLoose],
    scraped: list,
) -> None:
    """Make ``merged`` show what the re-scrape found rather than what was
    stored.

    merge_instances keeps the first non-empty value it sees, and the stored
    item goes in first so that what only the feed itself delivered (and a
    re-scrape cannot fetch again) survives. For the picture that is wrong: a
    stored image_url would win over whatever the page shows today, and a post
    that has since been deleted would keep its old preview for good. The vote
    model has to see the article as it is now, so a fresh picture replaces the
    stored one, and when the page that is authoritative for the picture
    answered without one, the stored one is cleared rather than kept.

    For a reddit post that page is the post's JSON. Anywhere else nothing can
    yet tell "the page has no picture" from "the scraper could not read it",
    so a stored picture is only ever replaced, never cleared.
    """
    fresh_image = next((s.image_url for s in scraped if s and s.image_url), None)

    if not is_reddit_post(str(stored.url)):
        merged.image_url = fresh_image or stored.image_url
        return

    if reddit_item is None:
        # reddit didn't answer (rate limited, blocked, down): that says
        # nothing about the post, so keep what we have unless something
        # else turned up a picture
        merged.image_url = fresh_image or stored.image_url
        return

    merged.media = reddit_item.media
    if reddit_item.content in REMOVAL_NOTICES:
        # The post is gone. Its picture lives on in the body the feed
        # delivered too (the card and the recommender both fall back to the
        # first image in it), so the notice replaces the body as well,
        # otherwise the old preview would keep showing through.
        merged.image_url = None
        merged.content = reddit_item.content
        merged.excerpt = reddit_item.excerpt
        return

    merged.image_url = fresh_image


def _feeds_carrying(url_hash: str) -> set:
    """Every (user_hash, feed_hash) the item shows up in, voted on or not."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT DISTINCT user_hash, feed_hash FROM feed_items "
            "WHERE item_url_hash = %s",
            (url_hash,),
        )
        return {(row["user_hash"], row["feed_hash"]) for row in cur.fetchall()}


class ArticleUnreachable(IngestError):
    """Starting fresh found nothing to rebuild the article from."""


_UNREACHABLE = (
    "Couldn't reach the article to start fresh, so it was left as it was."
)


def _collect_fresh(
    item: ItemLoose, backend, wipe_if_unreachable: bool = False
) -> ItemLoose:
    """The article built only from what its site answers with right now.

    Nothing of the stored copy is merged back in, so whatever a removed post
    used to show is gone for good. Only the link is kept. When nothing
    answers at all (reddit refusing the API, the page unreachable) that says
    nothing about the article, so ArticleUnreachable is raised and the stored
    copy stays as it was, unless ``wipe_if_unreachable`` says the reader has
    already decided the content is gone: then only the link is kept.
    """
    blank = ItemLoose(url=item.url)
    if backend.enrich:
        reddit_item = ingest_reddit_item(item)
        scraped = [
            reddit_item,
            ingest_open_graph_item(item),
            ingest_mercury_item(item),
        ]
        # For a reddit post only reddit's own answer can say whether the post
        # (and its picture) still exists: the page itself goes on offering
        # the old preview to anything that isn't the API. Rebuilding from that
        # alone would bring a deleted post's picture straight back, so when
        # reddit doesn't answer, that counts as nothing answering.
        answered = (
            reddit_item is not None
            if is_reddit_post(str(item.url))
            else any(scraped)
        )
        if answered:
            fresh = ItemLoose.merge_instances(items=[s for s in scraped if s])
            _replace_with_fresh_pictures(fresh, blank, reddit_item, scraped)
        elif wipe_if_unreachable:
            fresh = blank
        else:
            raise ArticleUnreachable(_UNREACHABLE)
    else:
        fresh = backend.enrich_item(blank)
        if fresh is None:
            if not wipe_if_unreachable:
                raise ArticleUnreachable(_UNREACHABLE)
            fresh = blank
    # the hostname is what every backend files an article under, and it comes
    # from the link, which is kept
    fresh.domain = urlparse(str(item.url)).netloc or fresh.domain
    # The model's sanitizer turns a missing body into the text "None", which
    # a card would then show as the article. An empty body is what is meant.
    if fresh.content in (None, "None"):
        fresh.content = ""
    fresh.embeddings = None
    fresh.image_embeddings = None
    return fresh


def _rescrape_item(
    item: ItemLoose, backend, fresh: bool = False, wipe_if_unreachable: bool = False
) -> tuple:
    """Re-run one stored item's scrapers and re-embed it, persisting whatever
    changed. Returns whether anything changed, and the (user_hash, feed_hash)
    pairs whose models trained on the item's old features and should retrain.

    With ``fresh`` the stored copy is thrown away rather than added to: the
    article is rebuilt only from what the scrapers find now (see
    _collect_fresh), every embedding is recomputed, and every feed carrying
    the article is returned for re-ranking, not only the ones that voted.
    """
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)
    image_embed_host = config.get("IMAGE_EMBED_HOST", None)
    image_embed_model = config.get("IMAGE_EMBED_MODEL")

    before = {f: getattr(item, f) for f in _RESCRAPE_FIELDS}
    picture_before = item.embeddable_image_url

    if fresh:
        merged = _collect_fresh(item, backend, wipe_if_unreachable)
    elif backend.enrich:
        reddit_item = ingest_reddit_item(item)
        scraped = [
            reddit_item,
            ingest_open_graph_item(item),
            ingest_mercury_item(item),
        ]
        merged = ItemLoose.merge_instances(items=[item, *scraped])
        _replace_with_fresh_pictures(merged, item, reddit_item, scraped)
    else:
        # the generic scrapers have nothing to offer a backend that
        # says so, and the sites it reaches refuse them anyway
        merged = ItemLoose(**item.dict())

    if not fresh:
        # merge_instances doesn't carry embeddings over; keep the existing
        # ones so a re-scrape never drops them. Copied rather than shared:
        # add_embedding mutates the dict in place, so handing `merged` the
        # same object would also mutate `item` and leave the two comparing
        # equal — a freshly computed embedding would then look like "no
        # change" and never get written back.
        merged.embeddings = dict(item.embeddings) if item.embeddings else None
        merged.image_embeddings = (
            dict(item.image_embeddings) if item.image_embeddings else None
        )

        # a re-collect is the one other time a backend gets to top an item
        # up, which is how items stored before it could do so get their
        # pictures
        merged = backend.enrich_item(merged) or merged

    after = {f: getattr(merged, f) for f in _RESCRAPE_FIELDS}
    text_changed = any(after[f] != before[f] for f in _EMBEDDING_TEXT_FIELDS)
    # Compared as the picture the item shows rather than as image_url: with
    # no image_url the card and the recommender both fall back to the first
    # image in the content, so a re-scrape that swaps the content out from
    # under an unset image_url changes the picture just as much.
    # Starting fresh counts as a new picture even when the URL is the same:
    # the old vectors and retry history are exactly what is being thrown out.
    picture_changed = fresh or merged.embeddable_image_url != picture_before

    if text_changed:
        # Every stored text vector describes the old text, including any left
        # over from an earlier embedding model: the recommender reads whichever
        # vector comes first, so a stale one would go on standing in for the
        # article. They go, and the current model's is recomputed below. If
        # that fails the article has no text vector until the next ingest pass
        # fills it in, which is better than being scored on words it no
        # longer says.
        merged.embeddings = None

    if (text_changed or fresh) and embedding_model is not None:
        try:
            merged.add_embedding(model_name=embedding_model, force_refresh=True)
        except Exception as e:
            logging.error(f"Error re-embedding item {item.url}: {e}")

    if picture_changed:
        # a re-scrape that turns up a different picture clears the old
        # one's failure history: those failures say nothing about the new
        # URL, and an item that had exhausted its retries would otherwise
        # stay out of the backfill queue forever
        reset_image_embed_attempts(item.url_hash)
        # Every stored image vector describes the old picture. Keeping one
        # would have the vote model go on scoring a picture the article no
        # longer shows (a deleted post's, say), so they go; the new picture,
        # if there is one, is embedded below or by the backfill.
        merged.image_embeddings = None

    picture = merged.embeddable_image_url
    if picture is None:
        # no picture, so no image vector of any model applies
        merged.image_embeddings = None

    image_failure = None
    if picture is not None and image_embed_host is not None:
        image_failure = _refresh_image_embedding(
            merged, picture, image_embed_model, picture_changed
        )

    embedding_changed = (
        merged.embeddings != item.embeddings
        or merged.image_embeddings != item.image_embeddings
    )

    if fresh:
        # whatever the old row held is being wiped, so it is always written
        # back, and the similarity graph re-places it below
        embedding_changed = True
    elif after == before and not embedding_changed:
        if image_failure is not None:
            _record_rescrape_image_failure(item.url_hash, image_failure)
        return False, set()  # nothing changed, leave the row untouched

    merged.update()  # persist (overwrites the existing row)

    if image_failure is not None:
        # after the write, so the failure is filed against the row as it now
        # stands rather than overwritten by it
        _record_rescrape_image_failure(item.url_hash, image_failure)

    if embedding_changed:
        # The similarity graph's links, and the duplicate grouping read out of
        # them, were all measured against the vector this article just stopped
        # having. Queue it to be placed again; the re-walk cooldown is about
        # links going stale with age and would not notice this on its own.
        from neighbors.graph import mark_relink_needed

        mark_relink_needed(item.url_hash)

        # Every feed's score for the article was worked out from the vectors
        # it just lost, voted on or not, so every feed carrying it rescores.
        return True, _feeds_carrying(item.url_hash)

    # a changed, voted-on item means the models that trained on its old
    # features are now stale — those feeds should retrain
    return True, _feeds_with_votes_on(item.url_hash)


def _refresh_image_embedding(
    merged: ItemLoose, picture: str, model_name: str, picture_changed: bool
) -> Optional[ImageEmbedError]:
    """Bring ``merged``'s image vector in line with the picture it shows now.

    A new picture, or one that never got a vector (the image host was down,
    rate-limiting us, or refusing the request), is embedded; a re-scrape is
    the one chance to retry that which no amount of unchanged re-scraping
    would otherwise get.

    A picture that is the same as before and already embedded is fetched
    once to check it is still there. The link staying put says nothing about
    the picture behind it: an upload its author deleted keeps its URL and
    answers 404. When every candidate URL says it is gone, the old vector is
    dropped, since it describes a picture nobody can see any more. Anything
    else (a 403, a timeout) is the kind of thing that fixes itself, so the
    vector stays.

    Returns the failure, if any, for the caller to record once the row is
    written.
    """
    embedded = model_name in (merged.image_embeddings or {})
    if picture_changed or not embedded:
        # copied first: the dict may still be the stored item's, and filling
        # it in place would make the two compare equal
        merged.image_embeddings = dict(merged.image_embeddings or {})
        try:
            failure = merged.add_image_embedding(
                model_name=model_name, force_refresh=picture_changed
            )
        except Exception as e:
            logging.error(f"Error re-embedding image {merged.url}: {e}")
            failure = None
        if not merged.image_embeddings:
            merged.image_embeddings = None
        return failure

    try:
        fetch_image_base64(picture)
    except ImageEmbedError as e:
        if not e.image_is_missing:
            return None
        logging.info(f"Picture for {merged.url} is gone, dropping its vector: {e}")
        merged.image_embeddings = None
        return e
    return None


def _record_rescrape_image_failure(url_hash: str, error: ImageEmbedError) -> None:
    """File a re-scrape's failed picture the way the backfill would, so the
    backfill backs off from it, and a 410 marks the picture gone for the
    recommender straight away instead of on the backfill's next pass."""
    try:
        record_image_embed_failure(
            url_hash,
            str(error),
            image_gone=error.image_is_gone,
            image_missing=error.image_is_missing,
        )
    except Exception as e:
        logging.error(f"Error recording image failure for {url_hash}: {e}")


def rerank_feeds(feeds: set) -> None:
    """Retrain the feeds a re-scrape left stale."""
    from ranking.engine import rank_feed  # local import avoids an import cycle

    for user_hash, feed_hash in feeds:
        feed = Feed.read(user_hash=user_hash, name_hash=feed_hash)
        if feed is None:
            continue
        try:
            rank_feed(feed)
        except Exception as e:
            logging.exception(
                f"Re-ranking feed {feed.name} after re-scrape failed: {e}"
            )


def rescrape_source(source: Source) -> None:
    """Re-scrape a source's existing items for content, images, and preview
    media, and regenerate embeddings, WITHOUT re-fetching the RSS feed.

    Each item's scrapers (reddit / open graph / mercury) are re-run and merged
    over the stored item, so gaps get backfilled and better content wins. The
    picture follows the page as it is now (see _replace_with_fresh_pictures),
    so a post that has been taken down stops showing its old preview. When an
    item's re-collected data actually changed and the item carries a vote, the
    affected feeds are re-ranked so their models retrain on the fresh features.
    """
    backend = get_backend(source.kind)
    feeds_to_rerank: set = set()

    for item in source.query_items():
        try:
            _, stale = _rescrape_item(item, backend)
            feeds_to_rerank |= stale
        except IngestError as e:
            logging.warning(f"Re-scrape of {item.url}: {e}")
        except Exception as e:
            logging.exception(f"Re-scrape of item {item.url} failed: {e}")

    rerank_feeds(feeds_to_rerank)

    logging.info(
        f"Re-scraped source '{source.name}': {len(feeds_to_rerank)} feed(s) retrained"
    )


def rescrape_item(
    item: ItemLoose,
    source: Source,
    fresh: bool = False,
    wipe_if_unreachable: bool = False,
) -> tuple:
    """Re-scrape one article now, the way its source's re-scrape would.

    Returns whether anything about the article changed, and the feeds whose
    models are now stale. Retraining is left to the caller: it takes far
    longer than the scrape, and someone waiting on the answer only needs the
    latter. ``fresh`` wipes the stored copy and rebuilds it from the site
    instead of adding to it (see _rescrape_item), and raises
    ArticleUnreachable when nothing answers unless ``wipe_if_unreachable``.
    """
    changed, stale = _rescrape_item(
        item,
        get_backend(source.kind),
        fresh=fresh,
        wipe_if_unreachable=wipe_if_unreachable,
    )
    logging.info(
        f"Re-scraped {item.url}: "
        + (f"changed, {len(stale)} feed(s) to retrain" if changed else "no change")
    )
    return changed, stale


def download_embedding_model_job() -> None:
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)

    if embedding_model is None:
        return

    ollama = get_ollama_connection()

    models = ollama.list()
    if embedding_model not in models:
        ollama.pull(embedding_model)


def _image_is_gone(error: ImageEmbedError, missed_before: bool) -> bool:
    """Whether to stop asking for this picture entirely.

    A 410 is the host saying the resource is gone, which it is not going to
    take back: believe it the first time. A 404 usually means the same thing --
    an expired signed preview, a deleted upload -- but is also what a CDN says
    mid-deploy, so it gets one more attempt before we treat it as final.

    ``missed_before`` is that first strike, and it comes from the item's own
    ``image_missing_at`` rather than from its attempt count: the manual retry
    resets the attempts, so counting strikes there meant a 404 never reached
    two and was fetched again every single pass, forever.

    Everything else keeps its full budget of retries: a 403, a timeout or a
    refusal page is the kind of thing that fixes itself.
    """
    if error.image_is_gone:
        return True
    return error.image_is_missing and missed_before


def _backfill_one_image(row: dict) -> tuple:
    """Embed one candidate row's preview image.

    Returns ``(embedding_or_None, error_or_None, image_gone, image_missing)``:
    the third says the picture is gone for good rather than failing for now,
    the fourth that it answered 404 and has used up its one benefit of the
    doubt. Runs on a worker thread and takes no database connection of its own
    — results are written by the caller — so a wide fan-out can't drain the
    pool.
    """
    try:
        image_url = embeddable_image_url(row["image_url"], row["content"], row["url"])
        if not image_url:
            # the candidate query matches "<img" anywhere in the content, which
            # a sanitized body can carry without a usable src; count it as a
            # failure so the row backs off instead of being re-picked each pass
            return None, "no embeddable image url", False, False
        return embed_image(image_url), None, False, False
    except ImageEmbedError as e:
        gone = _image_is_gone(e, row.get("image_missing_at") is not None)
        return None, str(e), gone, e.image_is_missing
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", False, False


def _failure_summary(reasons: Counter) -> str:
    """The handful of reasons that account for a run's failures.

    One log line per failed image would bury everything else at this batch size,
    but "1,431 failed" on its own says nothing about whether the image hosts are
    rate-limiting us or the URLs are simply dead — which is the first thing
    worth knowing when coverage stops climbing.
    """
    return ", ".join(f"{count}x {reason}" for reason, count in reasons.most_common(3))


def _failure_reason(error: str) -> str:
    """Collapse a failure to something worth counting across a run.

    The stored error names the URLs it tried, which is exactly what makes every
    message unique and useless to tally; the parenthesised detail at the end is
    the part that repeats.
    """
    detail = error.rsplit("(", 1)[-1].rstrip(")").strip()
    return detail or error


def backfill_image_embeddings_job() -> None:
    """Embed the preview image of stored items missing an embedding for the
    current CLIP model.

    New items are embedded at ingest time, so this catches everything scraped
    before the service existed (or before the model changed) — plus every item
    whose image download failed at the time. Image hosts fail transiently (rate
    limits, timeouts, CDN hiccups), so a failed item is worth retrying; but
    plenty of them fail *permanently* — expired reddit signed URLs, deleted
    images, hosts that answer a scraper with HTML. Each attempt is therefore
    recorded on the row, and a failing item backs off exponentially before it is
    offered again, then drops out of the queue once it has burned through its
    attempts. Without that, a batch of permanently broken images is re-selected
    and re-failed on every single pass and the backlog behind them is never
    reached.

    Items are fetched a few at a time: the work is almost entirely waiting on
    image hosts, and a serial loop over a five-figure backlog never catches up.

    No-op when the service isn't configured.
    """
    if config.get("IMAGE_EMBED_HOST", None) is None:
        return

    model_name = config.get("IMAGE_EMBED_MODEL")
    rows = image_embed_backfill_candidates(
        model_name=model_name,
        limit=config.get_int("IMAGE_EMBED_BACKFILL_BATCH_SIZE"),
        max_attempts=config.get_int("IMAGE_EMBED_MAX_ATTEMPTS"),
        retry_minutes=config.get_float("IMAGE_EMBED_RETRY_MINUTES"),
        max_retry_minutes=config.get_float("IMAGE_EMBED_MAX_RETRY_MINUTES"),
    )

    if not rows:
        return

    concurrency = max(1, config.get_int("IMAGE_EMBED_BACKFILL_CONCURRENCY"))
    logging.info(
        f"Backfilling image embeddings for {len(rows)} item(s) "
        f"({concurrency} at a time)..."
    )
    # Recorded only from here on: a pass with nothing to do returned above, and
    # a timeline of empty passes every quarter of an hour would bury the ones
    # that did work.
    run_id = start_run(KIND_IMAGE_EMBED_BACKFILL)

    embedded = 0
    retired = 0
    reasons: Counter = Counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_backfill_one_image, row): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            embedding, error, image_gone, image_missing = future.result()
            try:
                # both writes are dropped if a re-scrape changed the picture
                # while this pass was fetching the old one
                if embedding is not None:
                    embedded += save_image_embedding(
                        row["url_hash"],
                        model_name,
                        embedding,
                        image_url=row["image_url"],
                        content=row["content"],
                    )
                else:
                    record_image_embed_failure(
                        row["url_hash"],
                        error,
                        image_gone,
                        image_missing,
                        image_url=row["image_url"],
                        content=row["content"],
                    )
                    reasons[_failure_reason(error)] += 1
                    retired += image_gone
            except Exception as e:
                logging.error(
                    f"Error recording image embedding result for {row['url']}: {e}"
                )

    failed = sum(reasons.values())
    summary = (
        f"{embedded} embedded, {failed} failed"
        # Retired items are the ones that will never be tried again, so the
        # line says how many rather than leaving the count to drift silently.
        + (f", {retired} gone for good" if retired else "")
        + (f" ({_failure_summary(reasons)})" if failed else "")
    )
    logging.info(f"Image embedding backfill complete: {summary}")
    # A pass that embedded nothing at all is the interesting failure -- every
    # picture in the batch was unreachable -- so it is recorded as one.
    finish_run(
        run_id,
        STATUS_ERROR if embedded == 0 and failed else STATUS_OK,
        summary,
    )
