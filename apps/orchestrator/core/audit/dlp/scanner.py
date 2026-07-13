import re
import json
from typing import Dict, Any

from .models import DlpVerdict, DlpMatch
from .loader import load_dlp_rules
from ...config import settings

# Global cache for compiled rules
_COMPILED_RULES = []

def _init_rules():
    global _COMPILED_RULES
    if _COMPILED_RULES:
        return
    
    rules = load_dlp_rules(settings.dlp_rules_path)
    for r in rules:
        if not settings.dlp_pii and r.category == "pii":
            continue
        try:
            pattern = re.compile(r.pattern)
            _COMPILED_RULES.append((pattern, r))
        except re.error as e:
            # Skip invalid regexes
            print(f"[DLP] Warning: invalid regex for rule {r.id}: {e}")

def scan(tool_qualified: str, arguments: Dict[str, Any] | str, mode: str = None) -> DlpVerdict:
    """
    Scans tool arguments against the DLP rules.
    If mode is 'disable', it immediately returns matched=False.
    """
    if mode is None:
        mode = settings.dlp_mode
        
    if mode == "disable":
        return DlpVerdict(matched=False, mode=mode)
        
    _init_rules()
    
    if not _COMPILED_RULES:
        return DlpVerdict(matched=False, mode=mode)
        
    # Serialize arguments to a single searchable string
    if isinstance(arguments, dict):
        try:
            text_to_scan = json.dumps(arguments)
        except Exception:
            text_to_scan = str(arguments)
    else:
        text_to_scan = str(arguments)
        
    for pattern, rule_meta in _COMPILED_RULES:
        if pattern.search(text_to_scan):
            match = DlpMatch(
                rule_id=rule_meta.id,
                category=rule_meta.category,
                severity=rule_meta.severity,
                pattern_type="regex"
            )
            return DlpVerdict(matched=True, mode=mode, match=match)
            
    return DlpVerdict(matched=False, mode=mode)
