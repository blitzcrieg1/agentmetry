"""Package names that imitate well-known ones.

An agent told to "install the requests library" types what it was told, and an
MCP config copied from a forum runs whatever name it holds. A package one
keystroke from a popular one, or a popular MCP server's name with its scope
dropped, is the cheapest supply-chain attack there is, and it is visible from
the name alone, before anything is fetched.

What a finding says is "this resembles X; check it is the package you meant".
It never says the package is malicious: plenty of near-names are legitimate,
which is also why an exact match against the known list is never flagged and
why short names get a tighter threshold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentmetry.core.scanner.known_packages import NPM, PYPI

ECOSYSTEMS = ("npm", "pypi")

#: Names this short collide by accident: `ws`, `six`, `idna`. One edit only.
_SHORT = 5


@dataclass(frozen=True)
class SquatFinding:
    package: str
    ecosystem: str
    kind: str  # near_known | scope_dropped | scope_lookalike | separator_variant
    resembles: str
    distance: int

    def sentence(self) -> str:
        what = {
            "near_known": f"{self.distance} edit{'s' if self.distance != 1 else ''} from",
            "scope_dropped": "the name of the scoped package",
            "scope_lookalike": "a lookalike scope of",
            "separator_variant": "the same letters as",
        }[self.kind]
        return f"{self.package} ({self.ecosystem}) is {what} {self.resembles}; check it is the package you meant"


def _distance(a: str, b: str, limit: int) -> int:
    """Optimal string alignment distance (a transposition is one edit), capped at limit + 1."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


_VERSION = re.compile(r"(?<=.)@[^/@]*$|[=<>!~;\[].*$")


def normalise(name: str, ecosystem: str) -> str:
    """The bare package name: version and extras gone, lower case.

    PyPI treats `-`, `_` and `.` as the same character (PEP 503), so those are
    folded there and two spellings of one package are one name. npm does not,
    so they are kept, and a separator-only difference is its own finding.
    """
    bare = _VERSION.sub("", name.strip()).strip().lower()
    if ecosystem == "pypi":
        bare = re.sub(r"[-_.]+", "-", bare)
    return bare


def check(name: str, ecosystem: str, extra_known: frozenset[str] = frozenset()) -> SquatFinding | None:
    """A finding when `name` imitates a known package, else None."""
    if ecosystem not in ECOSYSTEMS:
        raise ValueError(f"unknown ecosystem: {ecosystem}")
    known = {normalise(k, ecosystem) for k in (NPM if ecosystem == "npm" else PYPI) | extra_known}
    pkg = normalise(name, ecosystem)
    if not pkg or pkg in known:
        return None

    if ecosystem == "npm":
        scope, _, base = pkg.rpartition("/")
        for k in sorted(known):
            k_scope, _, k_base = k.rpartition("/")
            if not k_scope:
                continue
            if not scope and base == k_base:
                return SquatFinding(pkg, ecosystem, "scope_dropped", k, 0)
            if scope and base == k_base and scope != k_scope and _distance(scope, k_scope, 2) <= 2:
                return SquatFinding(pkg, ecosystem, "scope_lookalike", k, _distance(scope, k_scope, 2))
        folded = re.sub(r"[-_.]", "", pkg)
        for k in sorted(known):
            if re.sub(r"[-_.]", "", k) == folded:
                return SquatFinding(pkg, ecosystem, "separator_variant", k, 0)

    # Two- and three-letter names sit one edit from each other by accident
    # (`ws`, `wz`, `six`, `sx`); a near-miss there is noise, not a signal.
    if len(pkg) <= 3:
        return None
    limit = 1 if len(pkg) <= _SHORT else 2
    best: SquatFinding | None = None
    for k in sorted(known):
        d = _distance(pkg, k, limit)
        if 0 < d <= limit and (best is None or d < best.distance):
            best = SquatFinding(pkg, ecosystem, "near_known", k, d)
    return best
