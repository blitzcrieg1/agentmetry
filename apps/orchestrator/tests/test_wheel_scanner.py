"""Synthetic wheel startup declarations. The archives are never installed."""

import hashlib
import json
from zipfile import ZIP_DEFLATED, ZipFile

from agentmetry.core.scanner import wheel

PREFIX = "example-1.0"
WHEEL_NAME = f"{PREFIX}-py3-none-any.whl"


def make_wheel(tmp_path, files):
    path = tmp_path / WHEEL_NAME
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{PREFIX}.dist-info/METADATA", "Metadata-Version: 2.1\nName: example\nVersion: 1.0\n")
        archive.writestr(f"{PREFIX}.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{PREFIX}.dist-info/RECORD", "")
        for name, contents in files.items():
            archive.writestr(name, contents)
    return path


def test_import_declarations_report_locations_without_code_or_paths(tmp_path):
    path = make_wheel(tmp_path, {"example.pth": (
        "# header\r\nsynthetic-path-value\r\nimport sys  # synthetic-private-text\r\n"
        "import\tmath\r\n  import random\r\n"
    )})

    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 1
    assert report.files == [wheel.StartupFile("example.pth", "pth", 1, 2, 1, 0, [3, 4, 5])]
    assert report.to_json()["coverage"] == "supported_locations_inspected"
    for rendered in (json.dumps(report.to_json()), "\n".join(report.lines())):
        assert "synthetic-path-value" not in rendered
        assert "synthetic-private-text" not in rendered
        assert "import random" not in rendered


def test_path_only_entries_do_not_raise_review(tmp_path):
    path = make_wheel(tmp_path, {
        "paths.pth": b"\xef\xbb\xbf# comment\nfirst_path\n\nsecond_path\rthird_path\n"
                     b"path_with_vertical_tab\x0bimport sys",
        ".hidden.pth": "import sys",
        "example/nested.pth": "import sys",
        f"{PREFIX}.data/scripts/script.pth": "import sys",
    })

    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 0
    assert report.files == [wheel.StartupFile("paths.pth", "pth", 4, 0, 0, 0, [])]


def test_detects_start_and_pth_in_wheel_site_directories(tmp_path):
    pure = f"{PREFIX}.data/purelib/example.start"
    platform = f"{PREFIX}.data/platlib/example.pth"
    path = make_wheel(tmp_path, {
        "example.start": "# Root\nexample.setup:initialize\n",
        pure: "\nexample.setup:begin\n",
        platform: "import sys\n",
    })

    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 1
    entries = {item.member: item for item in report.files}
    assert entries["example.start"] == wheel.StartupFile("example.start", "start", 0, 0, 0, 1, [2])
    assert entries[pure].entry_points == 1
    assert entries[platform].direct_imports == 1
    assert "example.setup" not in json.dumps(report.to_json())


def test_hash_check_does_not_establish_provenance(tmp_path):
    path = make_wheel(tmp_path, {})
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    matching = wheel.inspect_wheel(path, digest.upper())
    assert matching.exit_code() == 0
    assert matching.to_json()["provenance"] == "not_verified"
    assert matching.sha256 == digest
    assert matching.hash_check == "match"

    mismatch = wheel.inspect_wheel(path, "a" * 64)
    assert mismatch.exit_code() == 1
    assert mismatch.hash_check == "mismatch"

    invalid = wheel.inspect_wheel(path, "synthetic-invalid-digest")
    assert invalid.exit_code() == 2
    assert invalid.hash_check == "unavailable"
    assert "synthetic-invalid-digest" not in json.dumps(invalid.to_json())


def test_malformed_archive_is_incomplete(tmp_path):
    path = tmp_path / WHEEL_NAME
    path.write_text("synthetic-not-a-zip", encoding="utf-8")

    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 2
    assert report.unobserved == [{"reason": "invalid_archive"}]
    assert report.to_json()["coverage"] == "partial"


def test_missing_wheel_records_are_reported(tmp_path):
    path = tmp_path / WHEEL_NAME
    with ZipFile(path, "w") as archive:
        archive.writestr("paths.pth", "synthetic_paths")

    assert wheel.inspect_wheel(path).unobserved == [{"reason": "wheel_metadata_missing"}]


def test_unexpected_data_directory_is_still_inspected(tmp_path):
    member = "other-1.0.data/purelib/example.pth"
    report = wheel.inspect_wheel(make_wheel(tmp_path, {member: "import sys"}))

    assert report.exit_code() == 2
    assert report.needs_review
    assert report.files[0].member == member
    assert report.unobserved == [{"reason": "unexpected_wheel_data_directory", "member": member}]


def test_invalid_startup_text_does_not_hide_valid_declarations(tmp_path):
    path = make_wheel(tmp_path, {
        "bad.pth": b"\xff",
        "mixed.start": "synthetic-invalid-value\nexample.setup:initialize\n",
    })

    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 2
    assert report.needs_review
    assert report.files[0].declaration_lines == [2]
    assert report.unobserved == [
        {"reason": "unknown_startup_text_encoding", "member": "bad.pth"},
        {"reason": "unsupported_start_entry", "member": "mixed.start"},
    ]


def test_member_and_display_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(wheel, "MAX_STARTUP_BYTES", 80)
    monkeypatch.setattr(wheel, "MAX_PRINTED_LINES", 2)
    path = make_wheel(tmp_path, {
        "large.pth": b"x" * 81,
        "short.pth": "import sys\n" * 4,
    })

    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 2
    assert report.unobserved == [{"reason": "startup_read_limit_reached", "member": "large.pth"}]
    assert report.files[0].direct_imports == 4
    assert report.files[0].declaration_lines == [1, 2]


def test_directory_limit_does_not_index_archive(tmp_path, monkeypatch):
    path = make_wheel(tmp_path, {"paths.pth": "synthetic_paths"})
    monkeypatch.setattr(wheel, "MAX_MEMBERS", 3)

    def unexpected_archive(*args, **kwargs):
        raise AssertionError("the directory exceeded the limit before indexing")

    monkeypatch.setattr(wheel.zipfile, "ZipFile", unexpected_archive)
    report = wheel.inspect_wheel(path)

    assert report.exit_code() == 2
    assert report.unobserved == [{"reason": "directory_limit_reached"}]


def test_wheel_cli_supports_json_and_validates_options(tmp_path, capsys):
    from agentmetry.cli import main

    path = make_wheel(tmp_path, {"example.pth": "import sys"})
    assert main(["scan", "--wheel", str(path), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "wheel_startup"
    assert result["files"][0]["member"] == "example.pth"
    assert main(["scan", "--wheel", str(path), "--project", str(tmp_path)]) == 2
    assert main(["scan", "--expected-sha256", result["sha256"]]) == 2
