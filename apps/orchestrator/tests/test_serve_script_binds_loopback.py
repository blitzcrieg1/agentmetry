"""serve.bat binds loopback by default (pilot hardening item 12).

It bound 0.0.0.0, which put the API on every network the machine joined. LAN
access is mobile.bat's job, deliberately named and documented as such.
"""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def test_serve_bat_does_not_bind_every_interface():
    text = (SCRIPTS / "serve.bat").read_text(encoding="utf-8")
    assert "--host 0.0.0.0" not in text
    assert "set AGENTMETRY_BIND=127.0.0.1" in text
    assert "--host %AGENTMETRY_BIND%" in text


def test_the_lan_launcher_says_what_it_is():
    text = (SCRIPTS / "mobile.bat").read_text(encoding="utf-8")
    assert "LAN" in text.splitlines()[1]
