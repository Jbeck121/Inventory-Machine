# One-time script to seed fake rows into test_inventory.db, matching
# the core schema. Run by hand whenever you want fresh test data --
# safe to run again after deleting test_inventory.db and rerunning
# setup_test_db.py first, since this assumes an empty database.

from inventory_machine.config import load_config
from inventory_machine.db import Database

cfg = load_config()
db = Database(cfg)

# --- Locations ---
# No "id" column here -- AUTOINCREMENT assigns it. We capture each
# one's real id off cursor.lastrowid, since items need it below.
garage_cursor = db.execute("INSERT INTO locations (name) VALUES (?)", ("garage",))
garage_id = garage_cursor.lastrowid

kitchen_cursor = db.execute("INSERT INTO locations (name) VALUES (?)", ("kitchen",))
kitchen_id = kitchen_cursor.lastrowid

office_cursor = db.execute("INSERT INTO locations (name) VALUES (?)", ("office",))
office_id = office_cursor.lastrowid

# --- Tags ---
# Same pattern -- capture each tag's real id for item_tags later.
tag_ids = {}
for tag_name in ["tools", "kitchen", "electronics", "power-tool"]:
    cursor = db.execute("INSERT INTO tags (name) VALUES (?)", (tag_name,))
    tag_ids[tag_name] = cursor.lastrowid

# --- Items ---
# items.id is TEXT, not auto-generated -- the real pipeline assigns a
# UUID here. For test data, a short readable string is fine.
db.execute(
    "INSERT INTO items (id, location_id, description, confidence_score, date_processed) "
    "VALUES (?, ?, ?, ?, ?)",
    ("item-1", garage_id, "Cordless drill", 0.92, "2026-09-23"),
)
db.execute(
    "INSERT INTO items (id, location_id, description, confidence_score, date_processed) "
    "VALUES (?, ?, ?, ?, ?)",
    ("item-2", kitchen_id, "Ceramic mug", 0.97, "2026-09-23"),
)
db.execute(
    "INSERT INTO items (id, location_id, description, confidence_score, date_processed) "
    "VALUES (?, ?, ?, ?, ?)",
    ("item-3", office_id, "USB cable", 0.85, "2026-09-23"),
)

# --- item_tags (the junction table linking items to tags) ---
db.execute("INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)", ("item-1", tag_ids["tools"]))
db.execute("INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)", ("item-1", tag_ids["power-tool"]))
db.execute("INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)", ("item-2", tag_ids["kitchen"]))
db.execute("INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)", ("item-3", tag_ids["electronics"]))

print("Seed data inserted successfully.")