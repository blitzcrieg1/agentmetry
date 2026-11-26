import yaml
from pathlib import Path
from typing import List

from .models import RuleMeta

#: libyaml where it is installed. The pure-Python parser was most of the hook's
#: runtime: the DLP and tool manifests are re-read by every hook process, and
#: parsing them took ~55 ms of an ~85 ms tool call (#171). Same SafeConstructor,
#: so the same Python objects, which `test_hook_import_cost.py` checks.
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

#: Rules planted by `agentmetry canary` live here, one file per plant, and are
#: merged after the built-in manifest. They are kept out of the packaged
#: manifest so an opt-in feature never ships in the default ruleset, and the
#: directory is read only when it exists: the hook loads this on every tool call
#: and #171 is the reason that path is kept short.
CANARY_RULES_DIR = Path.home() / ".agentmetry" / "canary"


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

    rules = _load_file(path)
    if CANARY_RULES_DIR.is_dir():
        for extra in sorted(CANARY_RULES_DIR.glob("*.yaml")):
            rules.extend(_load_file(extra))
    return rules
