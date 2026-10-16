"""The Antigravity conversation blob yields the tool call, not a guess."""

import json

from agentmetry.core.audit.antigravity_trajectory import iter_tool_calls


def _frame(name: str, args: dict) -> bytes:
    body = json.dumps(args, separators=(",", ":")).encode()
    length = len(body)
    encoded = bytearray()
    while True:
        piece = length & 0x7F
        length >>= 7
        if length:
            encoded.append(piece | 0x80)
        else:
            encoded.append(piece)
            break
    return b"\x12" + bytes([len(name)]) + name.encode() + b"\x1a" + bytes(encoded) + body


def test_a_run_command_frame_returns_the_command():
    blob = b"\x00\x01" + _frame("run_command", {"CommandLine": "git status", "Cwd": "C:/repo"})
    found = list(iter_tool_calls(blob))
    assert found == [("run_command", {"CommandLine": "git status", "Cwd": "C:/repo"})]


def test_a_view_file_frame_is_not_dropped():
    blob = _frame("view_file", {"AbsolutePath": "C:/repo/README.md"})
    assert list(iter_tool_calls(blob))[0][0] == "view_file"


def test_noise_without_the_framing_yields_nothing():
    assert list(iter_tool_calls(b'{"tool":"run_command"}')) == []
