# Minecraft data layout and RAG build

Jenny reads a Minecraft **instance folder**, not a special combined JSON file. By default, the instance's `mods/` and `config/` directories are expected at the repository root:

```text
Jenny/
  mods/                         # mod JARs, directly here or in subfolders
    create-1.21.1.jar
    addons/another-mod.jar
  config/                       # actual text config files, nested folders allowed
    create-common.toml
    jei/...
  data/                         # generated, ignored by Git
```

For a launcher or server instance elsewhere, pass its actual directories to the builder:

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

The `mods/`, `config/`, generated `data/`, local SQLite memory, and runtime logs are ignored by Git. They belong to each installation and should not be committed unless you intentionally publish that pack's data.
