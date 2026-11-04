# Jenny file-by-file guide

This guide covers the public source files and the current workspace additions intended for publication. The published `main` can lag behind a local development copy. Generated data is listed separately.

## How the pieces connect

1. Discord events reach `Jenny/Jenny-Bot.py`. It builds context, calls a model, and sends a conversational reply or dispatches a model-selected command.
2. Slash and model-selected commands use the same handlers in `Jenny/discord_commands.py`. The dispatcher checks the caller and validates arguments. Discord still enforces role hierarchy and channel permissions.
3. The optional Node service joins voice and handles audio. It exchanges join status, transcripts and speech requests with `jenny_api_server.py` on loopback. Node does not register slash commands.
4. The offline Minecraft build extracts JAR and config data, then turns it into searchable text. The Python runtime reads the generated files for pack commands and uses the vector index for relevant conversational questions.

## Python runtime

| File | Responsibility |
| --- | --- |
| [`Jenny/Jenny-Bot.py`](Jenny/Jenny-Bot.py) | Startup, Discord events, server and DM chat, scoped reply context, automatic maintenance, presence, and the API bridge. |
| [`Jenny/Prompts.py`](Jenny/Prompts.py) | Jenny's character, channel-specific prompt rules, grounding instructions, and the memory update format. |
| [`Jenny/prompt_builder.py`](Jenny/prompt_builder.py) | Assembles bounded recent history, summaries and the active request for text, voice or maintenance. |
| [`Jenny/ai.py`](Jenny/ai.py) | Provider clients, fallback routes, rate limit handling, usage accounting, text, vision, voice-note transcription and trivia generation. |
| [`Jenny/search.py`](Jenny/search.py) | Tavily search and backup-key fallback. |
| [`Jenny/discord_commands.py`](Jenny/discord_commands.py) | Slash commands, permission checks, embed pagers, trivia rounds, usage views and web search modal. |
| [`Jenny/model_commands.py`](Jenny/model_commands.py) | Parses the model's command output and routes it through the registered slash handler using the real caller and channel. |
| [`Jenny/issue_reporting.py`](Jenny/issue_reporting.py) | Collects an explicit public bug report in Discord and submits it to the configured GitHub issue tracker. |
| [`Jenny/pack_browser.py`](Jenny/pack_browser.py) | Indexes recipe outputs, ingredients, known item tags, names and mod entries for autocomplete and recipe cards. |
| [`Jenny/trivia_bank.py`](Jenny/trivia_bank.py) | Collects pack facts and builds or loads questions by category and difficulty. |
| [`Jenny/trivia_cache.py`](Jenny/trivia_cache.py) | SQLite storage for validated questions and solve times. |
| [`Jenny/database.py`](Jenny/database.py) | SQLite schema, migrations, history, summaries, profiles, guild settings, usage, activity and cached results. |
| [`Jenny/memory_maintenance.py`](Jenny/memory_maintenance.py) | Reads eligible conversation records, validates summary responses and saves progress. |
| [`Jenny/rich_presence.py`](Jenny/rich_presence.py) | Updates Jenny's Minecraft Playing activity and elapsed process time. |
| [`Jenny/runtime_logging.py`](Jenny/runtime_logging.py) | Mirrors stdout and stderr into a rotating Python log. |
| [`Jenny/utils.py`](Jenny/utils.py) | Jenny name recognition, modpack query hints and reply cleanup. |
| [`jenny_api_server.py`](jenny_api_server.py) | FastAPI loopback interface for voice operations, transcripts, health and timing records. |
| [`jenny_rag_integration.py`](jenny_rag_integration.py) | Loads the local corpus, embeddings and Chroma index, then retrieves relevant pack evidence. |

## Voice and extraction

| File | Responsibility |
| --- | --- |
| [`voice_service/index.js`](voice_service/index.js) | Discord voice connection, speech capture, Whisper transcription, the Python bridge, Flux synthesis and playback. |
| [`voice_service/package.json`](voice_service/package.json) | Node version requirement, launch scripts and direct dependencies. |
| [`voice_service/package-lock.json`](voice_service/package-lock.json) | Resolved dependency tree used by `npm ci`. Regenerate it with npm when dependencies change. |
| [`tools/rag/build_index.py`](tools/rag/build_index.py) | Runs the extraction, document processing and vector index stages. |
| [`tools/rag/extract_modpack_data.py`](tools/rag/extract_modpack_data.py) | Reads mod JARs and supported text configs, writes a manifest, and optionally seeds trivia. |
| [`tools/rag/process_for_rag.py`](tools/rag/process_for_rag.py) | Turns extracted data into searchable documents and records document statistics. |
| [`tools/rag/README.md`](tools/rag/README.md) | Data layout, supported formats, build flags and troubleshooting. |

## Setup, documentation and GitHub

| File | Responsibility |
| --- | --- |
| [`.env.example`](.env.example) | Safe sample settings. Copy it to `.env` and fill in your own keys. |
| [`requirements.txt`](requirements.txt) | Python dependencies for chat, local retrieval and the voice API. |
| [`start.bat`](start.bat) | Starts the Python runtime on Windows. |
| [`RUN_VOICE_SERVICE.bat`](RUN_VOICE_SERVICE.bat) | Starts the Node voice service on Windows. |
| [`start_hybrid_system.bat`](start_hybrid_system.bat) | Checks the running Python API and starts the optional voice window. |
| [`.gitignore`](.gitignore) | Excludes secrets, dependencies, Minecraft inputs and generated runtime state. |
| [`README.md`](README.md) | Quick start, Discord setup, keys, features, FAQ and support. |
| [`CONFIGURATION.md`](CONFIGURATION.md) | Every environment setting, defaults, storage and privacy. |
| [`PROJECT.md`](PROJECT.md) | This file inventory and runtime overview. |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history and current unreleased changes. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution rules and local validation commands. |
| [`SUPPORT.md`](SUPPORT.md) | Contact and reporting instructions. |
| [`SECURITY.md`](SECURITY.md) | Private vulnerability reporting. |
| [`LICENSE`](LICENSE) | MIT license and copyright notice. |
| [`.github/workflows/validate.yml`](.github/workflows/validate.yml) | Python and Node syntax checks on pushes and PRs. |
| [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) | Prompts for describing changes and checks. |
| [`.github/ISSUE_TEMPLATE/bug_report.yml`](.github/ISSUE_TEMPLATE/bug_report.yml) | Collects steps, version information and sanitized errors. |
| [`.github/ISSUE_TEMPLATE/feature_request.yml`](.github/ISSUE_TEMPLATE/feature_request.yml) | Collects feature ideas and the contexts they affect. |
| [`.github/ISSUE_TEMPLATE/config.yml`](.github/ISSUE_TEMPLATE/config.yml) | Configures the issue chooser and private reporting link. |
| `config/.gitkeep`, `data/.gitkeep`, `mods/.gitkeep` | Empty placeholders that can keep the expected directories in Git. |

The published version has a second `Jenny/.gitignore`. Its rules duplicate the root ignore file, so the cleaned source keeps the root copy.

## What stays local

Credentials and old voice environment files, the virtual environment, Node dependencies, databases and backups, logs, mod JARs, config files and the generated vector index are installation data. An unused local Minecraft icon is also excluded. The application uses a plain Discord Playing activity.

## Review notes

The source syntax workflow can catch Python or JavaScript parse errors. It does not connect to Discord, use API credits, or prove that a particular JAR format works. Check provider behavior and representative mods separately before documenting them as supported.
