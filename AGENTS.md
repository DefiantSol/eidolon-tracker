# Eidolon Tracker Notes

- Repo: `D:\eidolon-tracker`.
- App: local Windows Aura Kingdom Eidolon wish tracker.
- Backend: `app.py`, single-file Python HTTP server; no Flask.
- Frontend: `static\index.html`, `static\app.js`, `static\styles.css`.
- Seed: `data\seed.json`.
- Runtime DB: `tracker.db` beside source app or frozen exe; preserve unless reset is requested.

Commands:

```powershell
python app.py
.\run.ps1
python app.py --reset-data --import-only
python app.py --sync-assets --import-only
python app.py --cache-images --import-only
python scripts\sync_client_wishes.py --data-dir <ini_plain data db path>
python scripts\export_db_assets_to_seed.py
.\build.ps1
```

URL: `http://127.0.0.1:8765`.

Release/privacy:

- Read `PRIVACY.md` before commit, push, tag, or release.
- Do not commit/package `tracker.db`, backups, logs, local paths, usernames, hostnames, tokens, or personal workspace paths.
- Before zipping `dist\EidolonTracker`, remove `dist\EidolonTracker\tracker.db` if present.
- Verify `dist\EidolonTracker\_internal\data\seed.json`.
- Ship the full `dist\EidolonTracker` folder/zip, not only the exe.

Data rules:

- Normal startup should not fetch AuraKingdom-DB.
- Cached images under `static\img` should exist for seed references.
- Profile-aware code scopes progress to active profile.

Git caveat:

```powershell
git config --global --add safe.directory D:/eidolon-tracker
```
