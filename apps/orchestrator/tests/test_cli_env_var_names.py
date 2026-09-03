"""The CLI tells operators which environment variable to set. It has to be real.

`agentmetry stats` spent an unknown number of releases telling anyone who hit a
disabled export to "enable AGENTMETRY_AUDIT_EXPORT". No such variable exists.
The only alias is `AGENTMETRY_AUDIT_EXPORT_ENABLED`, so an operator who followed
the instruction set something inert, saw the trail stay empty, and had nothing
to tell them why.

That is the worst shape of bug this project can ship: a recorder that is off,
and a message that convinces the operator it is on.

It was found by contrast. PR #139 added the same message to `agentmetry
detections` and named the variable correctly, which is the only reason anybody
looked at the older one.

So this walks every string the CLI prints, pulls out anything shaped like an
`AGENTMETRY_` variable, and checks it against the aliases `Settings` actually
declares. Names, not values: whether `=1` is the right value is a question for
the reader, but whether the variable exists is a question a test can settle.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from pydantic import AliasChoices

from agentmetry.core.config import Settings

PACKAGE = Path(__file__).resolve().parents[1] / "agentmetry"
CLI = PACKAGE / "cli" / "__init__.py"

# Deliberately broad. A variable named in a comment is documentation too, but
# only strings reach the operator, so only strings are scanned.
_VAR = re.compile(r"\bAGENTMETRY_[A-Z0-9_]+\b")

# Not every setting goes through `Settings`. `AGENTMETRY_AGT_HMAC_KEY` is read
# straight from the environment at the point of use, and it is no less real for
# that, so a name counts as declared if anything in the package reads it.
_DIRECT_READ = re.compile(
    r"os\.(?:environ(?:\.get)?\(|getenv\()\s*[\"'](AGENTMETRY_[A-Z0-9_]+)[\"']"
)


def _declared_aliases() -> set[str]:
    names: set[str] = set()
    for field in Settings.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(choice) for choice in alias.choices)
        elif alias:
            names.add(str(alias))
    for source in PACKAGE.rglob("*.py"):
        names.update(_DIRECT_READ.findall(source.read_text(encoding="utf-8")))
    return names


def _mentioned_in_printed_strings() -> dict[str, int]:
    """Every `AGENTMETRY_*` token inside a string literal, with its line."""
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for name in _VAR.findall(node.value):
                found.setdefault(name, node.lineno)
    return found


def test_every_environment_variable_the_cli_names_exists():
    declared = _declared_aliases()
    mentioned = _mentioned_in_printed_strings()
    assert mentioned, "no environment variables found in the CLI; this test has gone blind"

    unknown = {name: line for name, line in mentioned.items() if name not in declared}
    assert not unknown, (
        "the CLI names environment variables that Settings does not declare, so an "
        f"operator who sets them changes nothing: {unknown}"
    )


def test_the_specific_regression_stays_fixed():
    """`AGENTMETRY_AUDIT_EXPORT` without the suffix is the one that shipped."""
    source = CLI.read_text(encoding="utf-8")
    assert "AGENTMETRY_AUDIT_EXPORT_ENABLED" in source
    assert not re.search(r"AGENTMETRY_AUDIT_EXPORT(?!_ENABLED)", source), (
        "AGENTMETRY_AUDIT_EXPORT is not a real variable; the alias is "
        "AGENTMETRY_AUDIT_EXPORT_ENABLED"
    )
