import logging
import re
from pathlib import Path
from typing import List

import yaml

from .models import RuleMeta

#: libyaml where it is installed. The pure-Python parser was most of the hook's
#: runtime: the DLP and tool manifests are re-read by every hook process, and
#: parsing them took ~55 ms of an ~85 ms tool call (#171). Same SafeConstructor,
#: so the same Python objects, which `test_hook_import_cost.py` checks.
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_BUNDLED_MANIFEST = Path(__file__).resolve().parents[3] / "policies" / "dlp" / "manifest.yaml"
logger = logging.getLogger(__name__)


def supports_canaries(path: Path) -> bool:
    """Operator-owned canaries only augment the bundled, unmanaged policy."""
    if path.absolute() != _BUNDLED_MANIFEST:
        return False
    from agentmetry.core.managed_policy import load_policy

    locked = load_policy().locked
    return not ({"dlp_mode", "dlp_rules_path"} & locked.keys())


def _canary_rules(path: Path) -> list[RuleMeta]:
    # Load the optional inventory only if it exists. It stores generated values
    # rather than arbitrary patterns, and a bad inventory cannot disable DLP.
    if path.absolute() != _BUNDLED_MANIFEST:
        return []
    try:
        from agentmetry.core import canary

        if not canary.STATE_FILE.exists() or not supports_canaries(path):
            return []
        return [
            RuleMeta(
                id=record["rule_id"],
                name="Agentmetry canary",
                description="A planted decoy value was observed in DLP input.",
                pattern="|".join(re.escape(value) for value in record["values"]),
                category="canary",
                severity="critical",
            )
            for record in canary.read_records(canary.STATE_FILE)
        ]
    except (OSError, ValueError, RuntimeError):
        logger.warning("Skipped unreadable canary state. Bundled DLP remains enabled.")
        return []


def _load_file(path: Path) -> List[RuleMeta]:
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.load(f, Loader=SAFE_LOADER)  # noqa: S506 - a safe loader

    if not data or "rules" not in data:
        return []

    rules = []
    for r in data["rules"]:
        rules.append(RuleMeta(
            id=r.get("id", ""),
            name=r.get("name", ""),
            description=r.get("description", ""),
            pattern=r.get("pattern", ""),
            category=r.get("category", ""),
            severity=r.get("severity", "medium")
        ))
    return rules


def load_dlp_rules(manifest_path: Path | str) -> List[RuleMeta]:
    """Load DLP rules from a YAML manifest file, plus any planted canaries."""
    path = Path(manifest_path)
    if not path.exists():
        return []

    return [*_load_file(path), *_canary_rules(path)]
