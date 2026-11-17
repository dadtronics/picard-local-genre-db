# SPDX-License-Identifier: GPL-2.0-or-later
"""Test fixtures.

The plugin's core (``__init__.py``) only uses the standard library, so it is
imported directly from a copy placed in a fake Picard ``Plugins`` folder. The
Qt modules (options.py, actions.py) are not imported here.
"""

import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Subset of picard-genre-db's schema.sql that the plugin reads and writes.
SCHEMA = '''
CREATE TABLE canonical_genre (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE canonical_style (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    genre_id INTEGER NOT NULL,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE alias_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL DEFAULT 'manual',
    raw_value TEXT NOT NULL COLLATE NOCASE,
    normalized_genre_id INTEGER,
    normalized_style_id INTEGER,
    notes TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    UNIQUE(source_name, raw_value)
);
''' + ''.join(
    f'''
CREATE TABLE {table} (
    {column} TEXT PRIMARY KEY,
    normalized_genre_id INTEGER NOT NULL,
    genres_text TEXT NOT NULL DEFAULT '',
    styles_text TEXT NOT NULL DEFAULT '',
    reviewed INTEGER NOT NULL DEFAULT 1,
    locked INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''
    for table, column in (
        ('artist_decision', 'artist_mbid'),
        ('release_decision', 'release_mbid'),
        ('release_group_decision', 'release_group_mbid'),
        ('recording_decision', 'recording_mbid'),
    )
)

RG_MBID = 'acddb85b-7889-45b5-bd96-49e5b22738b1'
RELEASE_MBID = '11111111-1111-1111-1111-111111111111'
ARTIST_MBID = '33333333-3333-3333-3333-333333333333'


def build_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany('INSERT INTO canonical_genre(id, name) VALUES (?, ?)', [
        (1, 'Electronic'), (2, 'Pop/Rock'), (3, 'Jazz'),
    ])
    con.executemany('INSERT INTO canonical_style(id, genre_id, name) VALUES (?, ?, ?)', [
        (1, 1, 'Club/Dance'), (2, 1, 'EDM'), (3, 1, 'Techno'), (4, 3, 'Acid Jazz'),
        (5, 2, 'Indie Rock'),
    ])
    con.executemany(
        'INSERT INTO alias_mapping(raw_value, normalized_genre_id, normalized_style_id) VALUES (?, ?, ?)',
        [('acid jazz', 3, 4), ('techno', 1, 3), ('rock', 2, None)],
    )
    con.execute(
        "INSERT INTO release_group_decision(release_group_mbid, normalized_genre_id, genres_text, styles_text) "
        "VALUES (?, 1, 'Electronic', 'Club/Dance; EDM')", (RG_MBID,))
    con.execute(
        "INSERT INTO artist_decision(artist_mbid, normalized_genre_id, genres_text, styles_text) "
        "VALUES (?, 2, 'Pop/Rock', 'Indie Rock')", (ARTIST_MBID,))
    con.commit()
    con.close()
    return path


def load_plugin(plugin_dir: Path):
    """Import the plugin package from plugin_dir as 'local_genre_db'."""
    for name in list(sys.modules):
        if name == 'local_genre_db' or name.startswith('local_genre_db.'):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        'local_genre_db', plugin_dir / '__init__.py', submodule_search_locations=[str(plugin_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['local_genre_db'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugins_dir(tmp_path, monkeypatch):
    """A fake Picard Plugins folder with the plugin installed as a checkout."""
    for env in ('PICARD_TAXONOMY_DB', 'PICARD_TAXONOMY_JSON'):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    root = tmp_path / 'Plugins'
    plugin = root / 'local_genre_db_ec8d05fd-2dc3-430a-a995-bb0b9b076b02'
    plugin.mkdir(parents=True)
    for source in REPO.glob('*.py'):
        shutil.copy(source, plugin / source.name)
    return root


@pytest.fixture
def plugin_dir(plugins_dir):
    return next(plugins_dir.iterdir())


@pytest.fixture
def plugin(plugin_dir):
    return load_plugin(plugin_dir)


@pytest.fixture
def db(tmp_path):
    return build_db(tmp_path / 'taxonomy.db')


@pytest.fixture
def settings(plugin, db):
    return plugin.Settings(db_path=str(db))
