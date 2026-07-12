# Taking the search driver live (10 minutes)

The `search` MCP driver and the `supplier_research` skill ship **disabled** and
have only mocked test coverage. This is the one-time procedure to prove real
bytes move — useful before enabling `supplier_research` or `kbeauty_trend_research` example skills.

## 1. Get a key

Either provider works (Serper is preferred when both are set):

- **Serper** — https://serper.dev (free tier, generous)
- **Tavily** — https://tavily.com

## 2. Put the key in the orchestrator env

Add to `apps/orchestrator/.env` (gitignored):

```
SERPER_API_KEY=your_key_here
# or
TAVILY_API_KEY=your_key_here
```

## 3. Enable the driver

Edit `vault/.system/drivers.json`, set the `search` entry to `"enabled": true`.
Leave `env_allow` as `["SERPER_API_KEY", "TAVILY_API_KEY"]` — that is what lets
the key cross into the driver subprocess (nothing else does).

**Do not commit this flip** — the repo ships the driver disabled on purpose.

## 4. Remount and confirm

```powershell
scripts\blackbox.bat start
# then, in another shell:
curl -X POST http://127.0.0.1:8000/api/v1/drivers/remount -H "X-API-Key: %BLACKBOX_API_KEY%"
curl http://127.0.0.1:8000/api/v1/drivers/
#   expect: search -> state "mounted", tools include search.web
```

## 5. Run the skill end to end

Dashboard → Armory → **Supplier Research**, or:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/skills/execute ^
  -H "Content-Type: application/json" -H "X-API-Key: %BLACKBOX_API_KEY%" ^
  -d "{\"skill_name\":\"supplier_research\",\"user_input\":\"korean snail mucin skincare\",\"session_id\":\"live\"}"
```

`supplier_research` gates on human approval before finalizing — approve from the
dashboard or the Obsidian "Review pending approvals" command. Result lands in
`vault/30-Archive/`.

## 6. Optional: the opt-in live test

```powershell
$env:BLACKBOX_LIVE_TESTS = "1"   # SERPER/TAVILY key already in shell env
cd apps\orchestrator
.\.venv\Scripts\python.exe -m pytest -q tests/test_search_live.py
```

Normal CI never runs this (skipped without both flags), so the suite stays at
129 and does not depend on a network or a key.

## 7. Turn it back off (optional)

Set `search` back to `"enabled": false` in `drivers.json` and remount when you
are done experimenting — autonomous skills should not silently depend on a paid
search key until you decide to keep it on.
