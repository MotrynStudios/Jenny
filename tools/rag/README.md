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

- Mod JARs are ZIP archives. Jenny reads Forge/NeoForge `META-INF/*mods.toml`, Fabric `fabric.mod.json`, Quilt `quilt.mod.json`, and legacy Forge `mcmod.info`. English localization is merged from JSON and old `.lang` files across resource namespaces.
- Recipe and advancement JSON is read from singular and plural Minecraft data folders across namespaces, including namespaces that differ from a loader mod ID. JSON up to 1 MB per file in common datapack data and mod-owned `assets/*/custom/*/data/` folders is also flattened and indexed, with a 500-record per-archive cap. TaCZ gunpack JSONC remains parsed into typed gun, ammunition, and attachment stats.
- Texture filenames and model-to-texture references are indexed as a compact asset manifest. Image bytes and visual appearance are not embedded; answering what an image depicts would require a separate local vision-captioning or image-embedding stage.
- Text config files are read recursively. Supported extensions are `.toml`, `.json`, `.json5`, `.yaml`, `.yml`, `.properties`, `.cfg`, `.conf`, `.ini`, `.snbt`, and `.txt`.
- Files over 2 MB and binary files are skipped. `.bak` files are skipped because their extension is unsupported. Config text is indexed as text; the builder does not evaluate config expressions or infer runtime behavior.
- Common credential-looking values are redacted before indexing, but this is best-effort. Review generated files before sharing them.

## Coverage and limits

Extraction is format-driven, not a universal mod API. Minecraft versions change folder names and schemas; the extractor handles singular and plural recipe/advancement folders but does not validate game-version or loader constraints. Forge/NeoForge, Fabric, Quilt, and legacy Forge metadata are recognized. Common text configs are indexed as text with best-effort credential redaction. Custom binary databases, generated runtime recipes, and proprietary mod-specific encodings are not interpreted automatically. Add a focused parser when a mod's content does not use the covered JSON or text layouts.

The Timeless & Classics Guns (TaCZ) core JAR stores gun data in a custom gunpack under `assets/tacz/custom/<pack>/data/tacz/data/`. Jenny extracts its JSONC stat records and indexes the numeric values. Other mods may use different schemas. `/searchpack` searches processed documents, and `/recipe` browses known outputs and ingredients from standard and supported custom files. Workbench recipes under `assets/*/custom/*/data/*/recipe(s)/` are also indexed for chat retrieval. Rebuild after adding or updating mods.

RAG has been tested with **Minecraft 1.21.1 NeoForge mods**. Other mods, loaders and versions may work, but coverage is incomplete and extraction can miss or misread some data. If your mod is missing or its data is wrong, follow the [reporting guide](../../SUPPORT.md).

The recipe browser also reads extracted custom workbench records. TaCZ cards show the Gun Smith Table and material counts. A grid is displayed only when the source supplies a pattern and key. Ingredient searches include tag membership where the extracted files describe it.

One bot installation has one shared index for every Discord server it serves. Different pack corpora currently need separate installations; per-server index selection is not implemented.

The builder writes extracted inputs to `data/raw_data/`, searchable evidence to `data/processed/all_documents.json`, and the vector index to `data/embeddings/`. The bot's startup warning about `all_documents.json` means the extraction/build step has not completed successfully or the bot is pointed at a different project folder. Run the builder after adding or updating a pack.

## Build all stages

Run the combined builder from the repository root so extraction, document processing, and vector indexing happen in sequence:

```powershell
.\.venv\Scripts\python.exe tools\rag\build_index.py --mods-dir .\mods --config-dir .\config
```

On macOS or Linux, use `./.venv/bin/python tools/rag/build_index.py --mods-dir ./mods --config-dir ./config`. Running `extract_modpack_data.py` alone creates the raw data, manifest, and trivia bank. `process_for_rag.py` alone creates `all_documents.json`.

## Prebuild the trivia bank

Extraction requests up to 100 questions each for descriptions, recipes, and items/blocks. The target is divided across easy, medium, and hard. It sends small batches of mod descriptions, localized item names, and supported recipe ingredients to the last configured provider in the default text route first. It tries the other configured text providers when needed. Configuration files are not part of trivia generation.

Questions live in `data/trivia_cache.sqlite3`. A source key ties each question to a fact in the current extraction. Rebuilding reuses matching questions and fills missing slots. Older uncategorized questions are left in the database for solve history. Shortfalls are printed per category when facts or provider quota run out.

Use `build_index.py --trivia-only` to fill the question bank from existing extracted files, or `build_index.py --skip-trivia` to build the search index without sending model requests. Server administrators can also use `/generatetrivia` to request up to 100 fresh questions for a selected category and difficulty. Recipe clues use supported crafting, cooking, stonecutting, smithing, and TaCZ workbench layouts.

Mob coverage is partial. Search can find extracted mob-related data such as entity loot tables, tags, biome modifiers, and texture references when a mod ships them in supported layouts. The extractor does not build a dedicated mob registry or derive health, attacks, behavior, or spawn rules from Java code.

## Build resource use

Indexing runs the local sentence-transformer model over every evidence document. A changed corpus fingerprint triggers a full vector-index rebuild, even when only some documents changed. Defaults limit PyTorch to 2 CPU threads, use 64-document Chroma batches, and embed 16 texts at a time. Configure `RAG_CPU_THREADS`, `RAG_INDEX_BATCH_SIZE`, and `RAG_EMBED_BATCH_SIZE` in `.env` to trade build speed for lower peak CPU and memory use. These settings do not change the embedding model or answer quality. Keep the current build running when possible; stopping midway leaves an incomplete generated index that must be rebuilt.

## Troubleshooting an empty index

Check the stages in order:

1. `logs/extraction.log` should finish with a non-zero number of processed mods and extracted config files. Individual unsupported or malformed mod metadata can be skipped; fix parser errors before relying on a complete pack inventory.
2. `data/processed/all_documents.json` should exist and contain documents. `logs/processing.log` reports the total and document types.
3. `logs/jenny_rag.log` should end with `Collection population complete`; `data/embeddings/rag_manifest.json` should record the document count.
4. The combined builder prints `Index ready: N evidence documents`. A `chroma.sqlite3` file may exist even when the collection has zero vectors, because the bot creates the empty collection at startup.

If indexing fails while adding a batch, inspect the first Chroma metadata validation error in `logs/jenny_rag.log`. Mod language data can contain nested arrays or objects. The indexer converts those values to JSON strings before sending them to Chroma. After updating the code, rerun the combined builder so it can rebuild the collection from the processed JSON.

The `mods/`, `config/`, generated `data/`, local SQLite memory, and runtime logs are ignored by Git. They belong to each installation and should not be committed unless you intentionally publish that pack's data. The runtime adapter and voice HTTP bridge live at the repository root because the Discord application imports and runs them; this folder is for offline RAG build tools only.
