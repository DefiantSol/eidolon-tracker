# Privacy And Release Safety

This repository must not contain personal local data, machine-specific paths, runtime logs, or user save files. Treat this file as a pre-commit and pre-release checklist.

## Never Commit

- Runtime databases: `tracker.db`, `tracker.backup.*.db`, or any copied user save database.
- Runtime logs: `*.log`, server output files, crash dumps, traceback captures, or terminal transcripts.
- Local absolute paths: `C:\...`, `D:\...`, `Users\...`, workspace paths, client install paths, or Codex directories.
- Personal identifiers: Windows username, real name, host name, email, tokens, local browser/cache paths, or GitHub auth output.
- Build artifacts: `build\`, `dist\`, generated `.spec` files, temporary zips, or copied executable folders.

## Use Generic Inputs

- Documentation should say `repository root`, `<repo path>`, or `<ini_plain data db path>` instead of a real local path.
- Scripts that need local files must accept a command-line option or environment variable instead of hardcoding a local path.
- Example: use `--data-dir <ini_plain data db path>` or `EIDOLON_CLIENT_DATA`, not a personal `C:\...` path.

## Before Every Commit

Run these checks from the repository root:

```powershell
git status --short
git diff --cached --name-only
git diff --cached
```

Reject the commit if staged changes include ignored runtime data, logs, local absolute paths, or personal identifiers.

For a broader scan before pushing:

```powershell
$commits = git rev-list --all
git grep -n -I -E "Users\\|C:\\|D:\\|\.codex|DESKTOP|server\.out|server\.err" $commits -- .
```

No output means the reachable Git history passed that scan.

## Before Every Release

- Build with `.\build.ps1`.
- Delete `dist\EidolonTracker\tracker.db` if it exists before zipping or publishing.
- Verify `dist\EidolonTracker\_internal\data\seed.json` exists.
- Zip and publish the whole `dist\EidolonTracker` folder, not only the `.exe`.
- Do not upload logs, local databases, or ad hoc debug archives as release assets.

## If Something Leaks

Do not make another normal commit that only deletes the file. If personal data was pushed, rewrite the affected Git history and force-update the affected branch and tags, then expire/prune local reflogs.
