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

- `[paths]`: input photo folder, QR output folder, and log file.
- `[database]`: SQLite backend with the database at `./inventory.db`.
- `[chroma]`: where ChromaDB stores embedding vectors.
- `[models]`: model names and the Ollama URL
  (`http://localhost:11434`).
- `[vision]`: retry count, image size limit, and the prompt template
  path (`./prompts/vision_prompt.txt`).
- `[confidence]`: the two confidence weights. They must sum to 1.0.
- `[clustering]`, `[labels]`, `[location]`, `[output]`: label and
  output formatting options.

Do not commit `config.ini`. It is machine-specific and gitignored.

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

```sh
python -m inventory_machine.pipeline
```

The pipeline loads `config.ini`, writes logs to the file in
`[paths] log_file`, and creates the output directories.
