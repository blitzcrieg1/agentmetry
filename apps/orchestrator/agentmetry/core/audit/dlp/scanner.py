import json
import logging
import re
from typing import Any, Dict

from .models import DlpVerdict, DlpMatch
from .loader import load_dlp_rules
from ...config import settings

logger = logging.getLogger(__name__)

# Compiled-rule cache. Reset with reset_rules() (tests / live rule reload).
_COMPILED_RULES: list[tuple[re.Pattern[str], Any]] = []


def reset_rules() -> None:
    """Clear the compiled-rule cache so the next scan reloads from disk."""
    _COMPILED_RULES.clear()


def _init_rules() -> None:
    if _COMPILED_RULES:
        return
    rules = load_dlp_rules(settings.dlp_rules_path)
    for r in rules:
        if not settings.dlp_pii and r.category == "pii":
            continue
        try:
            _COMPILED_RULES.append((re.compile(r.pattern), r))
        except re.error as exc:
            logger.warning("[DLP] invalid regex for rule %s: %s", r.id, exc)


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum — rejects random 16-digit numbers that aren't real cards."""
    nums = [int(c) for c in digits if c.isdigit()]
    if len(nums) < 13:
        return False
    total, parity = 0, len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _passes_validator(rule: Any, matched_text: str) -> bool:
    if getattr(rule, "validate", "") == "luhn":
        return _luhn_ok(matched_text)
    return True


def scan(tool_qualified: str, arguments: Dict[str, Any] | str, mode: str | None = None) -> DlpVerdict:
    """Scan tool arguments against DLP rules. Returns all matches, not just the first.

    Validators (e.g. Luhn for card numbers) suppress false positives. Only rule
    metadata is returned — never the matched value.
    """
    if mode is None:
        mode = settings.dlp_mode
    if mode == "disable":
        return DlpVerdict(matched=False, mode=mode)

    _init_rules()
    if not _COMPILED_RULES:
        return DlpVerdict(matched=False, mode=mode)

    if isinstance(arguments, dict):
        try:
            text = json.dumps(arguments)
        except Exception:
            text = str(arguments)
    else:
        text = str(arguments)

    matches: list[DlpMatch] = []
    seen: set[str] = set()
    for pattern, rule in _COMPILED_RULES:
        m = pattern.search(text)
        if not m or not _passes_validator(rule, m.group(0)):
            continue
        if rule.id in seen:
            continue
        seen.add(rule.id)
        matches.append(DlpMatch(
            rule_id=rule.id,
            category=rule.category,
            severity=rule.severity,
            pattern_type="regex",
        ))

    if not matches:
        return DlpVerdict(matched=False, mode=mode)
    return DlpVerdict(matched=True, mode=mode, match=matches[0], matches=matches)
