"""Recognize literal destinations of common shell writes without running commands.

This is deliberately a narrow policy helper, not a shell interpreter. It does
not resolve variables, cwd changes, aliases, subprocesses or arbitrary programs.
Quoted prose stays data. Python support reads literal AST arguments only.
"""

from __future__ import annotations

import ast
import shlex


def _unquote(word: str) -> str:
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "\"'":
        return word[1:-1]
    return word


def _python_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and node.args:
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
        )
        if name in {"Path", "PurePath", "PosixPath", "WindowsPath"}:
            return _python_path(node.args[0])
    return None


def _python_writes(program: str) -> list[str]:
    # The literal program is evidence to inspect, never code to execute. Bound
    # AST work separately from the hook's command classification budget.
    if len(program) > 16_384:
        return []
    try:
        tree = ast.parse(program)
    except (SyntaxError, RecursionError, ValueError):
        return []
    targets = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        method = call.func.attr if isinstance(call.func, ast.Attribute) else ""
        name = call.func.id if isinstance(call.func, ast.Name) else method
        path = None
        if method in {"write_text", "write_bytes", "touch"}:
            path = _python_path(call.func.value)
        elif method == "unlink" and _python_path(call.func.value) is not None:
            path = _python_path(call.func.value)
        elif name == "open":
            bound_path = (
                _python_path(call.func.value) if isinstance(call.func, ast.Attribute) else None
            )
            mode = next((k.value for k in call.keywords if k.arg == "mode"), None)
            if mode is None:
                index = 0 if bound_path is not None else 1
                mode = call.args[index] if len(call.args) > index else ast.Constant("r")
            if (
                isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and any(flag in mode.value for flag in "wax+")
            ):
                if bound_path is not None:
                    path = bound_path
                elif call.args:
                    path = _python_path(call.args[0])
        elif method in {"remove", "rmtree", "unlink", "rename", "replace"} and call.args:
            path = _python_path(call.args[0])
        if path is not None:
            targets.append(path)
    return targets


def _command_writes(words: list[str]) -> list[str]:
    if not words:
        return []
    # Quotes around a command word can execute too. Do not inspect the argument
    # of echo, printf or git commit as if it were another executable.
    verb = _unquote(words[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    args = [_unquote(word) for word in words[1:]]
    operands = [word for word in args if not word.startswith("-")]
    if verb in {"rm", "unlink", "rmdir", "tee", "truncate", "touch", "mv"}:
        return operands
    if verb in {"cp", "install"}:
        return operands[-1:]
    if verb == "sed" and any(
        word == "--in-place" or word.startswith("-i") or word.startswith("--in-place=")
        for word in args
    ):
        files = []
        has_script = False
        skip = False
        for word in args:
            if skip:
                skip = False
                continue
            if word in {"-e", "--expression", "-f", "--file"}:
                has_script, skip = True, True
            elif word.startswith(("--expression=", "--file=", "-e", "-f")):
                has_script = True
            elif not word.startswith("-"):
                files.append(word)
        return files if has_script else files[1:]
    if verb in {"python", "python3", "python.exe", "python3.exe"} and "-c" in args:
        index = args.index("-c") + 1
        return _python_writes(args[index]) if index < len(args) else []
    return []


_WORD_BREAKS = " \t\r\n;&|<>()"


def _strip_comments(command: str) -> str:
    """Remove what Bash treats as a comment: `#` at the start of a word, outside quotes.

    shlex starts a comment at any `#`, so `x=a#b; echo {} > file` lost the rest
    of the line, write included. A `#` inside a word, as in `$#`, a URL fragment
    or an assignment, is a literal in Bash and stays one here. A comment runs to
    the end of its line; the newline is kept, so the next line is still a new
    command.
    """
    out: list[str] = []
    quote = ""
    word_start = True
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            out.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(command):
                out.append(command[index + 1])
                index += 1
            elif char == quote:
                quote = ""
            word_start = False
        elif char == "\\" and index + 1 < len(command):
            out.append(command[index : index + 2])
            index += 1
            word_start = False
        elif char == "#" and word_start:
            end = command.find("\n", index)
            if end == -1:
                break
            index = end
            continue
        else:
            out.append(char)
            if char in "'\"":
                quote = char
            word_start = char in _WORD_BREAKS
        index += 1
    return "".join(out)


def literal_write_targets(command: str) -> list[str]:
    """Literal write/remove operands and output redirections in common commands.

    Non-POSIX mode preserves quotes, so `echo '> file'` cannot become a shell
    redirect. This intentionally does not claim to normalize shell syntax.
    """
    lexer = shlex.shlex(_strip_comments(command), posix=False, punctuation_chars=";&|<>()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    # Comments were removed the way Bash reads them; shlex's own rule is wrong.
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    targets = []
    words: list[str] = []
    index = 0
    while index < len(tokens):
        word = tokens[index]
        if word in {">", ">>", ">|", "&>"} and index + 1 < len(tokens):
            targets.append(_unquote(tokens[index + 1]))
            index += 2
            continue
        if word and all(char in ";&|()\n" for char in word):
            targets.extend(_command_writes(words))
            words = []
        else:
            words.append(word)
        index += 1
    targets.extend(_command_writes(words))
    return targets
