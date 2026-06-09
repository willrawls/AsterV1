import argparse
import base64
import json
import sqlite3
import sys
import traceback


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


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


print("RUNNING FILE:", __file__)
print("PYTHON:", sys.executable)


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

print("TABLES:")
for t in tables:
    print(" ", t)

for table in tables:
    print("\n" + "=" * 80)
    print(table)
    print("=" * 80)

    try:
        cur.execute(f"PRAGMA table_info({quote_identifier(table)})")
        columns = cur.fetchall()
        column_names = [c["name"] for c in columns]

        if args.fields:
            for col in columns:
                print(f"{col['name']}: {col['type']}")
            continue

        if selected_fields:
            missing = [f for f in selected_fields if f not in column_names]
            if missing:
                print(f"ERROR: field(s) not found in {table}: {', '.join(missing)}")
                continue

            fields_sql = ", ".join(quote_identifier(f) for f in selected_fields)
        else:
            fields_sql = "*"

        cur.execute(f"SELECT {fields_sql} FROM {quote_identifier(table)}")
        rows = cur.fetchall()

        print(f"Rows: {len(rows)}")

        for row in rows:
            obj = dict(row)

            print(json.dumps(obj, ensure_ascii=True, default=json_default))
            print()

    except Exception:
        traceback.print_exc()

conn.close()