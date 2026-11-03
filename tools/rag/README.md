# Minecraft data layout and RAG build

Jenny reads a Minecraft **instance folder**, not a special combined JSON file. By default, the instance's `mods/` and `config/` directories are expected at the repository root:

This build creates one local index for the whole bot installation. Every Discord server connected to the same bot process uses that corpus. Separate installations are needed if servers must use different modpack data; the current code does not select indexes per guild.

```text
<repository-root>/
  Jenny/                        # Discord bot runtime
  tools/rag/                    # one-time extraction and index commands
  mods/                         # mod JARs, directly here or in subfolders
    create-1.21.1.jar
    addons/another-mod.jar
  config/                       # actual text config files, nested folders allowed
    create-common.toml
    jei/...
  data/                         # generated, ignored by Git
```

For a launcher or server instance elsewhere, pass its actual directories to the builder. Run the builder from any working directory; it resolves its project root from its own file location:

```powershell
.\.venv\Scripts\python.exe tools\rag\build_index.py `
  --mods-dir "D:\Minecraft\Instances\My Pack\mods" `
  --config-dir "D:\Minecraft\Instances\My Pack\config"
```

## What gets read

- Mod JARs are ZIP archives. Jenny reads Forge/NeoForge `META-INF/*mods.toml`, English language JSON under `assets/<mod-id>/lang/`, and recipe and advancement JSON under `data/<mod-id>/recipe(s)/` and `advancement(s)/`.
- Text config files are read recursively. Supported extensions are `.toml`, `.json`, `.json5`, `.yaml`, `.yml`, `.properties`, `.cfg`, `.conf`, `.ini`, `.snbt`, and `.txt`.
- Files over 2 MB and binary files are skipped. `.bak` files are skipped because their extension is unsupported. Config text is indexed as text; the builder does not evaluate config expressions or infer runtime behavior.
- Common credential-looking values are redacted before indexing, but this is best-effort. Review generated files before sharing them.

The builder writes extracted inputs to `data/raw_data/`, searchable evidence to `data/processed/all_documents.json`, and the vector index to `data/embeddings/`. The bot's startup warning about `all_documents.json` means the extraction/build step has not completed successfully or the bot is pointed at a different project folder. Run the builder after adding or updating a pack.

## Build all stages

Run the combined builder from the repository root so extraction, document processing, and vector indexing happen in sequence:

```powershell
.\.venv\Scripts\python.exe tools\rag\build_index.py --mods-dir .\mods --config-dir .\config
```

On macOS or Linux, use `./.venv/bin/python tools/rag/build_index.py --mods-dir ./mods --config-dir ./config`. Running `extract_modpack_data.py` alone only creates `data/raw_data/`; it does not create the processed corpus or embeddings. `process_for_rag.py` alone creates `all_documents.json` but does not populate ChromaDB.

## Troubleshooting an empty index

Check the stages in order:

1. `logs/extraction.log` should finish with a non-zero number of processed mods and extracted config files. Individual unsupported or malformed mod metadata can be skipped; fix parser errors before relying on a complete pack inventory.
2. `data/processed/all_documents.json` should exist and contain documents. `logs/processing.log` reports the total and document types.
3. `logs/jenny_rag.log` should end with `Collection population complete`; `data/embeddings/rag_manifest.json` should record the document count.
4. The combined builder prints `Index ready: N evidence documents`. A `chroma.sqlite3` file may exist even when the collection has zero vectors, because the bot creates the empty collection at startup.

If indexing fails while adding a batch, inspect the first Chroma metadata validation error in `logs/jenny_rag.log`. Mod language data can contain nested arrays or objects. The indexer converts those values to JSON strings before sending them to Chroma. After updating the code, rerun the combined builder so it can rebuild the collection from the processed JSON.

The `mods/`, `config/`, generated `data/`, local SQLite memory, and runtime logs are ignored by Git. They belong to each installation and should not be committed unless you intentionally publish that pack's data. The runtime adapter and voice HTTP bridge live at the repository root because the Discord application imports and runs them; this folder is for offline RAG build tools only.
