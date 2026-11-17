# Local Genre DB (Picard 3)

MusicBrainz Picard plugin that applies canonical `genre` and `grouping`
tags from a local taxonomy database, keyed by MusicBrainz IDs.

- **Decisions** per recording, release, release group or artist. The most
  specific one wins: recording, then release, then release group, then
  artist. Decisions overwrite Picard's own genres.
- **Alias mapping**: raw genres/styles already in your files are mapped to
  canonical values. Aliases only fill empty tags.
- Albums with no match but with genre + grouping already set can be saved as
  *pending decisions* for review in the web app.

The taxonomy is built and edited with the companion project
[picard-genre-db](https://github.com/dadtronics/picard-genre-db)
(web UI + `manage_taxonomy.py`).

## Install

In Picard: **Options → Plugins → Install from URL**:

```
https://github.com/dadtronics/picard-local-genre-db
```

Pick the newest **`vX.Y.Z` tag** in the version selector rather than `main`.
Picard then offers updates when a newer tag is released.

## Configure

**Options → Plugins → Local Genre DB**:

- **Database**: browse to your `taxonomy.db`. The status line shows what the
  plugin found, e.g. `287 release groups, 37 aliases`.
- **JSON snapshot** (optional): `taxonomy.json`, used if the database can't
  be read.
- Tagging options: whether decisions overwrite existing tags, which tags
  styles go to (Grouping by default), and whether unmatched albums are
  remembered as pending decisions.

Settings live in Picard's config, so updating or reinstalling the plugin
keeps them.

Older ways to set the paths still work when the settings are empty, in this
order: the `PICARD_TAXONOMY_DB` / `PICARD_TAXONOMY_JSON` environment
variables, then `taxonomy_path.txt` / `taxonomy_json_path.txt` pointer files
in Picard's Plugins folder.

## Using it

- The plugin runs when a release loads. After changing a decision in the web
  app, right-click the album → **Refresh**. The database is re-read on every
  lookup, so no restart is needed.
- Changes are in-memory until you save the files.
- Pending decisions are written to `local_genre_db_pending.jsonl` in Picard's
  Plugins folder; import them with `manage_taxonomy.py`.

## Troubleshooting

- **Help → View Debug/Error Log**: the plugin logs which taxonomy it loaded
  at startup and warns when it can't find one. Per-album lookups are logged
  at debug level.
- **"Failed to switch ref … has uncommitted changes"** when updating from
  0.4.0 or 0.4.1: those versions wrote a log file inside the plugin folder.
  Uninstall the plugin and install it again from the URL above (choose the
  newest tag). Your taxonomy is not touched.

## Development

```
pip install pytest ruff PyQt6
ruff check .
QT_QPA_PLATFORM=offscreen pytest -q tests
```

The core (`__init__.py`) is standard-library only and tested without Picard;
`options.py` (settings page) is tested with real PyQt6, headless.
To release: bump `version` in `MANIFEST.toml`, commit, then
`git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`. CI checks that the
tag matches the manifest.

## License

GPL-2.0-or-later. See `LICENSE`.
