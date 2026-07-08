import logging

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


def create_builtin_source_templates() -> None:
    """Upsert Aggy's built-in (non-rss-bridge) source templates."""
    for template in BUILTIN_TEMPLATES:
        try:
            template.create()
            logging.info(f"builtin template created: {template.user_friendly_name}")
        except Exception as e:
            logging.error(
                f"Failed to create builtin template {template.user_friendly_name}: {e}"
            )
