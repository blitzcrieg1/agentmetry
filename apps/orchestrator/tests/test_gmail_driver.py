"""Gmail driver: auth hints, body extraction, reply drafts — Gmail API fully mocked."""

from __future__ import annotations

import base64
import importlib.util
import json
from email import message_from_bytes
from pathlib import Path
from typing import Any

import pytest

_SERVER = Path(__file__).resolve().parents[1] / "tools" / "gmail_server.py"

spec = importlib.util.spec_from_file_location("gmail_server", _SERVER)
gmail_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gmail_server)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


# ------------------------------------------------------- fake Gmail service


class _Req:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def execute(self) -> dict[str, Any]:
        return self._payload


class FakeGmail:
    """Mimics googleapiclient's chained users().threads()/drafts() shape."""

    def __init__(self, threads: dict[str, dict[str, Any]], listing: list[dict] | None = None):
        self.threads_by_id = threads
        self.listing = listing or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def users(self):
        return self

    def threads(self):
        return _Threads(self)

    def drafts(self):
        return _Drafts(self)


class _Threads:
    def __init__(self, svc: FakeGmail):
        self.svc = svc

    def list(self, **kwargs):
        self.svc.calls.append(("threads.list", kwargs))
        return _Req({"threads": self.svc.listing})

    def get(self, **kwargs):
        self.svc.calls.append(("threads.get", kwargs))
        return _Req(self.svc.threads_by_id[kwargs["id"]])


class _Drafts:
    def __init__(self, svc: FakeGmail):
        self.svc = svc

    def create(self, **kwargs):
        self.svc.calls.append(("drafts.create", kwargs))
        return _Req({"id": "draft-123"})

    def send(self, **kwargs):
        self.svc.calls.append(("drafts.send", kwargs))
        return _Req({"id": "msg-sent-1"})


def _message(headers: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {"mimeType": "text/plain", "body": {"data": _b64("hello")}}
    return {
        "payload": {
            "headers": [{"name": k, "value": v} for k, v in headers.items()],
            **body,
        }
    }


# ---------------------------------------------------------------------- auth


def test_missing_token_raises_setup_hint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gmail_server, "_load_credentials", lambda: None)
    with pytest.raises(RuntimeError, match="--auth"):
        gmail_server._get_service()


def test_client_config_requires_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="GMAIL_CLIENT_ID"):
        gmail_server._client_config()


# ------------------------------------------------------------ body handling


def test_strip_html():
    out = gmail_server._strip_html(
        "<div>Hi <b>there</b><br><script>evil()</script><p>Bye &amp; thanks</p></div>"
    )
    assert "Hi there" in out and "Bye & thanks" in out
    assert "evil" not in out and "<" not in out


def test_extract_body_prefers_plain_over_html():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>html version</p>")}},
            {"mimeType": "text/plain", "body": {"data": _b64("plain version")}},
        ],
    }
    assert gmail_server._extract_body(payload) == "plain version"


def test_extract_body_falls_back_to_stripped_html():
    payload = {"mimeType": "text/html", "body": {"data": _b64("<p>only html</p>")}}
    assert gmail_server._extract_body(payload) == "only html"


def test_get_thread_truncates_long_bodies(monkeypatch: pytest.MonkeyPatch):
    long_body = "x" * (gmail_server._MAX_BODY_CHARS + 500)
    svc = FakeGmail({
        "t1": {"messages": [_message(
            {"From": "a@x", "To": "b@x", "Subject": "S", "Date": "D"},
            {"mimeType": "text/plain", "body": {"data": _b64(long_body)}},
        )]}
    })
    monkeypatch.setattr(gmail_server, "_get_service", lambda: svc)
    out = gmail_server.get_thread("t1")
    assert "...[truncated]" in out
    assert len(out) < gmail_server._MAX_BODY_CHARS + 500


# --------------------------------------------------------------------- tools


def test_list_threads_clamps_limit_and_formats(monkeypatch: pytest.MonkeyPatch):
    svc = FakeGmail(
        threads={"t1": {"messages": [_message({"From": "maria@spa.example", "Subject": "Samples"})]}},
        listing=[{"id": "t1", "snippet": "about the sample kit"}],
    )
    monkeypatch.setattr(gmail_server, "_get_service", lambda: svc)

    out = gmail_server.list_threads(limit=99)

    list_call = next(kw for name, kw in svc.calls if name == "threads.list")
    assert list_call["maxResults"] == gmail_server._MAX_THREADS  # clamped
    assert "`t1`" in out and "maria@spa.example" in out and "Samples" in out


def test_create_draft_builds_threaded_reply(monkeypatch: pytest.MonkeyPatch):
    svc = FakeGmail({
        "t9": {"messages": [_message({
            "From": "maria@spa.example",
            "Subject": "Sample kit pricing",
            "Message-ID": "<abc@mail.example>",
        })]}
    })
    monkeypatch.setattr(gmail_server, "_get_service", lambda: svc)

    out = gmail_server.create_draft("t9", "Hi Maria — samples ship Friday.")
    assert "draft-123" in out

    create_call = next(kw for name, kw in svc.calls if name == "drafts.create")
    assert create_call["body"]["message"]["threadId"] == "t9"
    raw = base64.urlsafe_b64decode(create_call["body"]["message"]["raw"])
    mime = message_from_bytes(raw)
    assert mime["To"] == "maria@spa.example"
    assert mime["Subject"] == "Re: Sample kit pricing"
    assert mime["In-Reply-To"] == "<abc@mail.example>"
    assert "samples ship Friday" in mime.get_payload()


def test_create_draft_keeps_existing_re_prefix(monkeypatch: pytest.MonkeyPatch):
    svc = FakeGmail({
        "t2": {"messages": [_message({"From": "a@x", "Subject": "Re: ongoing", "Message-ID": "<m>"})]}
    })
    monkeypatch.setattr(gmail_server, "_get_service", lambda: svc)
    gmail_server.create_draft("t2", "body")
    raw = base64.urlsafe_b64decode(
        next(kw for n, kw in svc.calls if n == "drafts.create")["body"]["message"]["raw"]
    )
    assert message_from_bytes(raw)["Subject"] == "Re: ongoing"


def test_send_draft_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BLACKBOX_GMAIL_SEND_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="send_draft is disabled"):
        gmail_server.send_draft("draft-123")


def test_send_draft_calls_api_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BLACKBOX_GMAIL_SEND_ENABLED", "1")
    svc = FakeGmail(threads={})
    monkeypatch.setattr(gmail_server, "_get_service", lambda: svc)

    out = gmail_server.send_draft("draft-456")
    assert "msg-sent-1" in out
    send_call = next(kw for name, kw in svc.calls if name == "drafts.send")
    assert send_call["body"]["id"] == "draft-456"


def test_send_tool_shadow_exists_but_gated():
    """Phase 4-E: send_draft exists; default env keeps it off."""
    source = _SERVER.read_text(encoding="utf-8")
    assert "def send_draft" in source
    assert "BLACKBOX_GMAIL_SEND_ENABLED" in source
    assert "messages().send" not in source


# ------------------------------------------------------------ config & env


def _committed_drivers_json() -> str:
    """Shipped driver defaults — not the operator's local drivers.json flip."""
    repo_root = Path(__file__).resolve().parents[3]
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "show", "HEAD:vault/.system/drivers.json"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return (repo_root / "vault" / ".system" / "drivers.json").read_text(encoding="utf-8")


def test_gmail_driver_ships_disabled():
    config = json.loads(_committed_drivers_json())
    gmail = next(d for d in config["drivers"] if d["name"] == "gmail")
    assert gmail["enabled"] is False
    assert set(gmail["env_allow"]) == {
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "BLACKBOX_GMAIL_SEND_ENABLED",
    }


def test_env_allow_falls_back_to_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Documented setup puts client creds in apps/orchestrator/.env — pydantic
    never exports those to os.environ, so build_env must read the file."""
    import core.drivers.spec as spec_module
    from core.drivers.spec import DriverSpec

    env_file = tmp_path / ".env"
    env_file.write_text(
        'GMAIL_CLIENT_ID="from-dotenv"\n# comment\nGMAIL_CLIENT_SECRET=s3cret\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(spec_module, "_orchestrator_env_file", lambda: env_file)
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "from-environ")  # live env wins

    env = DriverSpec(
        name="gmail", command="x",
        env_allow=["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"],
    ).build_env()

    assert env["GMAIL_CLIENT_ID"] == "from-dotenv"      # .env fallback works
    assert env["GMAIL_CLIENT_SECRET"] == "from-environ"  # os.environ precedence
    assert "GEMINI_API_KEY" not in env                   # allowlist still scrubs
