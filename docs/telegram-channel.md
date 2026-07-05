# Telegram channel — reach BLACKBOX from your phone

Phase 1 of the channel layer: message the OS from anywhere, approve drafts with
a button press, capture thoughts into the vault. Ships **disabled** — like the
gmail and search drivers, nothing listens until you turn it on.

## What it does

| You send | BLACKBOX does |
|---|---|
| `/skill customer_reply thread:abc` | Runs the skill at interactive priority, replies with the outcome |
| `/pending` | Lists threads waiting at the human gate, with Approve/Reject buttons |
| `/approve 3fa8b2c1` (or button) | Resumes the paused graph — same path as the dashboard modal |
| `/reject 3fa8b2c1` | Terminates the thread, writes the crash report |
| `/status` | Run counters, total cost, today's Flash budget |
| `/skills` | Registered skill names |
| Free text | Filed to `00-Inbox/telegram-<stamp>.md` → existing vault triggers fire |

And it pushes to you:

- **Approval gates from any surface** (vault trigger, cron, dashboard) arrive
  on your phone with Approve/Reject buttons. This is the loop-closer: a cron
  `customer_reply` run can pause at 08:05 and you approve it from the bus.
- **Autonomous run outcomes** (`autonomous-*` sessions): completions with cost
  and archive path, failures with the error.

Runs you start from Telegram are answered in the same chat, synchronously.

## Governance unchanged

The adapter never touches the LLM. Every message becomes a normalized
`InboundMessage` routed through the same `run_skill()` / `resolve_approval()`
path as the dashboard and vault triggers — IVT gates, budget admission, audit
bus, closeout archiving all apply. Only allowlisted chat ids are served;
everything else is logged and dropped. Long polling means no public webhook,
no open port on your machine.

## Setup (~10 minutes)

1. **Create the bot:** message [@BotFather](https://t.me/botfather) →
   `/newbot` → pick a name → copy the token.
2. **Find your chat id:** message your new bot once (it can't message you
   first), then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   in a browser — your numeric chat id is at `result[0].message.chat.id`.
3. **Configure** `apps/orchestrator/.env`:

   ```env
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token
   BLACKBOX_TELEGRAM_ALLOWED_CHAT_IDS=123456789
   BLACKBOX_CHANNEL_TELEGRAM_ENABLED=true
   ```

   Multiple operators: comma-separate the chat ids. An empty allowlist
   refuses to start — there is no "open to everyone" mode.
4. **Restart** the orchestrator (`scripts\blackbox.bat start`). The log should
   show `Telegram channel started (1 allowed chat(s))`.
5. **Smoke test:** send `/status`, then free text (check `00-Inbox/`), then
   run a gated skill and approve it from the buttons.

## Notes

- Button presses are just commands: `callback_data` is `/approve <prefix>`,
  re-routed exactly as if you typed it.
- Thread ids match by prefix — the first 8 characters shown in prompts are
  enough; ambiguity gets you the candidate list instead of a guess.
- Draft previews are truncated (700 chars) to keep messages readable; the full
  draft lives in the dashboard and the active-loop note.
- If the network drops, the poller backs off 5s and retries forever; missed
  push events are bounded by a 256-event queue (oldest dropped).
