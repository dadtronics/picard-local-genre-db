# SPDX-License-Identifier: GPL-2.0-or-later
"""Saving decisions from Picard (right-click action) into taxonomy.db."""

import sqlite3
import sys
import types
from unittest import mock

import pytest
from conftest import ARTIST_MBID, RELEASE_MBID, RG_MBID

NEW_RG = '44444444-4444-4444-4444-444444444444'


def row(db, table, column, mbid):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(f'SELECT * FROM {table} WHERE {column} = ?', (mbid,)).fetchone()
    finally:
        con.close()


def test_save_new_release_group_decision(plugin, db, settings, plugin_dir):
    result = plugin.save_decision(str(db), 'release_group', NEW_RG, 'electronic', 'techno; club/dance')
    assert result == {'scope': 'release_group', 'mbid': NEW_RG,
                      'genres': 'Electronic', 'styles': 'Techno; Club/Dance'}
    saved = row(db, 'release_group_decision', 'release_group_mbid', NEW_RG)
    assert (saved['normalized_genre_id'], saved['locked'], saved['notes']) == (1, 1, 'Saved from Picard')

    md = {'musicbrainz_releasegroupid': NEW_RG}
    assert plugin.process_metadata(md, 'release', settings, str(plugin_dir))['source'] == 'release_group'
    assert md['grouping'] == ['Techno', 'Club/Dance']


def test_genre_aliases_resolve_and_dedupe(plugin, db):
    result = plugin.save_decision(str(db), 'release', RELEASE_MBID, 'Acid Jazz; Jazz, rock', '')
    assert result['genres'] == 'Jazz; Pop/Rock'
    assert row(db, 'release_decision', 'release_mbid', RELEASE_MBID)['normalized_genre_id'] == 3


def test_builtin_alias(plugin, db):
    assert plugin.save_decision(str(db), 'release', RELEASE_MBID, 'Electronica', '')['genres'] == 'Electronic'


def test_update_existing_decision(plugin, db):
    plugin.save_decision(str(db), 'release_group', RG_MBID, 'Jazz', 'Acid Jazz')
    saved = row(db, 'release_group_decision', 'release_group_mbid', RG_MBID)
    assert (saved['genres_text'], saved['styles_text']) == ('Jazz', 'Acid Jazz')


@pytest.mark.parametrize('genres, styles, message', [
    ('Shoegaze', '', 'unknown genre(s): Shoegaze'),
    ('Electronic', 'Hyperpop', 'unknown style(s): Hyperpop'),
    ('', 'Techno', 'no genre'),
])
def test_unknown_values_are_refused(plugin, db, genres, styles, message):
    with pytest.raises(plugin.TaxonomyError, match=message.replace('(', r'\(').replace(')', r'\)')):
        plugin.save_decision(str(db), 'release_group', NEW_RG, genres, styles)
    assert row(db, 'release_group_decision', 'release_group_mbid', NEW_RG) is None


def test_missing_mbid_or_db(plugin, db, tmp_path):
    with pytest.raises(plugin.TaxonomyError, match='no release group MBID'):
        plugin.save_decision(str(db), 'release_group', '', 'Jazz', '')
    with pytest.raises(plugin.TaxonomyError, match='Database not found'):
        plugin.save_decision(str(tmp_path / 'nope.db'), 'release_group', NEW_RG, 'Jazz', '')


def test_decision_target(plugin):
    ids = {'release_group': 'rg', 'release': 'rel', 'album_artists': ['a1', 'a2'], 'track_artists': ['t1']}
    assert plugin.decision_target(ids, 'release_group') == 'rg'
    assert plugin.decision_target(ids, 'artist') == 'a1'
    assert plugin.decision_target({'album_artists': [], 'track_artists': ['t1']}, 'artist') == 't1'


# -- the context-menu action (fake Picard, no Qt event loop) ---------------------

def test_action_saves_selected_albums(plugin, db, settings, monkeypatch):
    class Album:
        def __init__(self, metadata):
            self.metadata = metadata

    api_module = types.ModuleType('picard.plugin3.api')
    api_module.Album = Album
    api_module.BaseAction = type('BaseAction', (), {})
    qt = types.ModuleType('PyQt6')
    qt.QtWidgets = mock.MagicMock()
    for name, module in {
        'PyQt6': qt, 'PyQt6.QtWidgets': qt.QtWidgets,
        'picard': types.ModuleType('picard'), 'picard.plugin3': types.ModuleType('picard.plugin3'),
        'picard.plugin3.api': api_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop('local_genre_db.actions', None)
    from local_genre_db.actions import SaveGenreAction

    action = SaveGenreAction()
    action.api = mock.MagicMock()
    action.api.plugin_config = {'db_path': settings.db_path}
    action.ask_scope = lambda count: 'artist'
    reports = []
    action.report = lambda saved, failed: reports.append((saved, failed))

    good = Album({'album': 'Good', 'musicbrainz_albumartistid': ARTIST_MBID, 'genre': ['Jazz'],
                  'grouping': ['Acid Jazz']})
    bad = Album({'album': 'Bad', 'musicbrainz_albumartistid': 'x', 'genre': ['Shoegaze']})
    action.callback([good, object(), bad])

    saved, failed = reports[0]
    assert saved == ['Good: Jazz / Acid Jazz']
    assert len(failed) == 1 and failed[0].startswith('Bad: Not saved: unknown genre(s): Shoegaze')
    assert row(db, 'artist_decision', 'artist_mbid', ARTIST_MBID)['genres_text'] == 'Jazz'
