# Inventory Machine

Inventory Machine reads a folder of item photos and builds a searchable,
relational inventory from them. A local vision-language model tags and
describes each photo. A local embedding model groups similar items into
clusters. The pipeline stores every item, tag, image, and cluster in a
normalized SQL database, and it prints a QR-code label for each storage
location.

This repository supports a COCS 640 (Database Systems I) course project,
Milestone 1, taught by Dr. Muhammad. Team members: Jesse Beck, Richard
Baldwin, Kian Dong, and Reece Clem.

## Status

The project has a working package under `inventory_machine/`. The test
suite has 40 passing tests. It skips 1 MariaDB test unless you set
`IM_MARIADB_DSN`. `pipeline.py` connects all 9 steps. Three teammate
functions are not in the package yet. Until they are, the pipeline
raises `RuntimeError` and names each missing function:
`preprocessing.prepare_image` (resize),
`preprocessing.resolve_location_id` (location rows), and
`labels.write_qr_labels` (QR label rows).

- The `inventory_machine/` directory holds the package code. The
  `config.py` module loads and validates config. The `db.py` module
  handles data access for SQLite and MariaDB. The `pipeline.py` module
  connects the steps and `processing_runs`. The `preprocessing/`
  directory walks folders and reads EXIF. The `vision/client.py` module
  calls the Ollama vision model.

  The `embedding/client.py` module calls the Ollama embedding model
  and stores vectors in ChromaDB. The `scoring/` directory calculates
  confidence scores. The `clustering/` directory runs HDBSCAN and
  labels clusters. The `labels/` directory makes QR images.
- `pyproject.toml` makes the package installable with
  `pip install -e ".[dev]"`.
- `config.ini.example` shows every config section the code reads. Copy
  it to `config.ini` to run locally.
- `prompts/vision_prompt.txt` is the prompt template the vision client
  sends with each photo.
- `tests/` holds the pytest suite. Run it with `pytest tests/`.
- `plan.md` holds the full technical plan: architecture, AI models, the
  database design, the QR label strategy, the config file, the
  processing pipeline, and the presentation plan.
- `schema/` holds the SQL schema files.

See `SETUP.md` for install and test instructions.

## Scope: MVP vs. ideal final

### MVP

The MVP is the basic inventory machine from the original plan. It has
one pipeline, one domain-agnostic schema, and no business-specific
tables. It ingests photos, tags and describes each item, and embeds
and clusters similar items. It stores everything in SQLite and prints
a QR label for each storage location.

`schema/schema.sql` holds this MVP schema. It has 11 tables: locations,
clusters, items, images, tags, item_tags, confidence_components,
embeddings_index, vision_model_outputs, qr_labels, and processing_runs.

### Ideal final

The course requires 15 to 30 normalized tables. The ideal final build
adds one real inventory domain to the MVP schema to reach that range.
It does not add tables that model nothing real. The "Implementation
Options Under Consideration" section of `plan.md` describes three
domain candidates and the reasons for each. The `schema/` directory
holds one full, standalone schema per candidate:

| File | Domain | Total tables |
|---|---|---|
| `schema/option_a_home_organizer.sql` | Home organizer: household items in crates and drawers | 24 |
| `schema/option_b_university_it.sql` | University IT asset management: laptops, labs, and support tickets | 28 |
| `schema/option_c_spark_labs.sql` | FSU Spark Labs inventory: a research and makerspace lab | 30 |

The team picked Option A (24 tables) on 2026-10-19. If review cuts it
below 15 tables, the team switches to Option B or C. Each file runs
standalone against a fresh SQLite database.

## Database

SQLite serves development. One data access layer handles every SQL
call. The team can later switch to MariaDB by changing only a
connection string. The "Database Design" section of `plan.md`
describes the switch strategy and the three syntax differences it must
handle.

## Workflow

Each team member uses a branch from `main` for their assigned part of
the pipeline. Push to your own branch. Open a PR or flag it in Teams
for someone else to merge into `main` after it runs. Log any decision
that changes another member's assigned task in `Assist/HANDOFFS.md`
before that member starts the affected work.

## Documentation

- `plan.md`: the full technical plan.
- `SETUP.md`: install and test instructions for a clean checkout.
- `Ollama_Setup.md`: how to install Ollama and pull the models.
- `schema/schema.sql`: the core MVP schema.
- `schema/option_a_home_organizer.sql`, `schema/option_b_university_it.sql`,
  `schema/option_c_spark_labs.sql`: one full example schema per domain
  option under consideration for the final build.
