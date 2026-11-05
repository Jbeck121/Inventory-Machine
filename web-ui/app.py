from flask import Flask, render_template, request, abort

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inventory_machine.config import load_config
from inventory_machine.db import Database

logger = logging.getLogger(__name__)

config = load_config()
db = Database(config)

ITEM_LIST_COLUMNS = [
    "id",
    "description",
    "location_id",
    "location_name",
    "cluster_label",
    "confidence_flag",
]

ITEM_LIST_SQL = (
    "SELECT DISTINCT items.id, items.description, items.location_id, "
    "locations.name, clusters.label, items.confidence_flag "
    "FROM items "
    "LEFT JOIN locations ON items.location_id = locations.id "
    "LEFT JOIN clusters ON items.cluster_id = clusters.id "
    "LEFT JOIN item_tags ON items.id = item_tags.item_id "
    "LEFT JOIN tags ON item_tags.tag_id = tags.id"
)


def rows_to_dicts(columns, rows):
    """
    Input: columns -- SELECT column names in order. rows -- tuples from fetch_all.
    Output: a list of dicts keyed by column name.
    Details:
        zip() pairs names to values by position.
    """
    return [dict(zip(columns, row)) for row in rows]


def _parse_optional_int(raw):
    """
    Input: raw -- a query string value or None.
    Output: an int, or None when the value is empty or not an integer.
    Details:
        Invalid values are ignored.
    """
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid integer query value: %s", raw)
        return None


def _parse_home_filters(args):
    """
    Input: args -- Flask request.args or a mapping with the same keys.
    Output: search text and validated filter values.
    Details:
        cluster=unclustered means cluster_id IS NULL. Invalid ints are dropped.
    """
    search = args.get("search") or ""
    cluster_raw = args.get("cluster") or ""
    unclustered = cluster_raw == "unclustered"
    flag_raw = args.get("confidence") or ""
    if flag_raw in ("ok", "low"):
        confidence_flag = flag_raw
    else:
        if flag_raw:
            logger.warning("Ignoring invalid confidence flag: %s", flag_raw)
        confidence_flag = None
    return {
        "search": search,
        "location_id": _parse_optional_int(args.get("location")),
        "cluster_id": None if unclustered else _parse_optional_int(cluster_raw),
        "unclustered": unclustered,
        "tag_id": _parse_optional_int(args.get("tag")),
        "confidence_flag": confidence_flag,
    }


def _home_where(filters):
    """
    Input: filters -- dict from _parse_home_filters.
    Output: (WHERE clause including leading WHERE, or empty; bind params).
    Details:
        Clauses are fixed strings. User values go in the params list.
    """
    clauses = []
    params = []
    search = filters["search"]
    if search:
        like = f"%{search}%"
        clauses.append(
            "(LOWER(items.description) LIKE LOWER(?) "
            "OR LOWER(tags.name) LIKE LOWER(?))"
        )
        params.extend([like, like])
    if filters["location_id"] is not None:
        clauses.append("items.location_id = ?")
        params.append(filters["location_id"])
    if filters["unclustered"]:
        clauses.append("items.cluster_id IS NULL")
    elif filters["cluster_id"] is not None:
        clauses.append("items.cluster_id = ?")
        params.append(filters["cluster_id"])
    if filters["tag_id"] is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM item_tags "
            "WHERE item_tags.item_id = items.id AND item_tags.tag_id = ?)"
        )
        params.append(filters["tag_id"])
    if filters["confidence_flag"] is not None:
        clauses.append("items.confidence_flag = ?")
        params.append(filters["confidence_flag"])
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _attach_tags(results):
    """
    Input: results -- item dicts that include an id key.
    Output: the same list, each item given a tags name list.
    Details:
        One query loads tags for the listed ids. Placeholders are not user text.
    """
    ids = [item["id"] for item in results]
    for item in results:
        item["tags"] = []
    if not ids:
        return results
    placeholders = ",".join("?" * len(ids))
    tag_rows = db.fetch_all(
        "SELECT item_tags.item_id, tags.name FROM item_tags "
        "JOIN tags ON item_tags.tag_id = tags.id "
        f"WHERE item_tags.item_id IN ({placeholders}) "
        "ORDER BY tags.name",
        tuple(ids),
    )
    by_item = {item_id: [] for item_id in ids}
    for item_id, name in tag_rows:
        by_item[item_id].append(name)
    for item in results:
        item["tags"] = by_item.get(item["id"], [])
    return results


app = Flask(__name__)


@app.route("/")
def home():
    """
    Input: search, location, cluster, tag, and confidence query args.
    Output: the home page with matching items.
    Details:
        First load lists every item. Filters combine with AND.
    """
    filters = _parse_home_filters(request.args)
    locations = rows_to_dicts(
        ["id", "name"],
        db.fetch_all("SELECT id, name FROM locations ORDER BY name"),
    )
    clusters = rows_to_dicts(
        ["id", "label"],
        db.fetch_all("SELECT id, label FROM clusters ORDER BY id"),
    )
    tags = rows_to_dicts(
        ["id", "name"],
        db.fetch_all("SELECT id, name FROM tags ORDER BY name"),
    )
    where, params = _home_where(filters)
    rows = db.fetch_all(
        ITEM_LIST_SQL + where + " ORDER BY items.description",
        tuple(params),
    )
    results = _attach_tags(rows_to_dicts(ITEM_LIST_COLUMNS, rows))
    return render_template(
        "home.html",
        search_term=filters["search"],
        location_id=filters["location_id"],
        cluster_id=filters["cluster_id"],
        unclustered=filters["unclustered"],
        tag_id=filters["tag_id"],
        confidence_flag=filters["confidence_flag"],
        locations=locations,
        clusters=clusters,
        tags=tags,
        results=results,
    )


@app.route("/scan")
def scan_page():
    """
    Input: None.
    Output: the in-browser QR scan page.
    Details:
        The page uses the vendored jsQR script and the device camera.
    """
    return render_template("scan.html")


@app.route("/location/<int:location_id>")
def location_page(location_id):
    """
    Input: location_id -- locations.id from the URL.
    Output: the location page, or 404 when the row is missing.
    Details:
        The page lists items here, the parent location, and child locations.
    """
    location_row = db.fetch_one(
        "SELECT id, name, parent_location_id FROM locations WHERE id = ?",
        (location_id,),
    )
    if location_row is None:
        abort(404)
    location = dict(zip(["id", "name", "parent_location_id"], location_row))

    parent = None
    if location["parent_location_id"] is not None:
        parent_row = db.fetch_one(
            "SELECT id, name FROM locations WHERE id = ?",
            (location["parent_location_id"],),
        )
        if parent_row is not None:
            parent = dict(zip(["id", "name"], parent_row))

    children = rows_to_dicts(
        ["id", "name"],
        db.fetch_all(
            "SELECT id, name FROM locations "
            "WHERE parent_location_id = ? ORDER BY name",
            (location_id,),
        ),
    )
    items = rows_to_dicts(
        ["id", "description", "confidence_score", "confidence_flag"],
        db.fetch_all(
            "SELECT id, description, confidence_score, confidence_flag "
            "FROM items WHERE location_id = ? ORDER BY description",
            (location_id,),
        ),
    )
    return render_template(
        "location.html",
        location=location,
        parent=parent,
        children=children,
        items=items,
    )


@app.route("/item/<item_id>")
def item_page(item_id):
    """
    Input: item_id -- items.id from the URL.
    Output: the item page, or 404 when the row is missing.
    Details:
        location_id and cluster_id may be NULL. LEFT JOIN keeps the item.
    """
    columns = [
        "id",
        "description",
        "confidence_score",
        "confidence_flag",
        "date_processed",
        "location_id",
        "location_name",
        "cluster_label",
    ]
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
    tag_rows = db.fetch_all(
        "SELECT tags.name FROM item_tags "
        "JOIN tags ON item_tags.tag_id = tags.id "
        "WHERE item_tags.item_id = ? ORDER BY tags.name",
        (item_id,),
    )
    tags = [tag_row[0] for tag_row in tag_rows]
    return render_template("item.html", item=item, tags=tags)


if __name__ == "__main__":
    app.run(debug=True, port=5050, threaded=False)
