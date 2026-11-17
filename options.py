# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 rb303
"""Settings page: Options -> Plugins -> Local Genre DB."""

import os

from picard.plugin3.api import OptionsPage
from PyQt6 import QtCore, QtWidgets

from . import DEFAULTS, LEARN_SCOPES, Settings, describe_taxonomy

_CHECKBOXES = (
    ('overwrite_with_decisions', 'Decisions overwrite existing genre/grouping tags'),
    ('overwrite_existing', 'Alias matches overwrite existing tags too'),
    ('write_grouping_tag', 'Write styles to the Grouping tag'),
    ('write_style_tag', 'Write styles to a Style tag'),
    ('remove_duplicate_style_tag', 'Remove a Style tag that duplicates the styles'),
    ('learn_from_metadata', 'Remember genre/grouping of unmatched albums as pending decisions'),
)


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
        check_button = QtWidgets.QPushButton('Check')
        check_button.clicked.connect(self._update_status)
        status_row = QtWidgets.QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(check_button)
        form.addRow('Status:', status_row)
        hint = QtWidgets.QLabel(
            'Leave empty to use the PICARD_TAXONOMY_DB / PICARD_TAXONOMY_JSON environment '
            'variables or taxonomy_path.txt / taxonomy_json_path.txt pointer files.')
        form.addRow(hint)
        layout.addWidget(files)

        behaviour = QtWidgets.QGroupBox('Tagging')
        box = QtWidgets.QVBoxLayout(behaviour)
        self.checkboxes = {}
        for name, label in _CHECKBOXES:
            checkbox = QtWidgets.QCheckBox(label)
            box.addWidget(checkbox)
            self.checkboxes[name] = checkbox
        scope_row = QtWidgets.QHBoxLayout()
        scope_row.addWidget(QtWidgets.QLabel('Pending decisions are saved per:'))
        self.scope_combo = QtWidgets.QComboBox()
        self.scope_combo.addItems(LEARN_SCOPES)
        scope_row.addWidget(self.scope_combo)
        scope_row.addStretch(1)
        box.addLayout(scope_row)
        layout.addWidget(behaviour)
        layout.addStretch(1)

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
        values['learn_default_scope'] = self.scope_combo.currentText()
        return Settings(**values)

    def _update_status(self):
        self.status_label.setText(describe_taxonomy(self._settings_from_ui()))

    def load(self):
        settings = Settings.from_config(self.api.plugin_config)
        self.db_edit.setText(settings.db_path)
        self.json_edit.setText(settings.json_path)
        for name, checkbox in self.checkboxes.items():
            checkbox.setChecked(getattr(settings, name))
        scope = settings.learn_default_scope
        self.scope_combo.setCurrentText(scope if scope in LEARN_SCOPES else DEFAULTS['learn_default_scope'])
        self._update_status()

    def save(self):
        settings = self._settings_from_ui()
        for name in DEFAULTS:
            self.api.plugin_config[name] = getattr(settings, name)
