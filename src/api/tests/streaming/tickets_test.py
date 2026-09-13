"""The permission slip a `video` element carries in its URL."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from config import config
from streaming import tickets
from tests.testing_utils import build_api_request_args

URL = "https://cdn.example.com/v.mp4?sig=abc"


def test_a_ticket_says_which_url_for_which_user():
    ticket = tickets.mint(URL, "user-hash", "item-hash")
    claims = tickets.verify(ticket)

    assert claims["url"] == URL
    assert claims["user"] == "user-hash"
    assert claims["item"] == "item-hash"


def test_a_ticket_nobody_here_signed_is_refused():
    forged = jwt.encode({"url": URL}, "a-secret-this-server-has-never-heard-of", algorithm="HS256")

    with pytest.raises(tickets.InvalidTicket):
        tickets.verify(forged)


def test_an_expired_ticket_is_refused():
    stale = jwt.encode(
        {
            "url": URL,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        # reach for the same key the minter derives, without exporting it
        tickets._secret(),
        algorithm=tickets._algorithm(),
    )

    with pytest.raises(tickets.InvalidTicket, match="expired"):
        tickets.verify(stale)


def test_a_login_token_is_not_a_ticket(token):
    """Tickets ride in URLs, so they end up in histories, referers and access
    logs. Signing them with the login secret would make every one of those a
    session."""
    with pytest.raises(tickets.InvalidTicket):
        tickets.verify(token)


def test_a_ticket_is_not_a_login(client, existing_user):
    ticket = tickets.mint(URL, existing_user.name_hash, "item-hash")

    args = build_api_request_args(path="/auth/token_check", token=ticket)
    assert client.get(**args).status_code == 401


def test_the_derived_key_follows_the_secret():
    """Rotating the login secret has to invalidate outstanding tickets too."""
    ticket = tickets.mint(URL, "user-hash", "item-hash")
    original = config.get("JWT_SECRET")
    try:
        config.set("JWT_SECRET", "a-different-secret")
        with pytest.raises(tickets.InvalidTicket):
            tickets.verify(ticket)
    finally:
        config.set("JWT_SECRET", original)
