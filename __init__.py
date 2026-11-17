# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 rb303
"""Local Genre DB - Picard 3 plugin.

Applies canonical genre/style tags from a local taxonomy (taxonomy.db, or a
taxonomy.json snapshot) built with https://github.com/dadtronics/picard-genre-db.

This module only uses the standard library so the lookup logic can be tested
without Picard. The Qt parts (settings page, context-menu action) live in
``options.py`` and ``actions.py`` and are imported from ``enable()``.
"""

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

# Plugin settings (stored in Picard's config under plugin.<uuid>) and defaults.
DEFAULTS = {
    'db_path': '',
    'json_path': '',
    'overwrite_existing': False,
    'overwrite_with_decisions': True,
    'write_style_tag': False,
    'write_grouping_tag': True,
    'remove_duplicate_style_tag': True,
    'learn_from_metadata': True,
    'learn_default_scope': 'artist',
}

LEARN_SCOPES = ('artist', 'release_group', 'release', 'recording')

DECISION_TABLES = {
    # scope: (table, id column, snapshot key)
    'recording': ('recording_decision', 'recording_mbid', 'recording_decisions'),
    'release': ('release_decision', 'release_mbid', 'release_decisions'),
    'release_group': ('release_group_decision', 'release_group_mbid', 'release_group_decisions'),
    'artist': ('artist_decision', 'artist_mbid', 'artist_decisions'),
}

# Replaced with Picard's plugin logger in enable(); messages then show up in
# Help -> View Debug/Error Log.
log = logging.getLogger('local_genre_db')


@dataclass
class Settings:
    db_path: str = ''
    json_path: str = ''
    overwrite_existing: bool = False
    overwrite_with_decisions: bool = True
    write_style_tag: bool = False
    write_grouping_tag: bool = True
    remove_duplicate_style_tag: bool = True
    learn_from_metadata: bool = True
    learn_default_scope: str = 'artist'

    @classmethod
    def from_config(cls, config) -> Settings:
        values = {}
        for name, default in DEFAULTS.items():
            try:
                value = config[name]
            except Exception:
                value = default
            if isinstance(default, bool):
                value = _to_bool(value, default)
            elif value is None:
                value = default
            else:
                value = str(value)
            values[name] = value
        return cls(**values)


def _to_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in ('true', '1', 'yes', 'on'):
            return True
        if lowered in ('false', '0', 'no', 'off'):
            return False
    if isinstance(value, int):
        return bool(value)
    return default


# --------------------------------------------------------------------------
# Locating the taxonomy
# --------------------------------------------------------------------------

def _plugin_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir() -> str:
    """Folder for files the plugin writes (pending decisions).

    The parent of the plugin folder (Picard's Plugins folder). Picard 3
    installs plugins as git checkouts and refuses to update or switch refs
    while untracked files sit inside them, and a reinstall deletes the folder.
    """
    return os.path.dirname(_plugin_dir())


def _read_path_file(name: str, plugin_dir: str) -> str:
    """First line of a legacy pointer file, from the plugin folder or its parent."""
    for folder in (plugin_dir, os.path.dirname(plugin_dir)):
        try:
            with open(os.path.join(folder, name), encoding='utf-8-sig') as handle:
                value = handle.readline().strip().lstrip('﻿')
        except OSError:
            continue
        if value:
            return value
    return ''


def resolve_path(kind: str, settings: Settings, plugin_dir: str | None = None):
    """Return (path, source) for kind 'db' or 'json'.

    Order: plugin settings, environment variable, legacy pointer file
    (plugin folder, then its parent), then ~/taxonomy.db / ~/taxonomy.json.
    """
    plugin_dir = plugin_dir or _plugin_dir()
    if kind == 'db':
        configured, env_name, file_name, default = (
            settings.db_path, 'PICARD_TAXONOMY_DB', 'taxonomy_path.txt', '~/taxonomy.db')
    else:
        configured, env_name, file_name, default = (
            settings.json_path, 'PICARD_TAXONOMY_JSON', 'taxonomy_json_path.txt', '~/taxonomy.json')

    if configured.strip():
        return os.path.expanduser(configured.strip()), 'settings'
    env_value = os.environ.get(env_name, '').strip()
    if env_value:
        return os.path.expanduser(env_value), f'env {env_name}'
    file_value = _read_path_file(file_name, plugin_dir)
    if file_value:
        return os.path.expanduser(file_value), f'pointer file {file_name}'
    return os.path.expanduser(default), 'default'


# --------------------------------------------------------------------------
# Loading the taxonomy
# --------------------------------------------------------------------------

def load_snapshot(settings: Settings, plugin_dir: str | None = None):
    """Load decisions and aliases. Prefers SQLite, falls back to JSON.

    Re-read on every call on purpose: it takes about a millisecond and means
    edits in the web app apply on the next album refresh, no restart needed.
    """
    db_path, _ = resolve_path('db', settings, plugin_dir)
    if db_path and os.path.exists(db_path):
        try:
            return load_sqlite_snapshot(db_path)
        except Exception as exc:
            log.warning('Local Genre DB: could not read %s (%s); trying JSON', db_path, exc)
    json_path, _ = resolve_path('json', settings, plugin_dir)
    with open(json_path, encoding='utf-8-sig') as handle:
        return json.load(handle)


def load_sqlite_snapshot(db_path: str):
    import sqlite3
    from pathlib import Path

    # Read-only, so lookups never lock out the web app.
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        snapshot = {}
        for table, id_column, key in DECISION_TABLES.values():
            rows = con.execute(
                f'''
                SELECT
                    d.{id_column} AS mbid,
                    COALESCE(NULLIF(d.genres_text, ''), cg.name) AS genre,
                    d.styles_text AS styles
                FROM {table} d
                LEFT JOIN canonical_genre cg ON cg.id = d.normalized_genre_id
                WHERE COALESCE(NULLIF(d.genres_text, ''), cg.name, '') != ''
                   OR COALESCE(d.styles_text, '') != ''
                '''
            ).fetchall()
            snapshot[key] = {
                str(row['mbid']): {'genre': str(row['genre'] or ''), 'styles': str(row['styles'] or '')}
                for row in rows
            }

        aliases = {}
        for row in con.execute(
            '''
            SELECT am.raw_value, cg.name AS genre, cs.name AS style
            FROM alias_mapping am
            LEFT JOIN canonical_genre cg ON cg.id = am.normalized_genre_id
            LEFT JOIN canonical_style cs ON cs.id = am.normalized_style_id
            ORDER BY am.confidence DESC, am.id ASC
            '''
        ):
            raw_key = str(row['raw_value'] or '').casefold()
            if raw_key and raw_key not in aliases:
                aliases[raw_key] = {'genre': str(row['genre'] or ''), 'style': str(row['style'] or '')}
        snapshot['aliases'] = aliases
        return snapshot
    finally:
        con.close()


def describe_taxonomy(settings: Settings, plugin_dir: str | None = None) -> str:
    """One-line status for the settings page and the startup log."""
    db_path, db_source = resolve_path('db', settings, plugin_dir)
    json_path, json_source = resolve_path('json', settings, plugin_dir)
    if not os.path.exists(db_path) and not os.path.exists(json_path):
        return f'Not found: {db_path} ({db_source}) or {json_path} ({json_source})'
    try:
        snapshot = load_snapshot(settings, plugin_dir)
    except Exception as exc:
        return f'Error reading taxonomy: {exc}'
    used = db_path if os.path.exists(db_path) else json_path
    source = db_source if os.path.exists(db_path) else json_source
    counts = ', '.join(
        f'{len(snapshot.get(key, {}))} {label}'
        for key, label in (
            ('release_group_decisions', 'release groups'),
            ('release_decisions', 'releases'),
            ('recording_decisions', 'recordings'),
            ('artist_decisions', 'artists'),
            ('aliases', 'aliases'),
        )
    )
    return f'Using {used} ({source}): {counts}'


# --------------------------------------------------------------------------
# Tag helpers
# --------------------------------------------------------------------------

def _get_tag(metadata, name: str, default: str = '') -> str:
    try:
        value = metadata.get(name, default)
    except Exception:
        try:
            value = metadata[name]
        except Exception:
            return default
    if value is None:
        return default
    if isinstance(value, list):
        return '; '.join(str(v) for v in value if v)
    return str(value)


def split_semicolon(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(';') if part.strip()]


def _set_tag(metadata, name: str, value: str) -> None:
    values = split_semicolon(value)
    metadata[name] = values if values else value


def _delete_tag(metadata, name: str) -> bool:
    try:
        if name in metadata:
            del metadata[name]
            return True
    except Exception:
        pass
    return False


def _split_ids(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace(';', ',').split(',') if part.strip()]


def metadata_ids(metadata) -> dict:
    return {
        'recording': _get_tag(metadata, 'musicbrainz_recordingid').strip(),
        # Picard calls the release MBID "albumid".
        'release': _get_tag(metadata, 'musicbrainz_albumid').strip(),
        'release_group': _get_tag(metadata, 'musicbrainz_releasegroupid').strip(),
        'album_artists': (
            _split_ids(_get_tag(metadata, 'musicbrainz_albumartistid')) or
            _split_ids(_get_tag(metadata, 'musicbrainz_releaseartistid'))
        ),
        'track_artists': _split_ids(_get_tag(metadata, 'musicbrainz_artistid')),
    }


def current_styles(metadata) -> str:
    return (
        _get_tag(metadata, 'grouping').strip() or
        _get_tag(metadata, 'contentgroup').strip() or
        _get_tag(metadata, 'style').strip()
    )


# --------------------------------------------------------------------------
# Lookup and apply
# --------------------------------------------------------------------------

def lookup_decision(snapshot, ids: dict):
    """Most specific decision wins: recording, release, release group, artist."""
    for scope in ('recording', 'release', 'release_group'):
        mbid = ids.get(scope)
        if not mbid:
            continue
        decision = snapshot.get(DECISION_TABLES[scope][2], {}).get(mbid)
        if decision:
            return dict(decision, source=scope, source_mbid=mbid)
    artist_decisions = snapshot.get('artist_decisions', {})
    for mbid in list(ids.get('album_artists', [])) + list(ids.get('track_artists', [])):
        decision = artist_decisions.get(mbid)
        if decision:
            return dict(decision, source='artist', source_mbid=mbid)
    return None


def lookup_aliases(snapshot, raw_terms: Iterable[str]):
    aliases = snapshot.get('aliases', {})
    genre_name: str | None = None
    styles: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        row = aliases.get(raw.casefold())
        if not row:
            continue
        if row.get('genre') and not genre_name:
            genre_name = str(row['genre'])
        style = str(row.get('style') or '')
        if style and style.casefold() not in seen:
            seen.add(style.casefold())
            styles.append(style)
    if not genre_name and not styles:
        return None
    return {'genre': genre_name or '', 'styles': '; '.join(styles), 'source': 'alias', 'source_mbid': ''}


def _raw_terms(metadata) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for tag_name in ('genre', 'style', 'contentgroup', 'grouping'):
        for term in split_semicolon(_get_tag(metadata, tag_name)):
            if term.casefold() not in seen:
                seen.add(term.casefold())
                ordered.append(term)
    return ordered


def apply_decision(metadata, decision, settings: Settings) -> dict:
    genre = (decision.get('genre') or '').strip()
    styles = (decision.get('styles') or '').strip()
    force = settings.overwrite_with_decisions and decision.get('source') != 'alias'
    written = []

    def should_write(tag_name):
        return force or settings.overwrite_existing or not _get_tag(metadata, tag_name).strip()

    if genre and should_write('genre'):
        _set_tag(metadata, 'genre', genre)
        written.append('genre')
    if settings.write_style_tag and styles and should_write('style'):
        _set_tag(metadata, 'style', styles)
        written.append('style')
    if settings.write_grouping_tag and styles and should_write('grouping'):
        _set_tag(metadata, 'grouping', styles)
        written.append('grouping')
    if (settings.remove_duplicate_style_tag and not settings.write_style_tag and styles and
            split_semicolon(_get_tag(metadata, 'style')) == split_semicolon(styles)):
        if _delete_tag(metadata, 'style'):
            written.append('-style')
    if styles and split_semicolon(_get_tag(metadata, 'contentgroup')) == split_semicolon(styles):
        if _delete_tag(metadata, 'contentgroup'):
            written.append('-contentgroup')
    return {'genre': genre, 'styles': styles, 'written': written}


# --------------------------------------------------------------------------
# Learning (pending decisions for the web app to import)
# --------------------------------------------------------------------------

def _pending_path() -> str:
    return os.path.join(_data_dir(), 'local_genre_db_pending.jsonl')


def _learn_target(metadata, ids: dict, settings: Settings):
    scope = _get_tag(metadata, 'local_genre_db_scope').strip().casefold() or settings.learn_default_scope
    scope = {'album': 'release', 'release-group': 'release_group', 'track': 'recording'}.get(scope, scope)
    if scope == 'artist':
        artists = list(ids['album_artists']) or list(ids['track_artists'])
        return ('artist', artists[0]) if artists else ('', '')
    if scope in ('release', 'release_group', 'recording') and ids.get(scope):
        return scope, ids[scope]
    return '', ''


def append_pending(metadata, ids: dict, settings: Settings, path: str | None = None) -> bool:
    if not settings.learn_from_metadata:
        return False
    genre = _get_tag(metadata, 'genre').strip()
    styles = current_styles(metadata)
    if not genre or not styles:
        return False
    scope, mbid = _learn_target(metadata, ids, settings)
    if not mbid:
        return False
    row = {
        'scope': scope,
        'mbid': mbid,
        'genre': genre,
        'styles': styles,
        'title': _get_tag(metadata, 'title'),
        'artist': _get_tag(metadata, 'artist'),
        'album': _get_tag(metadata, 'album'),
        'recording_mbid': ids['recording'],
        'release_mbid': ids['release'],
        'release_group_mbid': ids['release_group'],
        'album_artist_mbids': list(ids['album_artists']),
        'track_artist_mbids': list(ids['track_artists']),
        'learned_at': datetime.now().isoformat(timespec='seconds'),
    }
    try:
        with open(path or _pending_path(), 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, sort_keys=True) + '\n')
    except OSError as exc:
        log.warning('Local Genre DB: could not write pending decision: %s', exc)
        return False
    return True


# --------------------------------------------------------------------------
# Picard entry points
# --------------------------------------------------------------------------

def process_metadata(metadata, entity: str, settings: Settings, plugin_dir: str | None = None):
    """Look up and apply a decision. Returns the decision applied, or None."""
    db_path, _ = resolve_path('db', settings, plugin_dir)
    json_path, _ = resolve_path('json', settings, plugin_dir)
    if not os.path.exists(db_path) and not os.path.exists(json_path):
        log.warning(
            'Local Genre DB: taxonomy not found (%s / %s). Set it in '
            'Options -> Plugins -> Local Genre DB.', db_path, json_path)
        return None

    ids = metadata_ids(metadata)
    snapshot = load_snapshot(settings, plugin_dir)
    decision = lookup_decision(snapshot, ids) or lookup_aliases(snapshot, _raw_terms(metadata))
    if decision:
        result = apply_decision(metadata, decision, settings)
        log.debug(
            'Local Genre DB: %s %r: %s %s -> genre=%r styles=%r wrote=%s',
            entity, _get_tag(metadata, 'title') or _get_tag(metadata, 'album'),
            decision['source'], decision.get('source_mbid', ''),
            result['genre'], result['styles'], ','.join(result['written']) or 'nothing')
        return decision
    if append_pending(metadata, ids, settings):
        log.debug('Local Genre DB: no decision for %r; saved as pending', _get_tag(metadata, 'album'))
    return None


def _process_album(api, album, metadata, release_node):
    try:
        process_metadata(metadata, 'release', Settings.from_config(api.plugin_config))
    except Exception as exc:
        log.error('Local Genre DB: processing failed: %s', exc)


def _process_track(api, track, metadata, track_node, release_node=None):
    try:
        process_metadata(metadata, 'recording', Settings.from_config(api.plugin_config))
    except Exception as exc:
        log.error('Local Genre DB: processing failed: %s', exc)


def enable(api) -> None:
    global log
    log = api.logger
    for name, default in DEFAULTS.items():
        api.plugin_config.register_option(name, default)
    api.register_album_metadata_processor(_process_album)
    api.register_track_metadata_processor(_process_track)

    from .options import LocalGenreDbOptionsPage
    api.register_options_page(LocalGenreDbOptionsPage)

    log.info('Local Genre DB: %s', describe_taxonomy(Settings.from_config(api.plugin_config)))


def disable() -> None:
    pass
