# Eidolon Tracker Agent Notes

## Project

- Repo path: repository root.
- App: local Windows-friendly Aura Kingdom Eidolon wish tracker.
- Backend: single-file Python HTTP server in `app.py`; no Flask dependency.
- Frontend: static files in `static\index.html`, `static\app.js`, and `static\styles.css`.
- Data seed: `data\seed.json`.
- User save data: SQLite database `tracker.db` beside `app.py` when run from source, or beside `EidolonTracker.exe` when frozen. Account profiles are stored in this same database.

## Run And Build

- Run from source: `python app.py` or `.\run.ps1`.
- Local URL: `http://127.0.0.1:8765`.
- Reset local data from seed: `python app.py --reset-data --import-only`.
- Sync AuraKingdom-DB metadata: `python app.py --sync-assets --import-only`.
- Cache local images: `python app.py --cache-images --import-only`.
- Compare client wish data: `python scripts\sync_client_wishes.py --data-dir <ini_plain data db path>`.
- Copy runtime DB image/detail URLs back into the release seed: `python scripts\export_db_assets_to_seed.py`.
- Build Windows app: `.\build.ps1`.
- Build output: `dist\EidolonTracker\EidolonTracker.exe`.

## Release Hygiene

- Read `PRIVACY.md` before committing, pushing, tagging, or publishing a release.
- Never package personal `tracker.db` into a release zip.
- Before zipping `dist\EidolonTracker`, remove `dist\EidolonTracker\tracker.db` if it exists.
- Verify release builds include `dist\EidolonTracker\_internal\data\seed.json`.
- Share the whole `dist\EidolonTracker` folder or a zip of that folder, not just the `.exe`.
- GitHub releases are built by `.github\workflows\release.yml` when pushing `v*` tags or using workflow dispatch.

## Data Rules

- `tracker.db` and `tracker.backup.*.db` are local/user data and ignored by Git.
- Settings includes browser-friendly data backup/restore. Restore validates the uploaded SQLite DB, creates `tracker.backup.before-restore.*.db`, then copies it into `tracker.db`.
- Logs, local absolute paths, usernames, hostnames, tokens, and machine-specific workspace paths must not be committed.
- Scripts that need local data must take a CLI argument or environment variable instead of hardcoding a personal path.
- The app seeds from `data\seed.json`; normal startup should not fetch AuraKingdom-DB.
- Cached image files live under `static\img\`; commit files that are referenced by `data\seed.json` so releases work offline.
- Preserve user progress unless the user explicitly asks for reset/import-only behavior.
- Profile-aware code should scope progress changes to the active profile. New profiles are seeded from `data\seed.json` and start with the default starter-six state.

## Git Caveat

Git may report dubious ownership for this repo. If status/log commands fail, run:

```powershell
git config --global --add safe.directory D:/eidolon-tracker
```

Then retry the Git command.
