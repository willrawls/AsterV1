/*
    DEPRICATED - DO NOT USE
*/

import argparse
import base64
import json
import sqlite3
import sys
import traceback
from datetime import datetime, timezone 

def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

def utc_now_year_month() -> str:
    return datetime.now(timezone.utc).isoformat()[:7]

def normalize_provenance(value):
    value = maybe_json(value)

    if isinstance(value, list) and all(isinstance(x, str) and len(x) == 1 for x in value):
        value = ["".join(value)]

    if value is None or value == "":
        return []

    if isinstance(value, str):
        return [{"source": value}]

    if isinstance(value, dict):
        return [value]

    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str):
                out.append({"source": item})
            elif isinstance(item, dict):
                out.append(item)
            else:
                out.append({"source": str(item)})
        return out

    return [{"source": str(value)}]

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./aster_export/aster_seeds.db")
    parser.add_argument(
        "--filter",
        default=None,
        help="Comma-delimited list of fields to output, e.g. seed_id,title,created_at",
    )
    parser.add_argument(
        "--fields",
        action="store_true",
        help="Output only field names and types per table",
    )
    return parser.parse_args()


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def json_default(value):
    if isinstance(value, sqlite3.Row):
        return dict(value)

    if isinstance(value, bytes):
        return {
            "__type__": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }

    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

def maybe_json(value):
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("[") or s.startswith("{"):
            return json.loads(s)
    return value

args = parse_args()

selected_fields = None
if args.filter:
    selected_fields = [f.strip() for f in args.filter.split(",") if f.strip()]

conn = sqlite3.connect(args.db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
SELECT name
FROM sqlite_master
WHERE type='table'
ORDER BY name
""")

tables = [r[0] for r in cur.fetchall()]

for table in tables:
    print()
    print("//" + "=" * 80)
    print("//" + table)
    print("//" + "=" * 80)

    try:
        cur.execute(f"PRAGMA table_info({quote_identifier(table)})")
        columns = cur.fetchall()
        column_names = [c["name"] for c in columns]

        if args.fields:
            for col in columns:
                print("//" + f"{col['name']}: {col['type']}")
            continue

        if selected_fields:
            missing = [f for f in selected_fields if f not in column_names]
            if missing:
                print("//" + f"ERROR: field(s) not found in {table}: {', '.join(missing)}")
                continue

            fields_sql = ", ".join(quote_identifier(f) for f in selected_fields)
        else:
            fields_sql = "*"

        cur.execute(f"SELECT {fields_sql} FROM {quote_identifier(table)}")
        rows = cur.fetchall()

        print("//" + f"Rows: {len(rows)}")

        output_path = f"./aster_seeds_processed_{utc_now_iso()}.json1"
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                row["tags"] = maybe_json(row["tags"])
                row["provenance_chain"] = normalize_provenance(row["provenance_chain"])
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    except Exception:
        traceback.print_exc()

conn.close()