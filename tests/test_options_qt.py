# SPDX-License-Identifier: GPL-2.0-or-later
"""Builds the settings page with real PyQt6 (headless). Skipped without PyQt6."""

import os
import sys
import types

import pytest

QtWidgets = pytest.importorskip('PyQt6.QtWidgets')


@pytest.fixture
def qt_app():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_options_page_round_trip(qt_app, plugin, settings, monkeypatch):
    class OptionsPage(QtWidgets.QWidget):  # stand-in for picard.plugin3.api.OptionsPage
        def __init__(self, parent=None):
            super().__init__(parent)

    api_module = types.ModuleType('picard.plugin3.api')
    api_module.OptionsPage = OptionsPage
    for name, module in {
        'picard': types.ModuleType('picard'), 'picard.plugin3': types.ModuleType('picard.plugin3'),
        'picard.plugin3.api': api_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    from local_genre_db.options import LocalGenreDbOptionsPage

    config = {name: default for name, default in plugin.DEFAULTS.items()}
    config['db_path'] = settings.db_path
    LocalGenreDbOptionsPage.api = types.SimpleNamespace(plugin_config=config)
    page = LocalGenreDbOptionsPage()
    page.load()
    assert page.db_edit.text() == settings.db_path
    assert '1 release groups' in page.status_label.text()

    page.checkboxes['write_style_tag'].setChecked(True)
    page.scope_combo.setCurrentText('release_group')
    page.save()
    assert config['write_style_tag'] is True
    assert config['learn_default_scope'] == 'release_group'
