# Setup Guide

This guide gets Inventory Machine running from a clean checkout.
Complete the Ollama steps first. The pipeline needs the vision and
embedding models running locally.

## 1. Install Ollama and pull the models

Follow `Ollama_Setup.md`. It covers installing Ollama and pulling the
three models: `minicpm-v4.6`, `granite4.2:3b`, and
`qwen3-embedding:0.6b`. Check each step before you continue.

## 2. Create a virtual environment and install the project

Run these commands from the repository root. Python 3.11 or later is
required.

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

## 4. Run the tests

```sh
pytest tests/
```

All 12 tests should pass. This confirms the package, the config, and
the database layer are set up correctly.

## 5. Run the pipeline

```sh
python -m inventory_machine.pipeline
```

The pipeline loads `config.ini`, sets up logging to the file in
`[paths] log_file`, and creates the output directories.
