import yaml
from pathlib import Path
from typing import List

from .models import RuleMeta

def load_dlp_rules(manifest_path: Path | str) -> List[RuleMeta]:
    """Load DLP rules from a YAML manifest file."""
    path = Path(manifest_path)
    if not path.exists():
        return []
    
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
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
