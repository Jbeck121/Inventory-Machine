# Setup Guide

This guide helps you run Inventory Machine from a clean checkout.
Complete the Ollama steps first. Run the vision and embedding models
locally for the pipeline.

## 1. Install Ollama and pull the models

Follow `Ollama_Setup.md` to install Ollama and pull two vision models:
`minicpm-v4.5` (default) and `minicpm-v4.6` (fallback). Also pull the
embedding model `qwen3-embedding:0.6b`. The optional `granite4.2:3b`
model only confirms that Ollama works. The pipeline does not need it.
Check each step before you continue.

The pipeline calls Ollama through its OpenAI-compatible API at
`<ollama_base_url>/v1`. Ollama needs no key.

## 2. Create a virtual environment and install the project

Run these commands from the repository root. Use Python 3.11 or later.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`pip install -e ".[dev]"` installs the runtime dependencies from
`pyproject.toml` (ollama, Pillow, httpx, chromadb, hdbscan,
scikit-learn, PyMySQL, qrcode, flask) plus pytest for the tests.

On Windows, use `py -m venv .venv` and `.venv\Scripts\activate`
instead of the `source` command.

## 3. Create your config file

Copy the example config and edit it if your paths differ:

```sh
cp config.ini.example config.ini
```

The example works with no edits. It uses these settings:

- `[paths]`: input photo folder, QR output folder, resized photo
  folder (`prepared_dir`), and log file.
- `[database]`: SQLite backend with the database at `./inventory.db`.
- `[chroma]`: where ChromaDB stores embedding vectors.
- `[models]`: model names and the Ollama URL
  (`http://localhost:11434`).
- `[litellm]`: optional fallback. The example has it commented out.
  See "Optional: LiteLLM fallback" below.
- `[vision]`: retry count, image size limit, and the prompt template
  path (`./prompts/vision_prompt.txt`).
- `[confidence]`: the two confidence weights. They must sum to 1.0.
- `[labels]`: the base URL in each QR code and the label size in mm.
  The default base URL `http://localhost:5050` matches the web UI port.
- `[clustering]`, `[location]`, `[output]`: clustering and output
  formatting options.

Do not commit `config.ini`. It is machine-specific and gitignored.

### Optional: LiteLLM fallback

The pipeline always calls Ollama first. If Ollama does not answer, or
returns an error, the pipeline can send the same request to a LiteLLM
gateway. Without a `[litellm]` section, the pipeline uses Ollama only.

1. Get a LiteLLM virtual key that can call a vision model and the
   embedding model.
2. Add this section to `config.ini`, with your gateway URL and its
   exact model IDs:

   ```ini
   [litellm]
   base_url = http://<gateway host>:4000/v1
   vision_model = minicpm-v4.5:latest
   embedding_model = qwen3-embedding:0.6b
   ```

3. Export the key in the shell that runs the pipeline. The pipeline
   does not read the key from `config.ini`.

   ```sh
   export LITELLM_API_KEY=<your key>
   ```

Use the same embedding model on Ollama and on the gateway. ChromaDB
cannot compare vectors from two different embedding models. Each
`vision_model_outputs` row that the gateway answered has a model name
that starts with `litellm/`.

### Run against MariaDB

Start a local MariaDB container:

```sh
podman run -d --rm --name inventory-mariadb -e MARIADB_ROOT_PASSWORD=change-me -e MARIADB_DATABASE=inventory -p 127.0.0.1:3306:3306 docker.io/library/mariadb:11
```

Set these keys in the `[database]` section of `config.ini`:

```ini
[database]
backend = mariadb
mariadb_dsn = mariadb://root:change-me@127.0.0.1:3306/inventory
```

The `sqlite_path` key has no effect with `backend = mariadb`. Load
`schema/option_a_home_organizer.sql` with `Database.load_schema` before
you write inventory rows. When you finish, stop the container with
`podman stop inventory-mariadb`.

## 4. Run the tests

```sh
pytest tests/
```

Without `IM_MARIADB_DSN`, pytest skips the MariaDB integration test.
To run it, set `IM_MARIADB_DSN` to a fresh, empty MariaDB database.

## 5. Run the pipeline

Put photos in `[paths] input_dir` (default `./inventory_input`). The
folder path of each photo sets its location. For example,
`inventory_input/garage/toolbox/hammer.jpg` goes into the location
`garage > toolbox`.

```sh
python -m inventory_machine.pipeline
```

The pipeline loads `config.ini`, writes logs to the file in
`[paths] log_file`, and creates the output directories. It prints a
summary with the counts `processed`, `failed`, and `skipped`.

A second run skips each photo that already has a row in `images`. To
add photos, put them in the input folder and run the pipeline again.
Each run makes the clusters and the QR labels again from all items.

## 6. Print the labels

The pipeline writes one label image per location that holds items, and
one per item that has no location. The images go to
`[paths] qr_output_dir`. Each label is 62 x 29 mm at 300 DPI. The
pipeline also writes `label_sheet_<n>.png`, which puts the labels on
US Letter pages. Print the sheets at 100% scale.

For 0.5 in QR-only stickers, run `generate_sticker_page` after the
pipeline. It puts one sticker per location that holds items on one US
Letter page (80 stickers maximum) and writes `8.5x11_sticker_page.png`
to `[paths] qr_output_dir`:

```sh
python -c "from inventory_machine.config import load_config; from inventory_machine.db import Database; from inventory_machine.labels import generate_sticker_page; cfg = load_config(); print(generate_sticker_page(cfg, Database(cfg)))"
```

## 7. Run the web UI

Run this command from the repository root:

```sh
python web-ui/app.py
```

Open `http://localhost:5050`. The home page lists all items. You can
search descriptions and tags, and filter by location, cluster, tag, and
confidence flag. Each QR label opens a `/location/<id>` or
`/item/<id>` page.

The `/scan` page reads QR codes with the computer camera. Browsers
allow the camera only on `localhost` or on HTTPS.

The app listens only on `127.0.0.1`. A phone cannot open the label URLs
unless you serve the app on your network and set `[labels] qr_base_url`
to that address.
