from dataclasses import dataclass, field


@dataclass
class ToolPolicyRule:
    id: str
    action: str  # allow | deny
    tools: list[str] = field(default_factory=list)
    command_pattern: str = ""
    servers: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ToolPolicyMatch:
    rule_id: str
    action: str


@dataclass
class ToolPolicyVerdict:
    matched: bool
    blocked: bool
    mode: str = "disable"
    match: ToolPolicyMatch | None = None
