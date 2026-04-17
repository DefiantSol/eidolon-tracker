# Eidolon Wish Tracker

Lightweight local tracker for Aura Kingdom Eidolon wishes.

The app ships with built-in default Eidolon and wish data. User progress is stored in `tracker.db` with SQLite, so profiles, owned Eidolons, completed wishes, and completed Eidolons persist across shutdowns and restarts.

## Download And Run

For normal users, do not download the repository source code.

1. Go to the GitHub repository's **Releases** page.
2. Download `EidolonTracker-vX.X.X-windows.zip` from the latest release assets.
3. Unzip `EidolonTracker-vX.X.X-windows.zip`.
4. Open the unzipped `EidolonTracker` folder.
5. Double-click `EidolonTracker.exe`.

The app opens in your browser at:

```text
http://127.0.0.1:8765
```

Keep the whole unzipped `EidolonTracker` folder together. The app creates `tracker.db` beside `EidolonTracker.exe`; that file is your personal save data. Multiple account profiles are stored in that same database.

Do not use GitHub's automatic **Source code (zip)** or **Source code (tar.gz)** downloads unless you are a developer. Those files do not include `EidolonTracker.exe`.

## Updating

To update to a newer release:

1. Download the newer `EidolonTracker-vX.X.X-windows.zip`.
2. Extract it over your existing `EidolonTracker` folder, or unzip it somewhere new and copy your old `tracker.db` into the new `EidolonTracker` folder.
3. Double-click `EidolonTracker.exe`.

Release zips do not include `tracker.db`, so extracting a normal release over an existing folder should not replace your saved profiles. If you delete the old folder before updating, copy `tracker.db` somewhere safe first.

Do not share your `tracker.db` unless you want someone else to start with your progress.

## Backup And Restore

Open Settings to download or restore your tracker data.

- **Download Backup** saves a copy of `tracker.db`, including every profile and progress check.
- **Restore Backup** replaces the current tracker data with a selected backup file. The app creates a local safety backup before restoring.

## Run From Source

```powershell
cd path\to\eidolon-tracker
python app.py
```

Or:

```powershell
.\run.ps1
```

Then open:

```text
http://127.0.0.1:8765
```

## Developer Build

Build a double-clickable Windows app:

```powershell
.\build.ps1
```

The app will be created at:

```text
dist\EidolonTracker\EidolonTracker.exe
```

Share the whole `dist\EidolonTracker` folder. The app creates `tracker.db` beside the `.exe` on first run, and that file becomes the user's save data.

Personal progress is not copied into release builds. To move your own save into a new build, copy your personal `tracker.db` into the `dist\EidolonTracker` folder after building.

## Automated GitHub Releases

Pushing a version tag builds and uploads the Windows release zip automatically:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

The workflow creates or updates the GitHub Release for that tag and uploads:

```text
EidolonTracker-v1.0.0-windows.zip
```

The auto-generated GitHub source-code downloads still do not include the `.exe`.

## Reset Local Data

Reset the local database back to the built-in defaults:

```powershell
python app.py --reset-data --import-only
```

This clears local progress.

## Image Maintenance

Fetch matching Eidolon portraits and item icons from AuraKingdom-DB:

```powershell
python app.py --sync-assets --import-only
```

Download matched image files locally after syncing:

```powershell
python app.py --cache-images --import-only
```

Developer image files are stored under:

```text
static\img\
```

After caching, the UI uses local `/img/...` paths instead of requesting AuraKingdom-DB's CDN on every page load. Normal app startup does not fetch AuraKingdom-DB; network fetching only happens when a developer runs the explicit sync commands.

## Repo Notes

- No Python package install is required to run from source.
- `tracker.db` is ignored by Git.
- Cached image files are ignored by Git.
- Release builds do not include personal progress.
