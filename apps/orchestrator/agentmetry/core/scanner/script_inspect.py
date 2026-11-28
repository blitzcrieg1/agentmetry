"""Hash and pattern-check a referenced script without keeping its contents.

Preflight v2 follows one execution step: when a declaration resolves to a
local script, the script is read as data (never executed), hashed, and checked
against a small set of conservative observation patterns. Only the hash and
the observation names leave this module; contents stay on the machine.
"""

from __future__ import annotations

import ast
import hashlib
import re

MAX_OBSERVATIONS = 8

# Text patterns are deliberately narrow and observation-only: they name a
# shape, they do not claim a verdict.
_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("download_pipe_to_shell", re.compile(
        r"(?:curl|wget)\b[^|\n]{0,200}\|\s*(?:sudo\s+|env\s+)*(?:ba|z|da|k)?sh\b", re.IGNORECASE)),
    ("base64_decode_pipe", re.compile(
        r"base64\s+(?:-d|--decode)\b[^|\n]{0,200}\|", re.IGNORECASE)),
    ("eval_of_substitution", re.compile(
        r"\beval\b[^;\n]{0,80}\$\(", re.IGNORECASE)),
    ("credential_key_path", re.compile(
        r"~/\.aws/credentials|~/\.ssh/id_|\bid_rsa\b", re.IGNORECASE)),
    ("persistence_file_write", re.compile(
        r"(?:>>?|\btee\b)\s*~/\.(?:bashrc|zshrc|profile)\b", re.IGNORECASE)),
    ("long_encoded_blob", re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")),
)

_PY_EVAL_NAMES = frozenset({"eval", "exec", "compile", "__import__"})
_PY_EXEC_ROOTS = ("os.system", "subprocess")
_PY_NETWORK_ROOTS = ("requests", "urllib", "httpx", "socket", "aiohttp")


def _dotted(func: ast.expr) -> str:
    parts: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _python_observations(tree: ast.Module) -> set[str]:
    """Module-level statements only; anything inside a def or class is skipped."""
    observations: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            dotted = _dotted(node.func)
            root = dotted.split(".", 1)[0]
            if root in _PY_EVAL_NAMES or dotted in _PY_EVAL_NAMES:
                observations.add("module_level_eval_call")
            elif any(dotted == r or dotted.startswith(r + ".") for r in _PY_EXEC_ROOTS):
                observations.add("module_level_subprocess_call")
            elif root in _PY_NETWORK_ROOTS:
                observations.add("module_level_network_call")
    return observations


def inspect_bytes(data: bytes, suffix: str) -> tuple[str, tuple[str, ...]]:
    """Return (sha256 hex, observation names) for a bounded script body."""
    digest = hashlib.sha256(data).hexdigest()
    observations: set[str] = set()
    if suffix == ".py":
        try:
            tree = ast.parse(data.decode("utf-8-sig", errors="replace"))
        except (SyntaxError, ValueError):
            observations.add("python_unparsed")
        else:
            observations |= _python_observations(tree)
    else:
        text = data.decode("utf-8-sig", errors="replace")
        for name, pattern in _TEXT_PATTERNS:
            if pattern.search(text):
                observations.add(name)
    return digest, tuple(sorted(observations)[:MAX_OBSERVATIONS])
