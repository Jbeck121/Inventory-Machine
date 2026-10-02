import sqlite3

conn = sqlite3.connect("web_ui_test_scripts/test_inventory.db")

for table in ["locations", "tags", "items", "item_tags"]:
    print(f"\n--- {table} ---")
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    for row in rows:
        print(row)