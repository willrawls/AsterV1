import sqlite3

conn = sqlite3.connect("aster_seeds.db")
conn.row_factory = sqlite3.Row

cur = conn.cursor()

# Show tables
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

# Dump contents
for table in tables:
    print("\n" + "=" * 80)
    print(table)
    print("=" * 80)

    try:
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()

        print(f"Rows: {len(rows)}")

        for row in rows:
            print(dict(row))

    except Exception as ex:
        print("ERROR:", ex)

conn.close()