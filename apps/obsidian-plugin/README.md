# BLACKBOX Obsidian plugin (v0)

Run governed BLACKBOX skills from the note you are editing — without opening the dashboard.

## Prerequisites

- [Obsidian](https://obsidian.md/) with this repo's vault open
- BLACKBOX running: `scripts\blackbox.bat start` (orchestrator on `http://127.0.0.1:8000`)

## Install (dev)

```powershell
cd apps\obsidian-plugin
npm install
npm run deploy
```

`deploy` builds `main.js` and copies it plus `manifest.json` into `vault/.obsidian/plugins/blackbox/`.

In Obsidian: **Settings → Community plugins → turn off Safe mode → enable BLACKBOX**.

## Settings

| Setting | Default | Notes |
|---------|---------|-------|
| Orchestrator URL | `http://127.0.0.1:8000` | Must match running appliance |
| API key | (empty) | Set if `BLACKBOX_API_KEY` is configured |

## Commands

- **BLACKBOX: Summarize active note** — runs `summarize_note` on the vault-relative path
- **BLACKBOX: Triage active note** — runs `inbox_triage`
- **BLACKBOX: Review pending approvals** — picker → draft review modal → approve/reject

## Status bar

Polls health and pending count every 30s: `BLACKBOX ok`, `degraded`, `offline`, or pending count.

## Build only

```powershell
npm run build    # production bundle → main.js (gitignored in source tree)
npm run typecheck
```

## API used

- `GET /api/v1/health`
- `GET /api/v1/skills/pending` (includes `draft`, `confidence`)
- `POST /api/v1/skills/execute` (requires `X-API-Key` when configured)
- `POST /api/v1/skills/approve`
