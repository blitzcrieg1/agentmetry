"""gmail — read + create_draft MCP driver. Never sends.

Mounted from vault/.system/drivers.json (ships disabled). OAuth refresh tokens
live in the OS keyring (Windows Credential Manager), never in .env — only the
OAuth *client* id/secret cross into this process via env_allow.

One-time auth (see docs/gmail-driver.md):

    set GMAIL_CLIENT_ID=...        (or put both in apps/orchestrator/.env)
    set GMAIL_CLIENT_SECRET=...
    .venv\\Scripts\\python.exe tools\\gmail_server.py --auth

Scopes: gmail.readonly + gmail.compose. The compose scope technically permits
sending, but this server exposes no send tool — drafts only, by design.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import os
import re
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("gmail")

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
_KEYRING_SERVICE = "blackbox-gmail"
_KEYRING_USER = "oauth"
_MAX_THREADS = 20
_MAX_BODY_CHARS = 8_000

_AUTH_HINT = (
    "Gmail token missing or expired — run the one-time auth: "
    "`.venv\\Scripts\\python.exe tools\\gmail_server.py --auth` with "
    "GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET set (see docs/gmail-driver.md)"
)


# ------------------------------------------------------------------- helpers


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _extract_body(payload: dict[str, Any]) -> str:
    """Prefer text/plain; fall back to stripped text/html; walk nested parts."""
    mime = payload.get("mimeType", "")
    data = (payload.get("body") or {}).get("data")
    if data and mime.startswith("text/plain"):
        return _decode_part(data)
    if data and mime.startswith("text/html"):
        return _strip_html(_decode_part(data))
    plain, html = "", ""
    for part in payload.get("parts") or []:
        found = _extract_body(part)
        if not found:
            continue
        if part.get("mimeType", "").startswith("text/plain") and not plain:
            plain = found
        elif not html:
            html = found
    return plain or html


def _header(message: dict[str, Any], name: str) -> str:
    for header in (message.get("payload") or {}).get("headers") or []:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _truncate(text: str, limit: int = _MAX_BODY_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def _build_reply_mime(
    to: str,
    subject: str,
    body: str,
    in_reply_to: str = "",
) -> str:
    """RFC 2822 reply message, base64url-encoded for the Gmail API."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ---------------------------------------------------------------------- auth


def _load_credentials():
    import keyring

    blob = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
    if not blob:
        return None
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(json.loads(blob), _SCOPES)


def _save_credentials(creds) -> None:
    import keyring

    keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, creds.to_json())


def _load_orchestrator_dotenv() -> None:
    """Load apps/orchestrator/.env into os.environ (setdefault — shell wins)."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _client_config() -> dict[str, Any]:
    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET not set — create Desktop-app "
            "OAuth credentials in Google Cloud and export both (docs/gmail-driver.md)"
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1"],
        }
    }


def run_auth_flow() -> None:
    """One-time interactive OAuth (loopback redirect); token -> OS keyring."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_client_config(), scopes=_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_credentials(creds)
    print("Gmail token stored in the OS keyring (service 'blackbox-gmail').")


def _get_service():
    """Authenticated Gmail API client; refreshes and re-stores as needed."""
    creds = _load_credentials()
    if creds is None:
        raise RuntimeError(_AUTH_HINT)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            _save_credentials(creds)
        else:
            raise RuntimeError(_AUTH_HINT)
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------- tools


@server.tool()
def list_threads(label: str = "INBOX", limit: int = 10) -> str:
    """List recent Gmail threads for a label: id, from, subject, snippet."""
    limit = max(1, min(int(limit), _MAX_THREADS))
    svc = _get_service()
    listing = (
        svc.users().threads().list(userId="me", labelIds=[label], maxResults=limit).execute()
    )
    threads = listing.get("threads") or []
    if not threads:
        return f"(no threads in {label})"

    lines = []
    for item in threads:
        detail = (
            svc.users()
            .threads()
            .get(userId="me", id=item["id"], format="metadata",
                 metadataHeaders=["Subject", "From"])
            .execute()
        )
        first = (detail.get("messages") or [{}])[0]
        lines.append(
            f"- `{item['id']}` | {_header(first, 'From')} | "
            f"{_header(first, 'Subject')}\n  {item.get('snippet', '')}"
        )
    return "\n".join(lines)


@server.tool()
def get_thread(thread_id: str) -> str:
    """Full thread as plain text: every message's from/to/subject/date/body."""
    svc = _get_service()
    detail = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()

    blocks = []
    for message in detail.get("messages") or []:
        body = _truncate(_extract_body(message.get("payload") or {}))
        blocks.append(
            f"### From: {_header(message, 'From')}\n"
            f"To: {_header(message, 'To')}\n"
            f"Date: {_header(message, 'Date')}\n"
            f"Subject: {_header(message, 'Subject')}\n\n{body}"
        )
    return "\n\n---\n\n".join(blocks) if blocks else "(empty thread)"


@server.tool()
def create_draft(thread_id: str, body: str, subject: str | None = None) -> str:
    """Create a reply DRAFT in a thread (never sends). Returns the draft id."""
    svc = _get_service()
    detail = svc.users().threads().get(userId="me", id=thread_id, format="metadata",
                                       metadataHeaders=["Subject", "From", "Message-ID"]).execute()
    messages = detail.get("messages") or []
    if not messages:
        raise RuntimeError(f"Thread {thread_id} has no messages to reply to")
    last = messages[-1]

    reply_to = _header(last, "From")
    original_subject = _header(last, "Subject")
    reply_subject = subject or (
        original_subject if original_subject.lower().startswith("re:")
        else f"Re: {original_subject}"
    )
    raw = _build_reply_mime(
        to=reply_to,
        subject=reply_subject,
        body=body,
        in_reply_to=_header(last, "Message-ID"),
    )
    draft = (
        svc.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw, "threadId": thread_id}})
        .execute()
    )
    return f"Draft created (id `{draft.get('id')}`) — review and send from Gmail."


def _send_enabled() -> bool:
    return os.environ.get("BLACKBOX_GMAIL_SEND_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@server.tool()
def send_draft(draft_id: str) -> str:
    """Send an existing Gmail draft (Phase 4-E — disabled until operator unlock).

    Requires BLACKBOX_GMAIL_SEND_ENABLED=1 on the orchestrator after the
    4-green-week dogfood gate. Prefer create_draft + manual send until then.
    """
    if not _send_enabled():
        raise RuntimeError(
            "send_draft is disabled — complete 4 green dogfood weeks, then set "
            "BLACKBOX_GMAIL_SEND_ENABLED=1 (see docs/gmail-driver.md)"
        )
    svc = _get_service()
    sent = svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    message_id = sent.get("id", draft_id)
    return f"Message sent (id `{message_id}`) — audited on the event outbox."


if __name__ == "__main__":
    if "--auth" in sys.argv:
        _load_orchestrator_dotenv()
        run_auth_flow()
    else:
        server.run()
