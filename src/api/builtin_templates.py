import logging

from db.source_template import SourceTemplate, SourceTemplateParameter


def _reddit_sort_param() -> SourceTemplateParameter:
    return SourceTemplateParameter(
        name="Sort",
        title="Sort order",
        required=False,
        type="select",
        default="hot",
        options={"hot": "Hot", "new": "New", "top": "Top", "rising": "Rising"},
    )


BUILTIN_TEMPLATES = [
    SourceTemplate(
        name="Reddit Subreddit",
        url="https://www.reddit.com",
        url_template="https://www.reddit.com/r/{subreddit}/{sort}.rss",
        description=(
            "Posts from a subreddit via Reddit's native RSS feed. "
            "Fetches reddit.com directly, without rss-bridge, which avoids "
            "the API rate limits that block RedditBridge."
        ),
        parameters={
            "subreddit": SourceTemplateParameter(
                name="Subreddit",
                title="Subreddit name (without r/)",
                required=True,
                type="text",
                example="selfhosted",
            ),
            "sort": _reddit_sort_param(),
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
