from __future__ import annotations

from ansiblaster.db import make_engine


def test_make_engine_creates_missing_parent_directory(tmp_path):
    """database.path's parent directory (e.g. /opt/ansiblaster) isn't guaranteed to exist --
    unlike ansible.artifacts_path, nothing else in the app creates it lazily, and SQLite
    itself won't create a missing directory for its db file. A bare checkout with no volume
    pre-created (see CLAUDE.md's Distribution section) must still start successfully.
    """
    database_path = tmp_path / "does" / "not" / "exist" / "ansiblaster.db"
    assert not database_path.parent.exists()

    engine = make_engine(str(database_path))

    assert database_path.parent.is_dir()
    engine.dispose()


def test_make_engine_tolerates_already_existing_parent_directory(tmp_path):
    database_path = tmp_path / "ansiblaster.db"

    engine = make_engine(str(database_path))

    assert database_path.parent.is_dir()
    engine.dispose()
