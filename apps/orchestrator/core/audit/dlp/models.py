from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuleMeta:
    id: str
    name: str
    description: str
    pattern: str
    category: str
    severity: str
    validate: str = ""  # optional validator: "luhn" for card numbers


@dataclass
class DlpMatch:
    rule_id: str
    category: str
    severity: str
    pattern_type: str = "regex"


@dataclass
class DlpVerdict:
    matched: bool
    mode: str = "disable"  # log, block, disable
    match: Optional[DlpMatch] = None  # first match (back-compat)
    matches: list[DlpMatch] = field(default_factory=list)  # all matches
