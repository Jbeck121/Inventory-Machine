from flask import Flask, render_template, request, abort

import sys 
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
#allows this file to work with directories and files in the repo root outside of this directory

from inventory_machine.config import load_config
from inventory_machine.db import Database

config = load_config()
db = Database(config)
#reads from config.ini in repo then opens connection to sqlite file 

def rows_to_dicts(columns, rows):
    """
    Function to convert what is gotten from db.fetch_all(), list of tuples
    with positional assess, into a list of dictionaries accessed by name
    to allow for name access rather than position based

    columns must list the SELECT's columns in the EXACT order they
    were requested -- zip() pairs them up purely by position, with
    no idea what any value actually means.
    """
    return [dict(zip(columns, row)) for row in rows]

"""
    ITEMS = [
        {"name": "Cordless drill", "category": "tools", "location": "garage"},
        {"name": "Claw hammer", "category": "tools", "location": "garage"},
        {"name": "Ceramic mug", "category": "kitchen", "location": "kitchen"},
        {"name": "Cast iron skillet", "category": "kitchen", "location": "kitchen"},
        {"name": "USB cable", "category": "electronics", "location": "office"},
    ]

    category_set = set()
    location_set = set()
    for item in ITEMS:
        category_set.add(item["category"])
        location_set.add(item["location"])

    categories = sorted(category_set)
    locations = sorted(location_set)
    #Test items and categories
"""


app = Flask(__name__)
#__name__ tells flask where the file lives 

@app.route('/')
#this registers this function as a handler for a specific URL

def home():
#this function is used to return an actual response sent to the browser 
    search_term = request.args.get("search", "")
    #gets the argument set by the form with the search name, second string is a fallback

    location_id = request.args.get("location")

    filter_submitted = location_id is not None
    #filter_submitted serves to check if user submitted a filter for the inventory search

    location_id = location_id or ""

    location_rows = db.fetch_all("SELECT id, name FROM locations ORDER BY name")
    locations = rows_to_dicts(["id", "name"], location_rows)
    #pulls fresh data from the sqlite DB set Selecting by ID and ordering it by item name
    #uses the function to convert tuples to dictionary as indicated before
    
    results = []
    #serves as the array holding the inventory

    query = (
        "SELECT items.id, items.description, items.location_id, locations.name "
        "FROM items JOIN locations ON items.location_id = locations.id"
    )
    columns = ["id", "description", "location_id", "location_name"]

    
    if search_term:
        # One pattern, used twice: once against the description and once
        # against the tag names. %...% means "contains", as before.
        pattern = f"%{search_term}%"

        # LEFT JOIN, not JOIN, for the tag tables. An item with no tags
        # (real pipeline output can have them) would vanish from a plain
        # JOIN, even if its description matched the search.
        rows = db.fetch_all(
            "SELECT DISTINCT items.id, items.description, items.location_id, locations.name "
            "FROM items "
            "JOIN locations ON items.location_id = locations.id "
            "LEFT JOIN item_tags ON item_tags.item_id = items.id "
            "LEFT JOIN tags ON item_tags.tag_id = tags.id "
            "WHERE items.description LIKE ? OR tags.name LIKE ?",
            (pattern, pattern),
        )
        results = rows_to_dicts(columns, rows)
    #If block serving to find a specific item
    elif filter_submitted:

        """
            if category or location:
                for item in ITEMS:
                    matches_category = (not category) or (item["category"] == category)
                    matches_location = (not location) or (item["location"] == location)
                    if matches_category and matches_location:
                        results.append(item)
            #used if filter was submitted and specific category or location is chosen
        """
        if location_id:
            rows = db.fetch_all(
                query + " WHERE items.location_id = ?",
                (location_id,),
            )
            results = rows_to_dicts(columns, rows)
            
        #used if filter was submitted and specific category or location is chosen
        else:
            rows = db.fetch_all(query)
            results = rows_to_dicts(columns, rows)
        #used if filter was submitted with all locations and all categories

    return render_template(
        "home.html",
        search_term = search_term,
        location = location_id,
        locations = locations,
        results=results)

"""
    For code below, the route and code having int = makes it so
    that the URL captures the number and passes into the function.
    Also makes it so a string never reaches the function
"""

@app.route("/location/<int:location_id>")
def location_page(location_id):
    location_row = db.fetch_one(
        "SELECT id, name, parent_location_id FROM locations where id = ?", (location_id,),
    )
    if location_row is None:
        abort(404)

    location=dict(zip(["id", "name", "parent_location_id"],location_row))

    item_columns=["id", "description", "confidence_score", "confidence_flag"]
    item_rows = db.fetch_all(
        "SELECT id, description, confidence_score, confidence_flag "
        "FROM items WHERE location_id = ? ORDER BY description",
        (location_id,),
    )

    items = rows_to_dicts(item_columns, item_rows)

    return render_template("location.html", location=location, items=items)

@app.route("/item/<item_id>")
def item_page(item_id):
    # No "int:" here: items.id is a TEXT UUID (yours are "item-1" and so
    # on), so the default string converter is the right one.

    # LEFT JOIN on both tables: location_id and cluster_id can be NULL,
    # and an item with neither must still show up on this page.
    columns = ["id", "description", "confidence_score", "confidence_flag",
               "date_processed", "location_id", "location_name", "cluster_label"]
    row = db.fetch_one(
        "SELECT items.id, items.description, items.confidence_score, "
        "items.confidence_flag, items.date_processed, items.location_id, "
        "locations.name, clusters.label "
        "FROM items "
        "LEFT JOIN locations ON items.location_id = locations.id "
        "LEFT JOIN clusters ON items.cluster_id = clusters.id "
        "WHERE items.id = ?",
        (item_id,),
    )
    if row is None:
        abort(404)
    item = dict(zip(columns, row))

    # Second query for tags: item_tags is the junction table, and the
    # JOIN swaps each tag_id for its readable name. Each result row is a
    # 1-tuple, so r[0] pulls the name out.
    tag_rows = db.fetch_all(
        "SELECT tags.name FROM item_tags "
        "JOIN tags ON item_tags.tag_id = tags.id "
        "WHERE item_tags.item_id = ? ORDER BY tags.name",
        (item_id,),
    )
    tags = [r[0] for r in tag_rows]

    return render_template("item.html", item=item, tags=tags)

if __name__ == "__main__":
    app.run(debug=True, port=5050, threaded=False)