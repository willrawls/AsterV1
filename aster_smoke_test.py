#!/usr/bin/env python3
"""
Aster Export Smoke Test
=======================

Purpose
-------
Validate a minimal Aster export folder before sharing, archiving, or importing it.

This script checks:
  1. export_dir exists.
  2. manifest.json exists and parses as JSON.
  3. manifest.json contains required keys: version, files.
  4. manifest.files contains persona and continuity.
  5. persona file exists.
  6. continuity JSONL file exists.
  7. continuity JSONL parses line-by-line as JSON.
  8. each continuity record contains at least one identifying key:
       seed_id, iso_date, content_hash
  9. optional SHA-256 hash check:
       if manifest.files.continuity_hash is present, it must match the
       computed SHA-256 hash of the continuity file.

Expected folder shape
---------------------
Your export folder should look roughly like this:

  aster_export/
    manifest.json
    persona.json
    continuity.jsonl

Minimal manifest.json example
-----------------------------
{
  "version": "1.0",
  "files": {
    "persona": "persona.json",
    "continuity": "continuity.jsonl"
  },
  "meta": {
    "display_name": "Aster"
  }
}

Optional hash-protected manifest.json example
---------------------------------------------
{
  "version": "1.0",
  "files": {
    "persona": "persona.json",
    "continuity": "continuity.jsonl",
    "continuity_hash": "PUT_SHA256_HASH_HERE"
  },
  "meta": {
    "display_name": "Aster"
  }
}

Example continuity.jsonl
------------------------
Each line must be a valid JSON object:

{"seed_id":"s1","iso_date":"2026-06-08T00:00:00Z","content_hash":"sha256:abc","note":"first seed"}
{"seed_id":"s2","iso_date":"2026-06-09T00:00:00Z","content_hash":"sha256:def","note":"second seed"}

How to run
----------
Mac/Linux:

  python3 aster_smoke_test.py /path/to/aster_export

Windows PowerShell:

  py .\aster_smoke_test.py C:\path\to\aster_export

Exit codes
----------
  0 = pass
  2 = validation failure

Create a quick test export
--------------------------
Mac/Linux:

  tmp=$(mktemp -d)
  echo '{"version":"1.0","files":{"persona":"persona.json","continuity":"continuity.jsonl"},"meta":{"display_name":"test"}}' > "$tmp/manifest.json"
  echo '{"display_name":"test"}' > "$tmp/persona.json"
  echo '{"seed_id":"s1","iso_date":"2026-06-08T00:00:00Z","content_hash":"sha256:abc"}' > "$tmp/continuity.jsonl"
  python3 aster_smoke_test.py "$tmp"

Windows PowerShell:

  $tmp = New-Item -ItemType Directory -Path "$env:TEMP\aster_export_test" -Force
  '{"version":"1.0","files":{"persona":"persona.json","continuity":"continuity.jsonl"},"meta":{"display_name":"test"}}' | Set-Content "$tmp\manifest.json"
  '{"display_name":"test"}' | Set-Content "$tmp\persona.json"
  '{"seed_id":"s1","iso_date":"2026-06-08T00:00:00Z","content_hash":"sha256:abc"}' | Set-Content "$tmp\continuity.jsonl"
  py .\aster_smoke_test.py "$tmp"
"""

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict


REQUIRED_MANIFEST_KEYS = ("version", "files")
REQUIRED_FILE_KEYS = ("persona", "continuity")
IDENTIFYING_CONTINUITY_KEYS = ("seed_id", "iso_date", "content_hash")


def sha256_hex(path: str) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pass_msg(message: str) -> None:
    print(f"OK: {message}")


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(2)


def load_json_file(path: str, label: str) -> Dict[str, Any]:
    """Load a JSON file and ensure the top-level value is an object."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail(f"{label} missing: {path}")
    except json.JSONDecodeError as exc:
        fail(f"{label} JSON parse error at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except OSError as exc:
        fail(f"could not read {label}: {exc}")

    if not isinstance(data, dict):
        fail(f"{label} must contain a top-level JSON object")

    return data


def resolve_export_path(export_dir: str, relative_path: str, label: str) -> str:
    """Resolve a manifest path while preventing accidental absolute paths."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        fail(f"manifest.files.{label} must be a non-empty string")

    if os.path.isabs(relative_path):
        fail(f"manifest.files.{label} must be relative, not absolute: {relative_path}")

    normalized = os.path.normpath(relative_path)

    if normalized.startswith("..") or os.path.isabs(normalized):
        fail(f"manifest.files.{label} must stay inside export_dir: {relative_path}")

    return os.path.join(export_dir, normalized)


def validate_continuity_jsonl(path: str) -> int:
    """Validate JSONL continuity file and return record count."""
    count = 0

    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()

                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    fail(
                        "continuity JSONL parse error "
                        f"on line {line_number}, column {exc.colno}: {exc.msg}"
                    )

                if not isinstance(record, dict):
                    fail(f"continuity line {line_number} must be a JSON object")

                if not any(key in record for key in IDENTIFYING_CONTINUITY_KEYS):
                    required = ", ".join(IDENTIFYING_CONTINUITY_KEYS)
                    fail(
                        f"continuity line {line_number} lacks an identifying key. "
                        f"Expected at least one of: {required}"
                    )

                count += 1
    except FileNotFoundError:
        fail(f"continuity file missing: {path}")
    except OSError as exc:
        fail(f"could not read continuity file: {exc}")

    if count == 0:
        fail("continuity JSONL contained no JSON records")

    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a minimal Aster export folder.",
        epilog=(
            "Example: python3 aster_smoke_test.py ./aster_export\n"
            "Use --show-instructions to print detailed embedded instructions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "export_dir",
        nargs="?",
        help="Path to the Aster export directory containing manifest.json.",
    )
    parser.add_argument(
        "--show-instructions",
        action="store_true",
        help="Print the full embedded instructions and exit.",
    )

    args = parser.parse_args()

    if args.show_instructions:
        print(__doc__.strip())
        return 0

    if not args.export_dir:
        parser.print_help()
        return 2

    export_dir = os.path.abspath(args.export_dir)

    if not os.path.isdir(export_dir):
        fail(f"export_dir not found or not a directory: {export_dir}")

    manifest_path = os.path.join(export_dir, "manifest.json")
    manifest = load_json_file(manifest_path, "manifest.json")

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            fail(f"manifest.json missing required key: {key}")

    files = manifest["files"]

    if not isinstance(files, dict):
        fail("manifest.files must be a JSON object")

    for key in REQUIRED_FILE_KEYS:
        if key not in files:
            fail(f"manifest.files missing required key: {key}")

    persona_path = resolve_export_path(export_dir, files["persona"], "persona")
    continuity_path = resolve_export_path(export_dir, files["continuity"], "continuity")

    if not os.path.isfile(persona_path):
        fail(f"persona file missing: {persona_path}")

    if not os.path.isfile(continuity_path):
        fail(f"continuity file missing: {continuity_path}")

    # Confirm persona is valid JSON. This keeps the smoke test small but useful.
    load_json_file(persona_path, "persona file")
    pass_msg("persona file exists and parses as JSON")

    record_count = validate_continuity_jsonl(continuity_path)
    pass_msg(f"continuity JSONL parsed successfully ({record_count} record(s))")

    expected_hash = files.get("continuity_hash")

    if expected_hash is not None:
        if not isinstance(expected_hash, str) or not expected_hash.strip():
            fail("manifest.files.continuity_hash must be a non-empty string when present")

        expected_hash = expected_hash.strip().lower()
        computed_hash = sha256_hex(continuity_path).lower()

        if expected_hash != computed_hash:
            fail(
                "continuity hash mismatch: "
                f"manifest={expected_hash} computed={computed_hash}"
            )

        pass_msg("continuity hash matches manifest.files.continuity_hash")

    pass_msg("Aster export smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
