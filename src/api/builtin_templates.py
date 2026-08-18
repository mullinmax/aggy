import logging

from config import config
from db.source_template import SourceTemplate, SourceTemplateParameter


BUILTIN_TEMPLATES = [
    SourceTemplate(
        name="Reddit Subreddit",
        url="https://www.reddit.com",
        # Locked to "top today": reddit rate-limits hard, so we check each
        # subreddit only ~twice a day and pull the day's top posts, which
        # captures nearly everything worth surfacing without other sorts.
        url_template="https://www.reddit.com/r/{subreddit}/top.rss?t=day",
        description=(
            "The day's top posts from a subreddit via Reddit's native RSS "
            "feed. Fetches reddit.com directly, without rss-bridge, which "
            "avoids the API rate limits that block RedditBridge."
        ),
        parameters={
            "subreddit": SourceTemplateParameter(
                name="Subreddit",
                title="Subreddit name (without r/)",
                required=True,
                type="text",
                example="selfhosted",
            ),
        },
    ),
    SourceTemplate(
        name="YouTube Channel",
        url="https://www.youtube.com",
        url_template="https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
        description=(
            "A YouTube channel's latest uploads via YouTube's native RSS "
            "feed. Needs the channel ID (starts with UC); the bulk importer "
            "can resolve @handles and channel URLs to IDs for you."
        ),
        parameters={
            "channel_id": SourceTemplateParameter(
                name="Channel ID",
                title="Channel ID (starts with UC)",
                required=True,
                type="text",
                example="UCXuqSBlHAE6Xw-yeJA0Tunw",
            ),
        },
    ),
    SourceTemplate(
        name="Bluesky User",
        url="https://bsky.app",
        url_template="https://bsky.app/profile/{handle}/rss",
        description=(
            "Posts from a Bluesky account via Bluesky's native RSS feed, "
            "fetched directly without rss-bridge."
        ),
        parameters={
            "handle": SourceTemplateParameter(
                name="Handle",
                title="Bluesky handle (without @)",
                required=True,
                type="text",
                example="jay.bsky.team",
            ),
        },
    ),
    SourceTemplate(
        name="Reddit User",
        url="https://www.reddit.com",
        url_template="https://www.reddit.com/user/{username}/.rss",
        description=(
            "Posts and comments from a Reddit user via Reddit's native RSS "
            "feed, fetched directly without rss-bridge."
        ),
        parameters={
            "username": SourceTemplateParameter(
                name="Username",
                title="Reddit username (without u/)",
                required=True,
                type="text",
                example="spez",
            ),
        },
    ),
]


def ytdlp_template() -> SourceTemplate:
    return SourceTemplate(
        name="Video Site Listing",
        url="https://github.com/yt-dlp/yt-dlp",
        kind="ytdlp",
        url_template="{url}",
        description=(
            "Any channel, user, playlist, or search-results page on a video "
            "site, for the very many sites yt-dlp supports. Reads metadata "
            "only — nothing is downloaded, and playback streams from the site "
            "itself. Use this for sites that publish no feed, paginate their "
            "listings, or hide them behind an age or consent gate."
        ),
        parameters={
            "url": SourceTemplateParameter(
                name="Listing URL",
                title=(
                    "URL of a channel, user, playlist, or search-results page "
                    "— not a single item"
                ),
                required=True,
                type="text",
                quote="none",
                example="https://www.youtube.com/@Computerphile/videos",
            ),
        },
    )


def rsshub_template() -> SourceTemplate:
    return SourceTemplate(
        name="RSSHub Route",
        url="https://docs.rsshub.app",
        url_template="http://{host}:{port}/{{route}}".format(
            host=config.get("RSSHUB_HOST", "aggy-rsshub"),
            port=config.get("RSSHUB_PORT"),
        ),
        description=(
            "Any route on the bundled RSSHub instance, given as a path. Browse "
            "the routes at docs.rsshub.app; the catalog importer also adds them "
            "here as individual templates."
        ),
        parameters={
            "route": SourceTemplateParameter(
                name="Route",
                title="Route path, without the leading slash",
                required=True,
                type="text",
                quote="path",
                example="github/issue/RSS-Bridge/rss-bridge",
            ),
        },
    )


# Templates that only work when their backing service is running: added when
# it's configured, removed when it isn't, so the catalog never offers a source
# that could not possibly ingest.
OPTIONAL_TEMPLATES = (
    ("YTDLP_HOST", ytdlp_template),
    ("RSSHUB_HOST", rsshub_template),
)


def optional_templates() -> list:
    """The optional templates whose service is configured."""
    return [
        build()
        for host_key, build in OPTIONAL_TEMPLATES
        if config.get(host_key, None) is not None
    ]


def builtin_template(name: str) -> SourceTemplate:
    """Look up a built-in template by its (context-free) name."""
    for template in BUILTIN_TEMPLATES:
        if template.name == name:
            return template
    raise KeyError(f"No builtin template named {name}")


def create_builtin_source_templates() -> None:
    """Upsert Aggy's built-in (non-rss-bridge) source templates."""
    optional = optional_templates()

    for template in BUILTIN_TEMPLATES + optional:
        try:
            template.create()
            logging.info(f"builtin template created: {template.user_friendly_name}")
        except Exception as e:
            logging.error(
                f"Failed to create builtin template {template.user_friendly_name}: {e}"
            )

    # Drop templates for services that are no longer configured, so the
    # catalog can't offer a source that would fail on its first ingest.
    # Sources already built from them keep working.
    configured = {t.name_hash for t in optional}
    for _, build in OPTIONAL_TEMPLATES:
        template = build()
        if template.name_hash in configured:
            continue
        try:
            template.delete()
        except Exception as e:
            logging.error(
                f"Failed to drop unconfigured template "
                f"{template.user_friendly_name}: {e}"
            )
