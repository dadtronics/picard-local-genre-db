# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 rb303
"""Settings page: Options -> Plugins -> Local Genre DB."""

import os

from picard.plugin3.api import OptionsPage
from PyQt6 import QtCore, QtWidgets

from . import DEFAULTS, LEARN_SCOPES, Settings, describe_taxonomy

# (setting, label, tooltip), grouped as on the page.
_TAGGING = (
    ('overwrite_with_decisions', 'Decisions replace existing Genre and Grouping',
     'A decision from your database (recording, release, release group or artist) wins over '
     "MusicBrainz genres and whatever is already in the file."),
    ('overwrite_existing', 'Alias matches replace existing tags too',
     'Off: alias mappings only fill empty Genre/Grouping. On: they overwrite them.'),
    ('write_grouping_tag', 'Write styles to Grouping',
     'Grouping is the style tag this workflow uses; most players can show it.'),
)
_LEGACY_STYLE = (
    ('write_style_tag', 'Also write styles to a separate Style tag',
     'Style is a non-standard tag (saved as a custom field) that few players read. '
     'Off since May 2026: styles go to Grouping only.'),
    ('remove_duplicate_style_tag', 'Remove an old Style tag when it just repeats Grouping',
     'Cleans up files tagged by early versions that wrote both. Only removes Style when it '
     'matches the styles being written.'),
)
_SCOPE_LABELS = {
    'release_group': 'Release group (all editions of the album)',
    'release': 'Release (this edition only)',
    'artist': 'Album artist',
    'recording': 'Recording (single track)',
}


class LocalGenreDbOptionsPage(OptionsPage):
    TITLE = 'Local Genre DB'
    HELP_URL = 'https://github.com/dadtronics/picard-local-genre-db#readme'

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        files = QtWidgets.QGroupBox('Taxonomy')
        form = QtWidgets.QFormLayout(files)
        self.db_edit = self._path_row(form, 'Database (taxonomy.db):', 'SQLite DB (*.db *.sqlite);;All files (*)')
        self.json_edit = self._path_row(form, 'JSON snapshot (optional):', 'JSON (*.json);;All files (*)')
        self.status_label = QtWidgets.QLabel()
        self.status_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setWordWrap(True)
        check_button = QtWidgets.QPushButton('Check')
        check_button.clicked.connect(self._update_status)
        status_row = QtWidgets.QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(check_button)
        form.addRow('Status:', status_row)
        hint = QtWidgets.QLabel(
            'Leave empty to use the PICARD_TAXONOMY_DB / PICARD_TAXONOMY_JSON environment '
            'variables or taxonomy_path.txt / taxonomy_json_path.txt pointer files.')
        hint.setWordWrap(True)
        form.addRow(hint)
        layout.addWidget(files)

        self.checkboxes = {}
        layout.addWidget(self._checkbox_group('Tagging', _TAGGING))

        pending = QtWidgets.QGroupBox('Pending decisions')
        box = QtWidgets.QVBoxLayout(pending)
        learn = self._checkbox(
            'learn_from_metadata', 'Remember unmatched albums that already have Genre and Grouping',
            'Written to local_genre_db_pending.jsonl in the Plugins folder; review and import them '
            'in the picard-genre-db web app.')
        box.addWidget(learn)
        scope_row = QtWidgets.QHBoxLayout()
        scope_row.addWidget(QtWidgets.QLabel('Save them as decisions for:'))
        self.scope_combo = QtWidgets.QComboBox()
        for scope in LEARN_SCOPES:
            self.scope_combo.addItem(_SCOPE_LABELS[scope], scope)
        scope_row.addWidget(self.scope_combo)
        scope_row.addStretch(1)
        box.addLayout(scope_row)
        learn.toggled.connect(self.scope_combo.setEnabled)
        layout.addWidget(pending)

        layout.addWidget(self._checkbox_group('Style tag (legacy)', _LEGACY_STYLE))
        layout.addStretch(1)

    def _checkbox(self, name, label, tooltip):
        checkbox = QtWidgets.QCheckBox(label)
        checkbox.setToolTip(tooltip)
        self.checkboxes[name] = checkbox
        return checkbox

    def _checkbox_group(self, title, items):
        group = QtWidgets.QGroupBox(title)
        box = QtWidgets.QVBoxLayout(group)
        for name, label, tooltip in items:
            box.addWidget(self._checkbox(name, label, tooltip))
        return group

    def _path_row(self, form, label, file_filter):
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText('not set')
        button = QtWidgets.QPushButton('Browse...')

        def browse():
            start = edit.text().strip() or os.path.expanduser('~')
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, label.rstrip(':'), start, file_filter)
            if path:
                edit.setText(os.path.normpath(path))
                self._update_status()

        button.clicked.connect(browse)
        edit.editingFinished.connect(self._update_status)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(label, row)
        return edit

    def _settings_from_ui(self) -> Settings:
        values = {name: checkbox.isChecked() for name, checkbox in self.checkboxes.items()}
        values['db_path'] = self.db_edit.text().strip()
        values['json_path'] = self.json_edit.text().strip()
        values['learn_default_scope'] = self.scope_combo.currentData()
        return Settings(**values)

    def _update_status(self):
        self.status_label.setText(describe_taxonomy(self._settings_from_ui()))

    def load(self):
        settings = Settings.from_config(self.api.plugin_config)
        self.db_edit.setText(settings.db_path)
        self.json_edit.setText(settings.json_path)
        for name, checkbox in self.checkboxes.items():
            checkbox.setChecked(getattr(settings, name))
        index = self.scope_combo.findData(settings.learn_default_scope)
        if index < 0:
            index = self.scope_combo.findData(DEFAULTS['learn_default_scope'])
        self.scope_combo.setCurrentIndex(index)
        self.scope_combo.setEnabled(settings.learn_from_metadata)
        self._update_status()

    def save(self):
        settings = self._settings_from_ui()
        for name in DEFAULTS:
            self.api.plugin_config[name] = getattr(settings, name)
