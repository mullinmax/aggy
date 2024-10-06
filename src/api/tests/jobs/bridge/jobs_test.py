import pytest
import logging

from jobs.bridge.jobs import rss_bridge_get_templates_job
from config import config


def test_bridge_get_templates_job(caplog):
    # run the job and check the logs
    with caplog.at_level(logging.INFO):
        rss_bridge_get_templates_job()

    assert "Total rss-bridge templates created:" in caplog.text
    assert "rss-bridge template created:" in caplog.text


@pytest.fixture
def altered_config():
    org_host = config.get("RSS_BRIDGE_HOST")
    config.set("RSS_BRIDGE_HOST", None)
    yield
    config.set("RSS_BRIDGE_HOST", org_host)


def test_with_bad_bridge_host(caplog, altered_config):
    # set the host to None
    config.set("RSS_BRIDGE_HOST", None)

    # run the job and check the logs
    with caplog.at_level(logging.WARNING):
        rss_bridge_get_templates_job()

    assert "RSS_BRIDGE_HOST is not set in the config" in caplog.text
