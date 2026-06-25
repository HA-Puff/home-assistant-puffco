# Publishing guide

Repository: [HA-Puff/home-assistant-puffco](https://github.com/HA-Puff/home-assistant-puffco)

## Git identity (repo-local)

Use the throwaway account’s **noreply** email so commits do not expose a personal address:

```bash
cd /path/to/home-assistant-puffco
git config user.email "YOUR_ID+HA-Puff@users.noreply.github.com"
git config user.name "HA-Puff"
```

Find `YOUR_ID` under GitHub → **Settings → Emails** (with “Keep my email addresses private” enabled).

Verify before committing:

```bash
git config user.email
git log -1 --format="%an <%ae>"
```

## Release workflow

1. Bump `version` in `custom_components/puffco/manifest.json`.
2. Add a section to `CHANGELOG.md`.
3. If you changed `puffco-ble/`, run `scripts/sync_ha_lib.ps1` (or `.sh`) so `_vendor/` matches.
4. Commit and push to `main`.
5. Optional: build a zip for manual installs:

   ```powershell
   .\scripts\build_release.ps1 -Version 1.0.1
   ```

   Output: `dist/puffco-home-assistant-<version>.zip`

6. On GitHub: **Releases → Draft new release**
   - Tag: `v<version>` (e.g. `v1.0.1`)
   - Title: short summary
   - Body: paste from `CHANGELOG.md`
   - Attach the zip if you built one
   - **Publish release**

## Push (first time or routine)

```bash
git add -A
git status
git commit -m "Release v1.0.1"
git push origin main
```

Authenticate as **HA-Puff** when prompted (browser or `gh auth login`).

## HACS

Users add the custom repository once:

```
https://github.com/HA-Puff/home-assistant-puffco
```

Category: **Integration** → Install **Puffco** → Restart Home Assistant.
