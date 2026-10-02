from dataclasses import dataclass, field


@dataclass
class ToolPolicyRule:
    id: str
    action: str  # allow | deny | ask
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
    #: A rule wants a human to decide. Never set together with `blocked`: deny
    #: outranks ask, so a call matching both is simply blocked.
    ask: bool = False
