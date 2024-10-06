import pytest
import os

from config import config, KNOWN_CONFIG_VALUES, DEFAULT_CONFIG, ConfigError

# @pytest.fixture(autouse=True)
# def config_with_test_values():


def test_unknown_config_key():
    with pytest.raises(ConfigError):
        config.get("UNKNOWN_CONFIG_KEY")


def test_get_unset_known_config_key():
    # add a key to the known config values that is not in the default config
    KNOWN_CONFIG_VALUES.append("TEST_CONFIG_KEY")
    with pytest.raises(ConfigError):
        config.get("TEST_CONFIG_KEY")


def test_get_default_config_key():
    print(config.config)
    for k in DEFAULT_CONFIG:
        print(k)
        if k in config.config.keys():
            assert config.get(k) == config.config[k]
        elif os.getenv(k) is not None:
            assert config.get(k) == os.getenv(k)
        else:
            assert config.get(k) == DEFAULT_CONFIG[k]


def test_set_config_key():
    k = "TEST_CONFIG_KEY"
    KNOWN_CONFIG_VALUES.append(k)
    DEFAULT_CONFIG[k] = "default"
    config.config.pop(k, None)
    assert config.get(k) == DEFAULT_CONFIG[k]
    config.set(k, "set")
    assert config.get(k) == "set"


def test_return_passed_default():
    k = "TEST_CONFIG_KEY"
    KNOWN_CONFIG_VALUES.append(k)
    config.config.pop(k, None)
    assert config.get(k, "default") == "default"


def test_set_unknown_config_key():
    with pytest.raises(ConfigError):
        config.set("UNKNOWN_CONFIG_KEY", "value")
