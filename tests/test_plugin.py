# SPDX-License-Identifier: GPL-2.0-or-later
import json
import os
import sqlite3
import tomllib
from pathlib import Path

from conftest import ARTIST_MBID, RELEASE_MBID, REPO, RG_MBID


def album_metadata(**extra):
    md = {'musicbrainz_releasegroupid': RG_MBID, 'musicbrainz_albumid': RELEASE_MBID, 'album': 'WukiWorld'}
    md.update(extra)
    return md


# -- finding the taxonomy ----------------------------------------------------

def test_path_from_settings_wins(plugin, plugin_dir, db, monkeypatch, tmp_path):
    monkeypatch.setenv('PICARD_TAXONOMY_DB', str(tmp_path / 'env.db'))
    (plugin_dir.parent / 'taxonomy_path.txt').write_text(str(tmp_path / 'pointer.db'))
    path, source = plugin.resolve_path('db', plugin.Settings(db_path=str(db)), str(plugin_dir))
    assert (path, source) == (str(db), 'settings')


def test_path_env_before_pointer_files(plugin, plugin_dir, monkeypatch, tmp_path):
    monkeypatch.setenv('PICARD_TAXONOMY_DB', str(tmp_path / 'env.db'))
    (plugin_dir.parent / 'taxonomy_path.txt').write_text(str(tmp_path / 'pointer.db'))
    path, source = plugin.resolve_path('db', plugin.Settings(), str(plugin_dir))
    assert path == str(tmp_path / 'env.db')
    assert source == 'env PICARD_TAXONOMY_DB'


def test_pointer_file_in_plugin_folder_then_parent(plugin, plugin_dir, tmp_path):
    (plugin_dir.parent / 'taxonomy_path.txt').write_text('﻿' + str(tmp_path / 'parent.db') + '\n')
    path, _ = plugin.resolve_path('db', plugin.Settings(), str(plugin_dir))
    assert path == str(tmp_path / 'parent.db')
    (plugin_dir / 'taxonomy_path.txt').write_text(str(tmp_path / 'own.db'))
    path, _ = plugin.resolve_path('db', plugin.Settings(), str(plugin_dir))
    assert path == str(tmp_path / 'own.db')


def test_default_path_is_home(plugin, plugin_dir, tmp_path):
    path, source = plugin.resolve_path('json', plugin.Settings(), str(plugin_dir))
    assert source == 'default'
    assert path == os.path.expanduser('~/taxonomy.json')


def test_settings_from_config_coerces_types(plugin):
    config = {'db_path': None, 'write_style_tag': 'true', 'learn_from_metadata': 'false'}
    settings = plugin.Settings.from_config(config)
    assert settings.db_path == ''
    assert settings.write_style_tag is True
    assert settings.learn_from_metadata is False
    assert settings.write_grouping_tag is True  # missing -> default


def test_describe_taxonomy(plugin, settings, plugin_dir):
    status = plugin.describe_taxonomy(settings, str(plugin_dir))
    assert '1 release groups' in status and '3 aliases' in status
    missing = plugin.describe_taxonomy(plugin.Settings(db_path='/nope.db', json_path='/nope.json'), str(plugin_dir))
    assert missing.startswith('Not found')


# -- lookups -------------------------------------------------------------------

def test_release_group_decision_applies(plugin, settings, plugin_dir):
    md = album_metadata(genre='Dance', grouping='Old')
    decision = plugin.process_metadata(md, 'release', settings, str(plugin_dir))
    assert decision['source'] == 'release_group'
    assert md['genre'] == ['Electronic']
    assert md['grouping'] == ['Club/Dance', 'EDM']


def test_release_beats_release_group(plugin, settings, db, plugin_dir):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO release_decision(release_mbid, normalized_genre_id, genres_text, styles_text) "
                "VALUES (?, 3, 'Jazz', 'Acid Jazz')", (RELEASE_MBID,))
    con.commit()
    con.close()
    md = album_metadata()
    assert plugin.process_metadata(md, 'release', settings, str(plugin_dir))['source'] == 'release'
    assert md['genre'] == ['Jazz']


def test_artist_decision_fallback(plugin, settings, plugin_dir):
    md = {'musicbrainz_albumartistid': ARTIST_MBID}
    decision = plugin.process_metadata(md, 'release', settings, str(plugin_dir))
    assert decision['source'] == 'artist'
    assert md['genre'] == ['Pop/Rock']


def test_alias_only_fills_blanks(plugin, settings, plugin_dir):
    md = {'genre': 'Techno', 'grouping': 'Keep Me'}
    decision = plugin.process_metadata(md, 'release', settings, str(plugin_dir))
    assert decision['source'] == 'alias'
    assert md['genre'] == 'Techno'
    assert md['grouping'] == 'Keep Me'


def test_decision_with_orphaned_genre_id_still_applies(plugin, settings, db, plugin_dir):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO recording_decision(recording_mbid, normalized_genre_id, genres_text, styles_text) "
                "VALUES ('rec-1', 999, 'Electronic', 'Techno')")
    con.commit()
    con.close()
    md = {'musicbrainz_recordingid': 'rec-1'}
    assert plugin.process_metadata(md, 'recording', settings, str(plugin_dir))['source'] == 'recording'
    assert md['grouping'] == ['Techno']


def test_json_fallback(plugin, plugin_dir, tmp_path):
    snapshot = {'release_group_decisions': {RG_MBID: {'genre': 'Electronic', 'styles': 'EDM'}}}
    json_path = tmp_path / 'taxonomy.json'
    json_path.write_text(json.dumps(snapshot))
    settings = plugin.Settings(db_path=str(tmp_path / 'missing.db'), json_path=str(json_path))
    md = album_metadata()
    assert plugin.process_metadata(md, 'release', settings, str(plugin_dir))['source'] == 'release_group'


def test_missing_taxonomy_is_a_no_op(plugin, plugin_dir, tmp_path):
    settings = plugin.Settings(db_path=str(tmp_path / 'no.db'), json_path=str(tmp_path / 'no.json'))
    md = album_metadata()
    assert plugin.process_metadata(md, 'release', settings, str(plugin_dir)) is None
    assert 'genre' not in md


def test_lookup_does_not_lock_or_modify_db(plugin, settings, db, plugin_dir):
    before = db.stat().st_mtime_ns
    plugin.process_metadata(album_metadata(), 'release', settings, str(plugin_dir))
    assert db.stat().st_mtime_ns == before


# -- pending decisions and the plugin folder --------------------------------

def test_pending_goes_to_plugins_folder_not_checkout(plugin, settings, plugin_dir):
    md = {'musicbrainz_albumartistid': 'unknown-artist', 'genre': 'Shoegaze', 'grouping': 'Dream Pop'}
    plugin.process_metadata(md, 'release', settings, str(plugin_dir))
    pending = plugin_dir.parent / 'local_genre_db_pending.jsonl'
    row = json.loads(pending.read_text().splitlines()[0])
    assert (row['scope'], row['mbid']) == ('artist', 'unknown-artist')
    # Picard refuses to update a checkout with untracked files.
    shipped = sorted(p.name for p in REPO.glob('*.py'))
    assert sorted(p.name for p in plugin_dir.iterdir() if p.name != '__pycache__') == shipped


def test_learning_can_be_disabled(plugin, db, plugin_dir):
    settings = plugin.Settings(db_path=str(db), learn_from_metadata=False)
    md = {'musicbrainz_albumartistid': 'unknown-artist', 'genre': 'Shoegaze', 'grouping': 'Dream Pop'}
    plugin.process_metadata(md, 'release', settings, str(plugin_dir))
    assert not (plugin_dir.parent / 'local_genre_db_pending.jsonl').exists()


# -- packaging -------------------------------------------------------------------

def test_manifest():
    manifest = tomllib.loads((REPO / 'MANIFEST.toml').read_text(encoding='utf-8'))
    assert manifest['uuid'] == 'ec8d05fd-2dc3-430a-a995-bb0b9b076b02'
    assert manifest['api'] == ['3.0']
    assert manifest['license'] == 'GPL-2.0-or-later'


def test_runtime_files_are_gitignored():
    ignored = Path(REPO / '.gitignore').read_text().splitlines()
    for name in ('local_genre_db_pending.jsonl', 'taxonomy_path.txt', 'taxonomy_json_path.txt'):
        assert name in ignored


# -- Picard wiring ---------------------------------------------------------------

def test_enable_registers_with_picard_api(plugin, settings, monkeypatch):
    """enable() uses only the public plugin API, with a fake Picard/Qt."""
    import sys
    import types
    from unittest import mock

    qt = types.ModuleType('PyQt6')
    qt.QtCore = mock.MagicMock()
    qt.QtWidgets = mock.MagicMock()
    api_module = types.ModuleType('picard.plugin3.api')
    api_module.OptionsPage = type('OptionsPage', (), {})
    api_module.BaseAction = type('BaseAction', (), {})
    for name, module in {
        'PyQt6': qt, 'PyQt6.QtCore': qt.QtCore, 'PyQt6.QtWidgets': qt.QtWidgets,
        'picard': types.ModuleType('picard'), 'picard.plugin3': types.ModuleType('picard.plugin3'),
        'picard.plugin3.api': api_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    class FakeConfig(dict):
        def register_option(self, name, default):
            self.setdefault(name, default)

    api = mock.MagicMock()
    api.plugin_config = FakeConfig(db_path=settings.db_path)
    plugin.enable(api)

    assert api.plugin_config['write_grouping_tag'] is True
    api.register_album_metadata_processor.assert_called_once()
    api.register_track_metadata_processor.assert_called_once()
    api.register_options_page.assert_called_once()

    md = album_metadata()
    album_processor = api.register_album_metadata_processor.call_args.args[0]
    album_processor(api, object(), md, {})
    assert md['genre'] == ['Electronic']
