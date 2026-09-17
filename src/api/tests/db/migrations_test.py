"""The rules Flyway enforces at boot, checked here instead.

Flyway validates the migration tree against the schema history of whatever
database it is pointed at, which means a mistake here is only found when a
real install refuses to start. These are the checks that do not need a
database to make.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"
_NAME = re.compile(r"^V(\d+)__[a-z0-9_]+\.sql$")


def _versions() -> dict:
    found = {}
    for path in sorted(MIGRATIONS.glob("V*.sql")):
        match = _NAME.match(path.name)
        assert match, f"{path.name} is not a valid Flyway migration name"
        found.setdefault(int(match.group(1)), []).append(path.name)
    return found


def test_every_migration_version_is_used_once():
    """Two migrations claiming one version is the mistake two people adding a
    migration at the same time make, and Flyway refuses to run at all when it
    happens."""
    clashes = {v: names for v, names in _versions().items() if len(names) > 1}
    assert not clashes, f"more than one migration per version: {clashes}"


def test_the_migrations_are_a_contiguous_run_from_the_known_gap():
    """A missing version is usually a file that did not get committed. V15 is
    the one deliberate gap: it was never released, and filling it now would
    break every install that has already migrated past it."""
    versions = sorted(_versions())
    expected = [v for v in range(1, max(versions) + 1) if v != 15]

    assert versions == expected, f"unexpected gaps: {sorted(set(expected) - set(versions))}"
