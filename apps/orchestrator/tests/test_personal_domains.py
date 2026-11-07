"""The personal and corporate labels on the Identity page."""

from __future__ import annotations

import pytest

from agentmetry.core.audit.identity_view import build_identity_view
from agentmetry.core.audit.personal_domains import PERSONAL_DOMAINS, account_kind, is_personal_domain


@pytest.mark.parametrize(
    "domain",
    [
        "gmail.com",
        "GMAIL.COM",
        "googlemail.com",
        "hotmail.com",
        "hotmail.co.uk",
        "hotmail.fr",
        "hotmail.com.br",
        "outlook.com",
        "outlook.de",
        "live.com",
        "live.co.uk",
        "msn.com",
        "yahoo.com",
        "yahoo.gr",
        "yahoo.co.jp",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "pm.me",
        "tutanota.com",
        "gmx.de",
        "gmx.net",
        "web.de",
        "mail.ru",
        "yandex.ru",
        "yandex.com",
        "zoho.com",
        "qq.com",
        "163.com",
        "naver.com",
        "otenet.gr",
    ],
)
def test_public_providers_are_personal(domain: str):
    assert is_personal_domain(domain)
    assert account_kind(domain) == "personal"


@pytest.mark.parametrize(
    "domain",
    [
        "company.example",
        "acme-corp.example",
        "gmail.com.evil.test",
        "notgmail.com",
        "gmail.company.com",
        "outlook.company.com",
        "yahoo.company.example",
        "hotmail.internal.corp",
        "live.company.com",
        "liveperson.com",
    ],
)
def test_a_company_domain_or_look_alike_is_not_personal(domain: str):
    assert not is_personal_domain(domain)
    assert account_kind(domain) == "corporate"


def test_a_subdomain_of_a_provider_still_belongs_to_it():
    assert is_personal_domain("alumni.gmail.com")


def test_no_domain_is_unclassified_rather_than_guessed():
    assert account_kind("") == "unclassified"
    assert not is_personal_domain("")


def test_the_list_holds_only_clean_lowercase_domains():
    for domain in PERSONAL_DOMAINS:
        assert domain == domain.strip().lower()
        assert "." in domain
        assert "@" not in domain


def _row(**kw) -> dict:
    return {
        "source_app": "cursor",
        "action_type": "tool_called",
        "action_outcome": "success",
        "correlation_id": "s1",
        "timestamp_utc": "2026-11-07T10:00:00+00:00",
        "adapter": "cursor_hook",
        "account_source": "hook_payload",
        **kw,
    }


def test_the_view_labels_and_counts_each_kind():
    view = build_identity_view(
        [
            _row(domain="gmail.com"),
            _row(domain="hotmail.com", correlation_id="s2"),
            _row(domain="company.example", correlation_id="s3"),
            _row(source_app="codex", adapter="codex_hook", account_id="workspace-1", correlation_id="s4"),
        ],
        days=7,
    )
    kinds = {a["domain"] or a["account_id"]: a["kind"] for a in view["accounts"]}
    assert kinds == {
        "gmail.com": "personal",
        "hotmail.com": "personal",
        "company.example": "corporate",
        "workspace-1": "unclassified",
    }
    assert view["counts"] == {"personal": 2, "corporate": 1, "unclassified": 1}
