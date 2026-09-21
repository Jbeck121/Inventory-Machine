# Inventory Machine Plan

## Project Summary

Inventory Machine reads a folder of item photos. It sends each photo to a
local vision-language model. The model returns tags, a text description,
and a confidence score. The pipeline groups similar items by
embedding-based clustering. Each item gets a UUID. The system stores
every item, tag, image, and cluster in a normalized SQL database, and it
prints a QR-code label for each storage location.

This plan supports COCS 640 (Database Systems I), Milestone 1, taught by
Dr. Muhammad. Team members are Jesse Beck, Richard Baldwin, Kian Dong,
and Reece Clem. See `README.md` for the current build status and the
split between the MVP and the ideal final build.

---

## Implementation Options Under Consideration

The course requires 15 to 30 normalized tables. The team does not want to
pad the schema with tables that do not model a real thing. Instead, the
team picked three real inventory domains, sized each schema honestly, and
will choose the option whose schema, after review, best fits the
project's scope and the team's access to real data.

The `schema/` directory holds one full, standalone SQL schema per
option, plus the shared core schema every option builds on.

| Option | Domain | Extra tables | Total tables |
|---|---|---|---|
| A | Home organizer: general household items in crates and drawers | 13 | 24 |
| B | University IT asset management: laptops, labs, and support tickets | 17 | 28 |
| C | FSU Spark Labs inventory: a research and makerspace lab | 19 | 30 |

Each option adds its extra tables to the same 11-table core schema (see
"Database Design" below). The core schema does not change across
options. Only the business-specific tables change.

---

## Core Architecture

```mermaid
flowchart TD
    A[Input: folder of photos] --> B[Image preprocessor]
    B --> C["Vision model: MiniCPM-V 4.5 (or 4.6)"]
    C --> D[Structured output parser]
    D --> E["SQL database: items, images, tags"]
    D --> F["Embedding model: Qwen3 Embedding 0.6b"]
    F --> G[ChromaDB vector store]
    G --> H[HDBSCAN clustering]
    H --> I["SQL database: clusters"]
    H --> J[Cluster label generator]
    E --> K[QR label generator]
    I --> K
    K --> L["Printed labels: description + QR code"]
    E --> M["Web app: search, filters, in-browser QR camera scan"]
    I --> M

    B --> B1[Resize and normalize]
    B --> B2["EXIF: date taken, GPS (optional)"]
    D --> D1[Tags]
    D --> D2[Prose description]
    D --> D3[Confidence score]
    D --> D4[Location, from folder name]
```

---

## AI Components

### Vision Model

The pipeline calls `minicpm-v4.5` through Ollama by default. Team members
whose hardware cannot run `minicpm-v4.5` use `minicpm-v4.6` instead. Both
tags run through the same Ollama API, so the config file only needs to
name the tag to use.

The pipeline calls the model once per photo, with a prompt that requests
JSON output. Ollama enforces this with `"format": "json"` in the request
body.

Prompt JSON structure:

```json
{
  "tags": ["tag1", "tag2"],
  "description": "2-4 sentences covering color, material, condition, approximate size.",
  "confidence": 0.85
}
```

#### Vision Prompt Template

The prompt lives in its own file, at the path the config sets, so the
`.ini` file stays short.

```
System: You are an inventory assistant. Respond only with valid JSON, no markdown.

User: Describe the object(s) in this image.
Return exactly this structure:
{
  "tags": ["tag1", "tag2", ...],   // 5-15 specific, lowercase noun/adjective tags
  "description": "...",            // 2-4 sentences, include color, material, condition, approximate size
  "confidence": 0.0                // float 0.0-1.0, your certainty about the identification
}
```

### Embedding Model

The pipeline calls `qwen3-embedding:0.6b` through Ollama. It converts
each item's tags and description into one vector. ChromaDB stores and
indexes these vectors for similarity search. The vision model already
converted each photo to text, so the embedding step only needs a
text-only model. It does not need a multimodal one.

### Clustering

HDBSCAN groups the vectors ChromaDB holds. HDBSCAN needs no
pre-set cluster count, and it marks outliers as noise instead of forcing
them into a cluster. This fits a household or lab inventory, where many
items have no close match. Noise items keep `cluster_id` set to `NULL`.
After clustering, the pipeline sends the 3 most central items in each
cluster back to the vision model, with a short prompt that asks for a
2-4 word label for the group.

---

## Confidence Score

Vision models do not report a calibrated probability on their own. The
pipeline builds a confidence score from two signals.

1. **Model self-report.** The `confidence` field in the model's JSON
   output. This catches the obvious cases: a blurry, occluded, or
   ambiguous photo.
2. **Tag coherence.** The mean pairwise cosine similarity across an
   item's tag embeddings. A high variance means the model hedged across
   unrelated concepts.

Final score:

```
confidence = (self_report_weight * self_report) + (tag_coherence_weight * tag_coherence)
```

The config file sets both weights, and they must sum to 1.0. An item
below `low_confidence_threshold` gets `confidence_flag = 'low'` in the
database, so a query can filter on it directly.

---

## Location Model

A location is a physical place: a room, a shelf, a drawer, or a bin. The
`locations` table lets one location sit inside another, through
`parent_location_id`. A drawer can sit inside a shelf, and a shelf inside
a room. The folder name for a photo sets the initial location, matched
or created by name at ingestion time. A team member can move an item to
a new location later, without touching the photo or the AI output.

```
inventory_input/
    garage_shelf_a/
        img001.jpg
        img002.jpg
    kitchen_drawer/
        img003.jpg
```

Nested input folders join with the `folder_separator` from config
(default ` > `), for example `garage > shelf_a`. The config's
`strip_prefixes` list removes configured prefix strings from folder
names before the pipeline uses them.

Each `images` row also carries optional `date_taken`, `gps_lat`, and
`gps_lon` columns, extracted from the photo's EXIF data via Pillow when
present. These record where/when the photo was taken, and stay separate
from `locations`, which tracks physical storage placement, not capture
geolocation. A photo with no EXIF data leaves these columns `NULL`;
extraction failure never blocks ingestion.

---

## QR Code and Label Strategy

Each label is a printed sheet with two parts: a short text description
and a QR code. A team member attaches the label to a physical container,
drawer, or shelf.

Most labels point at a **location**, not at a single item, because one
container usually holds several items. The QR code encodes a URL:

```
<BASE_URL>/location/<location_id>
```

A phone camera reads the code and opens a page that lists every item
stored at that location, with a link to each item's own record. This
matches how the label works in practice: a person finds the physical
container first, then looks inside it for the specific item.

An item can also get its own label when it lives outside any container,
for example a single large piece of equipment. The `qr_labels` table
stores both cases in one table: a row that points at a `location_id`, or
a row that points at an `item_id`. A check constraint requires each row
to set exactly one of the two, never both and never neither.

Every item still keeps its own UUID and its own database row, whether or
not it ever gets a label of its own.

---

## Web Application

The Flask app is more than a QR-triggered lookup page. It also gives the
team a browsable, searchable front end over the catalog:

- **Search bar.** Free-text search across item tags and descriptions.
- **In-browser QR scanning.** A page that requests camera access and
  decodes a QR code client-side, then redirects to the matching
  `/location/<id>` or `/item/<id>` page — an alternative to a phone's
  native camera app for team members testing on a laptop with no camera
  app of its own.
- **Filterable inventory view.** A list/grid of items, filterable by
  location, cluster, tag, and confidence flag.
- **`/location/<location_id>`** and **`/item/<item_id>`** detail pages,
  as described above.

---

## Database Design

### SQLite for development, MariaDB for production

The team builds the schema and the data access layer against SQLite
first. Every SQL call in the codebase goes through one data access
layer. The team switches the backend to MariaDB later by changing a
connection string in the config file. No other code changes, because no
code outside the data access layer issues SQL directly, and the table
and column shapes stay the same on both backends.

Two syntax differences carry across the switch, and the data access
layer, not the schema files, handles them:

1. `INTEGER PRIMARY KEY AUTOINCREMENT` (SQLite) becomes `INTEGER PRIMARY
   KEY AUTO_INCREMENT` (MariaDB).
2. `datetime('now')` (SQLite) becomes `CURRENT_TIMESTAMP` (MariaDB).

### Core Tables (all options)

These 11 tables hold no business-specific data. Every option keeps them
unchanged. Full column definitions live in `schema/schema.sql`.

| Table | Holds |
|---|---|
| `locations` | Physical places, nested through a self-referencing parent |
| `clusters` | Groups of similar items, with a generated label |
| `items` | One row per cataloged item, keyed by UUID |
| `images` | One row per source photo, linked to its item |
| `tags` | AI-generated keywords |
| `item_tags` | Many-to-many bridge between items and tags |
| `confidence_components` | The two weighted signals behind an item's confidence score |
| `embeddings_index` | A pointer to the item's vector in ChromaDB, not the vector itself |
| `vision_model_outputs` | Raw model responses, including retried attempts, for audit |
| `qr_labels` | Printed labels, each tied to a location or an item |
| `processing_runs` | One row per pipeline run, with its config snapshot |

### Domain-Specific Tables

Each option adds real, distinct tables on top of the core 11. None of
these tables exist only to raise a count. Full column definitions live
in each option's SQL file.

**Option A: home organizer** (`schema/option_a_home_organizer.sql`, 13
extra tables)

`categories`, `item_categories`, `household_members`, `borrow_log`,
`maintenance_log`, `condition_log`, `retailers`, `purchase_records`,
`item_value_estimates`, `disposal_records`, `insurance_policies`,
`item_insurance`, `reminders`.

This models a full household-inventory lifecycle: a curated category
tree apart from AI tags, lending between household members, condition
history apart from maintenance actions, purchase and warranty records,
end-of-life disposal, value estimates for insurance, and a reminders
table that surfaces due dates across the other tables.

**Option B: university IT asset management**
(`schema/option_b_university_it.sql`, 17 extra tables)

`departments`, `employees`, `patrons`, `cost_centers`, `vendors`,
`purchase_orders`, `purchase_order_lines`, `asset_models`, `warranties`,
`software_licenses`, `license_assignments`, `asset_assignments`,
`ticket_categories`, `service_tickets`, `ticket_comments`,
`maintenance_history`, `depreciation_schedules`.

This models a real university IT department: a catalog of asset models
apart from serialized units, purchase orders split into line items,
software license seats tracked apart from hardware, a ticket system with
categories and a comment history, and depreciation schedules for
accounting. `patrons` (students, faculty, staff who request support)
stays separate from `employees` (the IT staff who manage assets and work
tickets).

**Option C: FSU Spark Labs** (`schema/option_c_spark_labs.sql`, 19 extra
tables)

`lab_members`, `certifications`, `training_sessions`,
`training_attendance`, `member_certifications`, `projects`,
`project_members`, `reservations`, `checkouts`, `consumables`,
`consumable_stock`, `consumable_usage_log`, `maintenance_requests`,
`incident_reports`, `experiment_runs`, `server_assets`,
`drone_flight_logs`, `radio_licenses`.

This design follows Spark Labs' actual equipment: 3D printers and print
supplies, servers, an arcade cabinet, soldering and other hand-tool
hardware, drones, radio systems, and an active photolithography research
effort. A few tables map directly to that mix: `server_assets` extends
only the items that are servers, `drone_flight_logs` covers FAA Part 107
flight records, `radio_licenses` covers FCC operator licenses tied to a
lab member, and `experiment_runs` logs a research process run (a
photolithography exposure, a print job) against the project it supports.
`consumables` and `consumable_stock` track filament, resin, and solder
stock by quantity, apart from the durable, individually tagged
equipment items.

### ChromaDB Integration

ChromaDB stores the actual embedding vectors outside SQL. The
`embeddings_index` table stores only a pointer: the Chroma collection
name, the Chroma record ID, and the model name. This keeps the
relational schema focused on structured facts, and it keeps vector
search fast, since ChromaDB indexes for nearest-neighbor lookup and SQL
does not.

---

## Timestamps

The pipeline writes `date_processed` once, when it inserts an item row.

```python
from datetime import datetime, timezone

def get_timestamp(cfg: configparser.ConfigParser) -> str:
    tz = timezone.utc if cfg.get("output", "timestamp_timezone") == "utc" else None
    fmt = cfg.get("output", "timestamp_format")
    return datetime.now(tz).strftime(fmt)
```

Passing `tz=None` gives local time. For a named timezone (for example
`America/New_York`), swap in `zoneinfo.ZoneInfo` later.

`images.date_taken` is a separate, independent timestamp: the photo's
own EXIF capture time, extracted at ingestion when present, `NULL`
otherwise. It records when the photo was taken; `date_processed`
records when the pipeline ran. The two commonly differ, for example
when a batch of older photos is ingested at once.

---

## Config File

```ini
[paths]
input_dir = ./inventory_input
qr_output_dir = ./inventory_output/qr_codes
log_file = ./logs/inventory_machine.log

[database]
backend = sqlite
sqlite_path = ./inventory.db
; used only when backend = mariadb
mariadb_dsn = mariadb://user:pass@host:3306/inventory

[chroma]
persist_dir = ./chroma_store
collection_name = inventory_items

[models]
vision_model = minicpm-v4.5
; fallback for hardware that cannot run minicpm-v4.5
vision_model_fallback = minicpm-v4.6
embedding_model = qwen3-embedding:0.6b
ollama_base_url = http://localhost:11434

[vision]
max_retries = 3
image_max_px = 1024
json_mode = true
; prompt template file path -- keeps the ini short
prompt_template = ./prompts/vision_prompt.txt

[confidence]
self_report_weight = 0.6
tag_coherence_weight = 0.4
low_confidence_threshold = 0.5

[clustering]
min_cluster_size = 2
min_samples = 1
; epsilon = 0 means HDBSCAN auto-selects
epsilon = 0.0

[labels]
qr_base_url = <BASE_URL>
label_width_mm = 62
label_height_mm = 29

[location]
folder_separator = >
; comma-separated strings to strip from folder names before use as location
strip_prefixes = img_, scan_, batch_

[output]
; get_timestamp() reads these two keys directly
timestamp_timezone = local
timestamp_format = %Y-%m-%d %H:%M:%S
```

### Config Loading

```python
# config.py
import configparser
from pathlib import Path

def load_config(path: str = "config.ini") -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(
        interpolation=configparser.BasicInterpolation(),
        inline_comment_prefixes=(";",),
    )
    read = cfg.read(path)
    if not read:
        raise FileNotFoundError(f"Config not found: {path}")
    return cfg

def get_confidence_weights(cfg: configparser.ConfigParser) -> tuple[float, float]:
    w1 = cfg.getfloat("confidence", "self_report_weight")
    w2 = cfg.getfloat("confidence", "tag_coherence_weight")
    if abs(w1 + w2 - 1.0) > 1e-6:
        raise ValueError(f"Confidence weights must sum to 1.0, got {w1 + w2}")
    return w1, w2
```

Weight validation runs at startup, not at scoring time, so a bad config
fails fast. The pipeline passes the `cfg` object around instead of
re-reading the file, which also makes testing easier: a test can build a
`ConfigParser` from a string instead of writing a file to disk.

---

## Data Access Layer

One module owns every SQL call. It reads `[database] backend` from
config and opens either a `sqlite3` connection to `sqlite_path`, or a
MariaDB connection (through a driver such as `mariadb` or `PyMySQL`)
using the `mariadb_dsn` value. Both paths return an object with the same
methods: `get_connection()`, `execute(query, params)`,
`fetch_one(query, params)`, `fetch_all(query, params)`.

Every other module calls these methods and never opens its own
connection or writes backend-specific SQL. Parameterized queries only,
never string-built SQL, on both backends. This is what makes the SQLite-
to-MariaDB switch a one-line config change instead of a rewrite.

---

## Implementation Stack

```
Python 3.11+
├── ollama                  # local model serving (vision + embeddings)
├── Pillow                  # image preprocessing
├── httpx                   # async calls to the Ollama API
├── chromadb                # vector store for similarity search
├── hdbscan                 # clustering
├── scikit-learn            # fallback: KMeans, PCA for debug viz
├── mariadb (or PyMySQL)    # MariaDB driver, used only when backend = mariadb
├── qrcode[pil]             # QR generation
└── flask                   # web app: search, filters, in-browser QR scan, and the item/location pages a QR code opens
```

---

## Processing Pipeline

1. **Walk the input directory.** Collect every `.jpg`/`.png`/`.webp`
   path. Record each photo's parent folder as its initial location.
2. **Preprocess.** Resize each photo to `image_max_px` on its longest
   side.
3. **Run vision inference.** POST each photo to the configured vision
   model through Ollama, with the JSON-mode prompt. Retry up to
   `max_retries` on malformed output. Store every raw response, retried
   or not, in `vision_model_outputs`.
4. **Embed.** Run the embedding model on each item's tags joined with
   its description. Store the resulting vector in ChromaDB, and store a
   pointer to it in `embeddings_index`.
5. **Score confidence.** Compute tag coherence from pairwise cosine
   similarity across an item's tag embeddings. Combine it with the
   model's self-reported confidence, using the configured weights.
6. **Cluster.** Run HDBSCAN on the vectors ChromaDB holds. Noise items
   keep `cluster_id` set to `NULL`.
7. **Label clusters.** For each cluster, send the tags of its 3 most
   central items back to the vision model, with a prompt that asks for
   a 2-4 word group label.
8. **Write to the database.** Insert rows into `items`, `images`, `tags`,
   `item_tags`, `clusters`, and `confidence_components`, through the
   data access layer.
9. **Generate labels.** Build one QR label per location that holds at
   least one item, plus one QR label for any item stored outside a
   container. Save each label's image to `qr_output_dir`, and insert a
   row into `qr_labels`.

---

## Presentation Plan

**Slides.** The Entity-Relationship Diagram (ERD) for the chosen schema,
the SQLite-to-MariaDB switch strategy, the ChromaDB vector store and how
it connects to the relational schema, and the key design decisions:
normalization choices, confidence scoring, and clustering.

**Demonstration.** Run the pipeline against a small sample photo set,
live. Show the populated SQLite database. Run a few queries and reports
against it, for example: items below the confidence threshold, item
count per cluster, and item count per location. These queries show the
value of a relational backend over a flat spreadsheet.

---

## Open Decisions

| Decision | Options | Tradeoff |
|---|---|---|
| Inventory domain (final scope) | Option A, B, or C above | Each schema is already sized and reviewed. The final pick depends on which domain the team can source real sample photos and data for |
| MariaDB driver | `mariadb` connector vs. `PyMySQL` | The `mariadb` connector is native and faster. `PyMySQL` is pure Python and needs no system library |
| Label print method | Adhesive label printer vs. plain paper cut to size | A label printer applies faster. Paper needs tape or a plastic sleeve for durability |
| Multi-object images | One row per photo vs. one row per detected object | Per-object needs a detection step first. Per-photo stays simpler for the MVP |
| Report export | Keep an optional CSV/XLSX export of query results vs. skip it | An export gives a quick offline view. The SQL queries already cover the demo requirement on their own |

The domain choice is the most consequential decision left. Everything
else in this plan works the same way under any of the three options.
