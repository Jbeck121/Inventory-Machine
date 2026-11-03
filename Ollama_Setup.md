# Ollama Setup Guide

This guide explains how to install Ollama and pull the models that
Inventory Machine uses. Follow these steps before you run the pipeline
locally.

## 1. Install Ollama

Go to [ollama.com/download](https://ollama.com/download). Get the
installer for your OS.

- **Mac / Windows:** Run the installer and follow the prompts.

You do not need an account or a sign-in to use the model locally.
Select **skip/use locally**.

## 2. Verify the install

Open a terminal, command prompt, or PowerShell window. Run
`ollama --version`. The version number should be 0.34.0. If the command
prints a version number, Ollama works. If it shows "command not found,"
close and reopen the terminal or command prompt.

## 3. Pull the models

1. Run `ollama pull minicpm-v4.5`. This is the default vision model
   in config.ini.example. It is around 5.5gb and takes about 5 minutes
   to pull.
2. Run `ollama pull minicpm-v4.6`. This is the fallback vision model
   for hardware that cannot run minicpm-v4.5. The
   `vision_model_fallback` setting in config.ini.example names it.
3. Run `ollama pull qwen3-embedding:0.6b`. This is the embedding model.
4. After the download, enter input in the prompt window to chat with
   the model if the setup worked.
   These model commands are the ones used here. Run `/?` for more:
   - `/bye` = exit
   - `/show` = show model info
   - `/clear` = clear session context
   - `/?` = show shortcuts
5. Run `ollama list` to check all 3 models. The output should show each
   model's size, ID, name, and modification time.

If you see a "digest mismatch" error, pull that model again. You can
also remove the model and pull it again. To remove it, run
`ollama rm minicpm-v4.6`.

## 4. Optional: testing Ollama itself

`granite4.2:3b` is not a pipeline dependency. It is a small chat model
that confirms Ollama works before you use the vision and embedding
models above.

Run `ollama pull granite4.2:3b` (around 2.2gb, about 3-4 minutes).
Then run `ollama run granite4.2:3b`. This command opens the granite
library for input if the pull did not open its window automatically.
