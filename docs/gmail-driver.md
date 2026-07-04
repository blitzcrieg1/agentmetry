# Gmail driver — read + create_draft (never sends)

The `gmail` MCP driver reads threads and creates **reply drafts**. It exposes
no send tool — drafts wait in your Gmail Drafts folder for you to review and
send by hand. Ships `enabled: false`.

## What goes where (security model)

| Secret | Location | Why |
|--------|----------|-----|
| OAuth client id/secret | `apps/orchestrator/.env` (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`) | Reaches the driver subprocess only via `env_allow` |
| Refresh/access token | **Windows Credential Manager** (keyring service `blackbox-gmail`) | Never touches `.env` or the repo |

## 1. Google Cloud setup (one time, ~5 min)

1. https://console.cloud.google.com → create/select a project
2. **APIs & Services → Library** → enable **Gmail API**
3. **OAuth consent screen** → External → add your own Gmail as a **test user**
   (stays in "Testing" mode — fine for personal use, no verification needed)
4. **Credentials → Create credentials → OAuth client ID → Desktop app**
5. Copy the client ID and secret into `apps/orchestrator/.env`:

```
GMAIL_CLIENT_ID=xxxx.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=xxxx
```

## 2. One-time auth (browser opens once)

```powershell
cd apps\orchestrator
$env:GMAIL_CLIENT_ID = "xxxx.apps.googleusercontent.com"
$env:GMAIL_CLIENT_SECRET = "xxxx"
.\.venv\Scripts\python.exe tools\gmail_server.py --auth
```

A browser opens on a localhost loopback redirect; grant read + compose. On
success: `Gmail token stored in the OS keyring (service 'blackbox-gmail')`.
Verify under **Windows Credential Manager → Windows Credentials →
blackbox-gmail**. Tokens refresh automatically afterwards.

## 3. Enable the driver

In `vault/.system/drivers.json`, set the `gmail` entry to `"enabled": true`
(**do not commit this flip**), then:

```powershell
scripts\blackbox.bat start
curl -X POST http://127.0.0.1:8000/api/v1/drivers/remount -H "X-API-Key: %BLACKBOX_API_KEY%"
curl http://127.0.0.1:8000/api/v1/drivers/
#   expect: gmail -> "mounted", tools gmail.list_threads / get_thread / create_draft
```

## 4. Smoke test (read-only first)

Skills opt in per tool. A future `customer_reply` skill would declare:

```yaml
tools:
  - gmail.list_threads
  - gmail.get_thread
  - gmail.create_draft
```

Until then, confirm the mount via `GET /api/v1/drivers/` and watch
`run/tool_called` events in the dashboard when a skill first uses it.

## Scope guarantees

- **No send:** the server defines exactly three tools; none send mail. The
  `gmail.compose` scope could technically send, but nothing in BLACKBOX calls
  it — and every tool call is allowlisted per skill and audited on the bus.
- **Caps:** max 20 threads per list; bodies truncated at 8k chars; HTML
  stripped to text.
- Missing/expired token → clear error naming the `--auth` command; the driver
  never opens a browser on its own during a run.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `GMAIL_CLIENT_ID ... not set` during `--auth` | Export both vars in the same shell |
| `Gmail token missing or expired` on tool call | Re-run step 2 (e.g. after revoking access) |
| Driver `failed` in `/api/v1/drivers/` | Check `data/logs/orchestrator.log`; usually deps — `pip install -e ".[dev]"` |
| Browser opens but redirect fails | Firewall blocking localhost loopback; retry, or free the chosen port |
