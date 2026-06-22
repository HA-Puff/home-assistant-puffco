# Publishing guide

Repository: [HA-Puff/home-assistant-puffco](https://github.com/HA-Puff/home-assistant-puffco)

## 1. Git identity (use noreply — not your personal email)

```powershell
cd "z:\OneDrive\Documents\Puffco-Integration"
git init
git config user.email "YOUR_ID+HA-Puff@users.noreply.github.com"
git config user.name "HA-Puff"
```

Replace `YOUR_ID` with the numeric ID from GitHub → **Settings → Emails** (enable “Keep my email addresses private”).

Verify before committing:

```powershell
git config user.email
```

## 2. Build release zip (optional)

```powershell
.\scripts\build_release.ps1
```

Output: `dist/puffco-home-assistant-1.0.0.zip`

## 3. First push

```powershell
git add .
git status
git commit -m "Release v1.0.0"
git branch -M main
git remote add origin https://github.com/HA-Puff/home-assistant-puffco.git
git push -u origin main
```

## 4. GitHub release

1. [Releases](https://github.com/HA-Puff/home-assistant-puffco/releases) → **Draft new release**
2. Tag: `v1.0.0`
3. Title: `1.0.0 — First public release`
4. Body: paste from `docs/RELEASE_NOTES_v1.0.0.md` or `CHANGELOG.md`
5. Attach `dist/puffco-home-assistant-1.0.0.zip`
6. **Publish release**

## 5. HACS

**HACS → Custom repositories** → add:

```
https://github.com/HA-Puff/home-assistant-puffco
```

Category: **Integration** → Install **Puffco** → Restart HA.
