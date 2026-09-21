# Ollama Setup Guide

This guide covers installing Ollama and pulling the models Inventory Machine
uses. Follow it before running the pipeline locally.

## 1. Install Ollama

Go to [ollama.com/download](https://ollama.com/download) and get the
installer for your OS.

- **Mac / Windows:** run the installer, follow the prompts.

Since we are planning to use the model locally, we do not need to make an account
or sign in, **skip/use locally**

## 2. Verify the install

Open a terminal/command prompt/powershell and run: ollama --version

Version number should be 0.34.0. If error message such as "command not found"
may need to close and reopen the 

If it prints a version number, you're good. If you get a "command not
found" error, close and reopen your terminal/command-prompt

## 3. Pull the models

A. `ollama pull minicpm-v4.5`
(the default vision model in config.ini.example; around 5.5gb, takes
like 5 minutes)

then

B. `ollama pull minicpm-v4.6`
(the fallback vision model, for hardware that can't run minicpm-v4.5 --
config.ini.example's `vision_model_fallback` setting)

then

C. `ollama pull qwen3-embedding:0.6b`
(the embedding model)

D. once downloaded, if everything was done correctly, prompt window 
should allow input to chat with the model.
Model commands (theres more, but these are the ones I used, run /? for the list)
-/bye = exit
-/show = shows model info
-/clear = clear session context
-/? = for shortcuts

E. use ollama list to see if all 3 were pulled correctly, should show size, ID, name, and when modified

**If error message labelling "digest mismatch" then you may need to to pull that model
again or remove it and pull it again
-removing the model = rm minicpm-v4.6

## 4. Optional: testing Ollama itself

`granite4.2:3b` is not a pipeline dependency. It's a small chat model
useful only for confirming Ollama itself works before touching the
vision/embedding models above.

Run: `ollama pull granite4.2:3b` (around 2.2gb, takes about 3-4 minutes),
then `ollama run granite4.2:3b`.

Should bring up the granite library to type, this step was done incase after you pulled granite 
and it didn't automatically pull up on the window
