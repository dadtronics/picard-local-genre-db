# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 rb303
"""Right-click on an album -> Save genre to Local Genre DB."""

from picard.plugin3.api import Album, BaseAction
from PyQt6 import QtWidgets

from . import (
    Settings,
    TaxonomyError,
    _get_tag,
    current_styles,
    decision_target,
    metadata_ids,
    resolve_path,
    save_decision,
)

SCOPES = (
    ('release_group', 'Release group (all editions of this album)'),
    ('release', 'This release only'),
    ('artist', 'Album artist (everything by them)'),
)


class SaveGenreAction(BaseAction):
    TITLE = 'Save genre to Local Genre DB'

    def callback(self, objs):
        albums = [obj for obj in objs if isinstance(obj, Album)]
        if not albums:
            return
        scope = self.ask_scope(len(albums))
        if not scope:
            return
        settings = Settings.from_config(self.api.plugin_config)
        db_path, _ = resolve_path('db', settings)
        saved, failed = [], []
        for album in albums:
            metadata = album.metadata
            name = _get_tag(metadata, 'album') or str(album)
            try:
                result = save_decision(
                    db_path,
                    scope,
                    decision_target(metadata_ids(metadata), scope),
                    _get_tag(metadata, 'genre'),
                    current_styles(metadata),
                )
            except TaxonomyError as exc:
                failed.append(f'{name}: {exc}')
                continue
            except Exception as exc:
                self.api.logger.exception('Local Genre DB: saving %r failed', name)
                failed.append(f'{name}: {exc}')
                continue
            self.api.logger.info('Local Genre DB: saved %s decision %s for %r: %s / %s', scope,
                                 result['mbid'], name, result['genres'], result['styles'])
            saved.append(f"{name}: {result['genres']}" + (f" / {result['styles']}" if result['styles'] else ''))
        self.report(saved, failed)

    # Dialog helpers, separate so tests can replace them.

    def _parent(self):
        return getattr(getattr(self, 'tagger', None), 'window', None)

    def ask_scope(self, count: int) -> str:
        labels = [label for _, label in SCOPES]
        what = 'this album' if count == 1 else f'these {count} albums'
        choice, ok = QtWidgets.QInputDialog.getItem(
            self._parent(), 'Save genre to Local Genre DB',
            f"Save the genre and grouping of {what} as a decision for:", labels, 0, False)
        if not ok:
            return ''
        return SCOPES[labels.index(choice)][0]

    def report(self, saved, failed) -> None:
        lines = []
        if saved:
            lines.append('Saved:\n' + '\n'.join(saved))
        if failed:
            lines.append('Not saved:\n' + '\n'.join(failed))
        box = QtWidgets.QMessageBox.warning if failed else QtWidgets.QMessageBox.information
        box(self._parent(), 'Local Genre DB', '\n\n'.join(lines))
