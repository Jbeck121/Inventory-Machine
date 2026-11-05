"""Tests for the Flask inventory search UI against a temp SQLite database."""
import importlib.util
import logging
import sys
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "web-ui" / "app.py"
SCHEMA = ROOT / "schema" / "option_a_home_organizer.sql"


def _write_config(tmp_path: Path) -> None:
    """
    Input: tmp_path -- pytest temp directory.
    Output: None.
    Details:
        Writes config.ini so load_config() can open a sqlite file here.
    """
    (tmp_path / "config.ini").write_text(
        "[database]\n"
        "backend = sqlite\n"
        f"sqlite_path = {tmp_path / 'inv.db'}\n"
        "\n"
        "[confidence]\n"
        "self_report_weight = 0.6\n"
        "tag_coherence_weight = 0.4\n",
        encoding="utf-8",
    )


def _seed(database) -> None:
    """
    Input: database -- open Database with Option A schema loaded.
    Output: None.
    Details:
        Inserts locations, clusters, tags, and items used by the UI tests.
    """
    garage_id = database.execute(
        "INSERT INTO locations (name) VALUES (?)", ("Garage",)
    ).lastrowid
    kitchen_id = database.execute(
        "INSERT INTO locations (name) VALUES (?)", ("Kitchen",)
    ).lastrowid
    database.execute(
        "INSERT INTO locations (name, parent_location_id) VALUES (?, ?)",
        ("Garage shelf", garage_id),
    )
    tools_id = database.execute(
        "INSERT INTO clusters (label) VALUES (?)", ("Power tools",)
    ).lastrowid
    kitchen_cluster_id = database.execute(
        "INSERT INTO clusters (label) VALUES (?)", ("Kitchen goods",)
    ).lastrowid
    drill_tag = database.execute(
        "INSERT INTO tags (name) VALUES (?)", ("drill",)
    ).lastrowid
    kitchenware_tag = database.execute(
        "INSERT INTO tags (name) VALUES (?)", ("kitchenware",)
    ).lastrowid
    hardware_tag = database.execute(
        "INSERT INTO tags (name) VALUES (?)", ("hardware",)
    ).lastrowid
    database.execute(
        "INSERT INTO items (id, location_id, cluster_id, description, "
        "confidence_score, confidence_flag, date_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("item-drill", garage_id, tools_id, "Cordless drill", 0.9, "ok", "2026-01-01"),
    )
    database.execute(
        "INSERT INTO items (id, location_id, cluster_id, description, "
        "confidence_score, confidence_flag, date_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("item-mug", kitchen_id, kitchen_cluster_id, "Ceramic mug", 0.2, "low", "2026-01-02"),
    )
    database.execute(
        "INSERT INTO items (id, location_id, cluster_id, description, "
        "confidence_score, confidence_flag, date_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("item-orphan", None, None, "Loose screw", 0.8, "ok", "2026-01-03"),
    )
    shelf_id = database.fetch_one(
        "SELECT id FROM locations WHERE name = ?", ("Garage shelf",)
    )[0]
    database.execute(
        "INSERT INTO items (id, location_id, cluster_id, description, "
        "confidence_score, confidence_flag, date_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("item-nails", shelf_id, None, "Bin of nails", 0.7, "ok", "2026-01-04"),
    )
    database.execute(
        "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)",
        ("item-drill", drill_tag),
    )
    database.execute(
        "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)",
        ("item-mug", kitchenware_tag),
    )
    database.execute(
        "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)",
        ("item-orphan", hardware_tag),
    )
    database.execute(
        "INSERT INTO item_tags (item_id, tag_id) VALUES (?, ?)",
        ("item-nails", hardware_tag),
    )


def _load_app(tmp_path: Path, monkeypatch):
    """
    Input: tmp_path -- pytest temp directory. monkeypatch -- chdir helper.
    Output: the loaded web-ui app module with schema and seed data.
    Details:
        chdir makes load_config read the temp config.ini.
    """
    _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("web_ui_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["web_ui_app"] = module
    spec.loader.exec_module(module)
    module.db.load_schema(str(SCHEMA))
    _seed(module.db)
    module.app.config["TESTING"] = True
    return module


@pytest.fixture
def ui(tmp_path, monkeypatch):
    """
    Input: tmp_path -- pytest temp directory. monkeypatch -- chdir helper.
    Output: the Flask app module bound to a seeded temp database.
    Details:
        Closes the sqlite connection when the test ends.
    """
    module = _load_app(tmp_path, monkeypatch)
    yield module
    try:
        module.db.get_connection().close()
    except Exception:
        logger.exception("Failed to close the web UI test database")
        raise


@pytest.fixture
def client(ui):
    """
    Input: ui -- loaded web-ui app module.
    Output: a Flask test client.
    Details:
        Uses the seeded database from the ui fixture.
    """
    return ui.app.test_client()


def _tag_id(ui, name: str) -> int:
    """
    Input: ui -- loaded app module. name -- tags.name.
    Output: tags.id.
    Details:
        Raises if the seed tag is missing.
    """
    row = ui.db.fetch_one("SELECT id FROM tags WHERE name = ?", (name,))
    if row is None:
        logger.warning("Seed tag missing: %s", name)
        raise AssertionError(f"missing tag {name}")
    return row[0]


def _location_id(ui, name: str) -> int:
    """
    Input: ui -- loaded app module. name -- locations.name.
    Output: locations.id.
    Details:
        Raises if the seed location is missing.
    """
    row = ui.db.fetch_one("SELECT id FROM locations WHERE name = ?", (name,))
    if row is None:
        logger.warning("Seed location missing: %s", name)
        raise AssertionError(f"missing location {name}")
    return row[0]


def _cluster_id(ui, label: str) -> int:
    """
    Input: ui -- loaded app module. label -- clusters.label.
    Output: clusters.id.
    Details:
        Raises if the seed cluster is missing.
    """
    row = ui.db.fetch_one("SELECT id FROM clusters WHERE label = ?", (label,))
    if row is None:
        logger.warning("Seed cluster missing: %s", label)
        raise AssertionError(f"missing cluster {label}")
    return row[0]


def test_home_lists_item_with_null_location(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Loose screw" in body
    assert "not assigned" in body
    assert "/location/None" not in body
    assert "Cordless drill" in body
    assert "Ceramic mug" in body
    assert "Bin of nails" in body


def test_search_by_tag_text(client):
    response = client.get("/?search=kitchenware")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Ceramic mug" in body
    assert "Cordless drill" not in body
    assert "Loose screw" not in body


def test_search_description_is_case_insensitive(client):
    response = client.get("/?search=DRILL")
    body = response.get_data(as_text=True)
    assert "Cordless drill" in body
    assert "Ceramic mug" not in body


def test_filter_location_alone(client, ui):
    garage_id = _location_id(ui, "Garage")
    response = client.get(f"/?location={garage_id}")
    body = response.get_data(as_text=True)
    assert "Cordless drill" in body
    assert "Ceramic mug" not in body
    assert "Loose screw" not in body
    assert "Bin of nails" not in body


def test_filter_cluster_unclustered_alone(client):
    response = client.get("/?cluster=unclustered")
    body = response.get_data(as_text=True)
    assert "Loose screw" in body
    assert "Bin of nails" in body
    assert "Cordless drill" not in body
    assert "Ceramic mug" not in body


def test_filter_cluster_id_alone(client, ui):
    cluster_id = _cluster_id(ui, "Power tools")
    response = client.get(f"/?cluster={cluster_id}")
    body = response.get_data(as_text=True)
    assert "Cordless drill" in body
    assert "Ceramic mug" not in body
    assert "Loose screw" not in body


def test_filter_tag_alone(client, ui):
    tag_id = _tag_id(ui, "hardware")
    response = client.get(f"/?tag={tag_id}")
    body = response.get_data(as_text=True)
    assert "Loose screw" in body
    assert "Bin of nails" in body
    assert "Cordless drill" not in body
    assert "Ceramic mug" not in body


def test_filter_confidence_alone(client):
    response = client.get("/?confidence=low")
    body = response.get_data(as_text=True)
    assert "Ceramic mug" in body
    assert "Cordless drill" not in body
    assert "Loose screw" not in body


def test_combined_filters(client, ui):
    shelf_id = _location_id(ui, "Garage shelf")
    tag_id = _tag_id(ui, "hardware")
    response = client.get(
        f"/?search=nails&location={shelf_id}&cluster=unclustered"
        f"&tag={tag_id}&confidence=ok"
    )
    body = response.get_data(as_text=True)
    assert "Bin of nails" in body
    assert "Loose screw" not in body
    assert "Cordless drill" not in body
    assert "Ceramic mug" not in body


def test_invalid_filter_values_are_ignored(client):
    response = client.get("/?location=abc&cluster=nope&tag=x&confidence=maybe")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Cordless drill" in body
    assert "Ceramic mug" in body
    assert "Loose screw" in body


def test_filters_are_sticky(client, ui):
    garage_id = _location_id(ui, "Garage")
    tag_id = _tag_id(ui, "drill")
    cluster_id = _cluster_id(ui, "Power tools")
    response = client.get(
        f"/?search=drill&location={garage_id}&cluster={cluster_id}"
        f"&tag={tag_id}&confidence=ok"
    )
    body = response.get_data(as_text=True)
    assert 'value="drill"' in body
    assert f'value="{garage_id}" selected' in body
    assert f'value="{cluster_id}" selected' in body
    assert f'value="{tag_id}" selected' in body
    assert 'value="ok" selected' in body


def test_scan_page_includes_jsqr(client):
    response = client.get("/scan")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'src="/static/vendor/jsQR.js"' in body
    assert "jsQR(" in body
    assert 'facingMode: "environment"' in body


def test_location_page_200_lists_parent_and_children(client, ui):
    garage_id = _location_id(ui, "Garage")
    shelf_id = _location_id(ui, "Garage shelf")
    garage = client.get(f"/location/{garage_id}")
    assert garage.status_code == 200
    garage_body = garage.get_data(as_text=True)
    assert "Garage shelf" in garage_body
    assert "Cordless drill" in garage_body
    shelf = client.get(f"/location/{shelf_id}")
    assert shelf.status_code == 200
    shelf_body = shelf.get_data(as_text=True)
    assert "Garage" in shelf_body
    assert f"/location/{garage_id}" in shelf_body
    assert "Bin of nails" in shelf_body


def test_location_and_item_404(client):
    assert client.get("/location/999").status_code == 404
    assert client.get("/item/missing").status_code == 404


def test_item_page_200(client):
    response = client.get("/item/item-drill")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Cordless drill" in body
    assert "Garage" in body
    assert "drill" in body
    orphan = client.get("/item/item-orphan")
    assert orphan.status_code == 200
    assert "not assigned" in orphan.get_data(as_text=True)
