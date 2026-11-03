# Jenny Discord Bot

Jenny is a multi-server Discord bot with persistent chat context, searchable server history, Minecraft mod and config retrieval, image/GIF analysis, and an optional voice companion service. Guild settings, profiles, usage totals, and channel memories stay scoped to their server. A person's long-term memory follows their stable Discord user ID across DMs, server text, and voice, while short conversation histories remain separate by conversation.

Jenny uses the Jenny Belle character profile in `Jenny/Prompts.py`: a 19-year-old freelancer from Long Beach, Los Angeles, who has played Minecraft since 2018. She likes relaxed chats, creative projects, cats, and clever jokes; she dislikes bullying, needless drama, and confident guessing. She is written to sound relaxed and personable while being transparent that Jenny is an AI bot when asked. Server text and voice prompts include the current speaker's and Jenny's live server roles; DM prompts do not have server roles.

> **License status:** This project does not yet include a license. Until its owner selects one, GitHub visitors can view the code but do not have an explicit license grant to reuse or redistribute it.

The bot grounds Minecraft claims in the local mod/config corpus configured for that Jenny installation. At present, one installation has one shared RAG index for every Discord server it serves. If different servers use different modpacks, run separate bot installations or keep that limitation in mind; per-guild indexes are not implemented yet. When local evidence is missing, Jenny can use web search for background and labels it as external rather than treating it as proof of the installed pack. This reduces unsupported claims; no language model can guarantee zero hallucinations, so review high impact answers and tune retrieval against your own files.

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer
- Node.js 22.12 or newer for voice features (`@discordjs/voice` requirement)
- FFmpeg available on `PATH` for voice playback
- One Discord application and bot token, shared by the Python and optional Node.js processes
- OpenRouter, Groq, Gemini, Tavily, and Deepgram API keys as configured in `.env.example`

## Install

1. Clone/download this repository and open a terminal in its folder.
2. Create and activate a Python virtual environment, then install dependencies:

   ```powershell
   py -3.10 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

   On macOS/Linux, use `python3 -m venv .venv` and `source .venv/bin/activate`.

3. Copy `.env.example` to `.env` and add the single bot token and provider keys. Do not commit `.env`.
4. In the Discord Developer Portal, enable **Message Content Intent** and **Server Members Intent** for the bot. Invite it with the `bot` and `applications.commands` scopes and permissions to view/send messages, read message history, embed links, attach files, and manage roles if you plan to use role assignment. Only grant Manage Roles if needed; Discord's role hierarchy still limits assignments.
5. Start the text bot:

   ```powershell
   .\.venv\Scripts\python.exe Jenny\Jenny-Bot.py
   ```

   Or run `start.bat` on Windows after Python is available on `PATH`.

## Voice service (optional)

Voice runs in a separate Node.js process, but uses the same Discord application, bot token, and root `.env` as Python. It is optional: text, DMs, slash commands, and RAG run without Node. Enable voice connection permissions for the existing bot. The Python bot's local API listens on `127.0.0.1:8000` by default; keep it local unless you add authentication and TLS.

From the repository root:

```powershell
cd voice_service
npm install
npm start
```

The shared bot joins the voice channel of the user who requests it. Use `/joinvc`, `/leavevc`, and `/voicestatus`; spoken reply behavior is controlled with `/replymode`. Voice transcription tries Groq Whisper with the primary key, then the backup key using the same model. Speech output uses Deepgram Flux Haley. Both Python and Node log in as the same bot identity.

For voice replies with multiple sentences, Jenny starts playing the first sentence while later sentences are synthesized. Single-sentence replies still wait for the speech provider to finish generating that audio.

## Minecraft RAG data

Place the Minecraft instance's `mods/` and `config/` folders beside this repository, or pass their paths to the builder. The one-time extraction and indexing pipeline is kept under `tools/rag`:

```powershell
   .\.venv\Scripts\python.exe tools\rag\build_index.py --mods-dir .\mods --config-dir .\config
```

The builder runs all three stages in order: JAR/config extraction, searchable document generation, then ChromaDB embedding/index creation. Running `extract_modpack_data.py` by itself only completes the first stage, so it does not create `data/processed/all_documents.json` or populate ChromaDB. Generated indexes and extracted data are local runtime artifacts and are ignored by Git. Re-run the builder after changing mods/configs. Do not publish a pack's private configuration or credentials.

Supported config formats include TOML, JSON/JSON5, YAML, properties, CFG, CONF, INI, SNBT, and TXT. Unsupported formats are skipped. Files larger than the extraction limit are skipped. Treat any redaction as best-effort and review extracted output before sharing it.

See [tools/rag/README.md](tools/rag/README.md) for the exact expected folder layout, supported extensions, extraction boundaries, build command, and troubleshooting. The startup warning `all_documents.json` not found means the processing stage did not produce the corpus in the bot's `data/processed` folder. A `chroma.sqlite3` file alone does not prove that it contains vectors; check the builder's final document count and generated `data/embeddings/rag_manifest.json`.

Jenny cites retrieved evidence sources in modpack answers. `RAG_MAX_DISTANCE` controls which vector matches count as evidence: lower values are stricter, but may miss relevant material. Tune it with representative questions. If no local evidence qualifies, the answer should say what is unknown; web results are supplementary context only.

At runtime, vector retrieval is limited to Minecraft/mod/config questions and short follow-ups to recent related turns, so casual chat does not load the embedding model. A non-empty index is warmed in a background task after Discord connects, including a persisted index whose source JSON is temporarily missing. An empty index does not trigger an embedding-model download. Shared server chat logs are added to prompts only when a message asks about chat history or what other members said.

## What the bot can do

- Reply to every message in a server's configured main channel, mentions/replies elsewhere, and every DM.
- Keep bounded recent context plus automatically summarized long-term channel, voice, and user memory. Active streams are checked every 15 minutes; a new stream gets an initial summary, then summaries run after 25 new records or six hours of activity.
- Search recent stored server chat and summarize channels.
- Answer server, member, profile-history, last-message, and token-usage questions; `/help` privately lists commands available to the caller, `/serverinfo` shows activity windows, and `/user` shows member stats.
- Show member avatars and roles. Assign and remove roles only when the requester is an administrator, outranks the role, and Jenny also has Manage Roles and outranks it.
- Include the current speaker's and Jenny's actual guild roles in server text and voice context, so role-aware answers use live server information.
- Show a Minecraft Singleplayer 26.3 Playing activity with elapsed time in the title, refreshed once per minute and reset when the Python bot restarts.
- Analyze attached and replied-to images. Animated GIFs are sampled at up to three frames before their visual evidence is passed to the chat model. Recent image context can be reused during text and voice follow-ups.
- Transcribe voice-message attachments posted in Jenny's configured channel.
- Send incoming server messages, Jenny's generated replies, and profile events to the selected logs channel. Direct messages stay private in the local database.
- Show per-user AI token counts plus speech-to-text and text-to-speech processing time for daily, weekly, and monthly periods. Server-wide usage is administrator-only; `/myusage` shows only the caller's totals.
- Browse the latest 100 voice inputs and stage timings with `/voicetimes`; full turn records are written to the ignored `logs/voice-turns.jsonl` file.
- Keep separate Python and Node terminal logs in `logs/python-runtime.log` and `logs/voice-runtime.log`. Logs rotate or are pruned automatically and remain local.
- Let users privately view `/mymemory` or clear conversation memory with `/forgetmydata`. Detailed chat, voice, profile-history, token, and speech records are pruned after the configured retention period (`DATA_RETENTION_DAYS`, default 90).
- Search the indexed mod/config corpus, with optional web lookup when local evidence is missing.

## How conversation summaries work

Jenny stores a short recent conversation window separately from long-term summaries. The short window holds up to 24 message entries, about 12 user and assistant exchanges, for each user and conversation. A server channel, voice room, and DM do not share the same raw chat history.

When a message is logged, Jenny increments that stream's activity counter. A new stream gets its first summary after activity is detected. After that, a background task picks it up at 25 new records or after six hours of accumulated activity. The task checks every 15 minutes and summarizes at most 30 unprocessed records per run. If a provider returns invalid JSON, Jenny retries once with at most 10 records; repeated failures use increasing delays up to six hours instead of retrying on every scheduler pass. The task sends those records and the existing relevant summary and user memories to the configured language model, which returns a channel summary and participant memory updates. Jenny saves those summaries in SQLite and advances the stream's processed-record cursor.

Server text summaries are scoped to their text channel; voice summaries are scoped to their server. Personal long-term memory uses the user's stable Discord ID and is shared across that person's DMs, server text, and server voice. Older server- or DM-scoped user memories remain readable and are merged into the shared memory as summaries run. `/mymemory` shows shared and current-scope memory. `/forgetmydata` clears the caller's Jenny conversation histories and saved memories across all scopes. System maintenance notes are excluded from activity counts and summary input. If more than 30 records are waiting, the remaining count is retained so later runs continue processing the backlog.

The default 90-day cleanup removes old detailed message, voice, usage, profile-history, image-context, and short conversation-history records. Rolling summaries are retained until the user clears their memory with `/forgetmydata` or an administrator clears their history. This lets Jenny remember useful context without keeping every raw conversation indefinitely.

See [CHANGELOG.md](CHANGELOG.md) for Jenny's current 0.85 feature list. Discord does not expose members' private profile bios through the bot API.

The activity is a bot-supported Playing status, not the full Rich Presence integration available to desktop games. The elapsed time is shown as text and advances once per minute.

Memory and searchable logs are stored locally in SQLite (`Jenny/memory.db`). They are not shared across installations. Users with access to the host can access that database, so apply appropriate filesystem and backup controls.

## Configuration notes

- `.env` is shared by both processes. The text fallback order is OpenRouter GPT-OSS 120B, Groq GPT-OSS 120B, Groq backup with that same model, then Gemini 3.6. Vision uses Qwen 3.8 27B on Groq and its backup key, then Gemini. Tavily uses the primary key and then its backup key.
- Backup credentials do not use separate model settings: each retry uses the same model ID as its primary provider.
- Set server channels and voice reply modes using the bot's slash commands. Guild configuration is stored per server.
- Global slash commands replace prior global definitions; startup also removes leftover guild-scoped copies from old development runs. New global command updates can take time to appear in Discord.
- For safety, keep bot tokens and API keys out of source control, screenshots, logs, and shared RAG documents. Rotate credentials immediately if exposed.

## Project layout

```text
Jenny/                    Discord bot, prompts, SQLite memory, commands, and game activity
tools/rag/                One-time mod/config extraction, processing, and index build tools
voice_service/            Optional Node voice capture, transcription, and speech playback
jenny_api_server.py       Always-running local HTTP bridge used by the voice process
jenny_rag_integration.py  Runtime retrieval adapter imported by the Discord bot
data/                     Local extracted documents and ChromaDB index, generated per installation
requirements.txt          Python dependencies
```

The two root-level Python modules are runtime components, not extraction tools. `jenny_api_server.py` connects the optional Node voice process to the already-running Python bot, and `jenny_rag_integration.py` is imported by the bot for live retrieval. The `tools/rag/` folder contains commands that an owner runs to build or refresh local modpack data.
