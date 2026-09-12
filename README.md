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

The project is in the planning stage. No pipeline code exists yet. The
plan and the SQL schemas are complete and ready to build against.

- `plan.md` holds the full technical plan: architecture, AI models, the
  database design, the QR label strategy, the config file, the
  processing pipeline, and the presentation plan.
- `schema/` holds the SQL schema files.

## Scope: MVP vs. ideal final

### MVP

The MVP is the basic inventory machine originally planned: one pipeline,
one domain-agnostic schema, no business-specific tables. It ingests
photos, tags and describes each item, embeds and clusters similar items,
stores everything in SQLite, and prints a QR label for each storage
location.

`schema/schema.sql` holds this MVP schema. It has 11 tables: locations,
clusters, items, images, tags, item_tags, confidence_components,
embeddings_index, vision_model_outputs, qr_labels, and processing_runs.

### Ideal final

The course requires 15 to 30 normalized tables. The ideal final build
adds one real inventory domain on top of the MVP schema to reach that
range, instead of padding the MVP schema with tables that do not model
anything real. `plan.md`, under "Implementation Options Under
Consideration," describes the three domain candidates and the reasoning
behind each one. `schema/` holds one full, standalone schema per
candidate:

| File | Domain | Total tables |
|---|---|---|
| `schema/option_a_home_organizer.sql` | Home organizer: household items in crates and drawers | 24 |
| `schema/option_b_university_it.sql` | University IT asset management: laptops, labs, and support tickets | 28 |
| `schema/option_c_spark_labs.sql` | FSU Spark Labs inventory: a research and makerspace lab | 30 |

The team has not yet picked one of the three. Each file already runs
standalone against a fresh SQLite database.

## Database

SQLite serves development. One data access layer wraps every SQL call,
so the team can switch the backend to MariaDB later by changing only a
connection string. `plan.md`, under "Database Design," covers the
switch strategy and the two syntax differences it needs to handle.

## Documentation

- `plan.md`: the full technical plan.
- `schema/schema.sql`: the core MVP schema.
- `schema/option_a_home_organizer.sql`, `schema/option_b_university_it.sql`,
  `schema/option_c_spark_labs.sql`: one full example schema per domain
  option under consideration for the final build.
