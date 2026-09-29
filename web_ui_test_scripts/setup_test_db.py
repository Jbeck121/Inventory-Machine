from inventory_machine.config import load_config
from inventory_machine.db import Database

config = load_config()

db = Database(config)

db.load_schema("schema/schema.sql")

print("Success")