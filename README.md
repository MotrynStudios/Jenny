# Jenny

Jenny is an open-source, multi-server Discord companion for relaxed chat, voice conversations, and grounded Minecraft modpack/config help.

Jenny is a multi-server Discord bot with persistent chat context, searchable server history, Minecraft mod and config retrieval, image/GIF analysis, and an optional voice companion service. Guild settings, profiles, usage totals, and channel memories stay scoped to their server. A person's long-term memory follows their stable Discord user ID across DMs, server text, and voice, while short conversation histories remain separate by conversation.

Jenny uses the Jenny Belle character profile in `Jenny/Prompts.py`: a 19-year-old freelancer from Long Beach, Los Angeles, who has played Minecraft since 2018. She likes relaxed chats, creative projects, cats, and clever jokes; she dislikes bullying, needless drama, and confident guessing. Her prompt avoids unprompted AI disclaimers and keeps a playful, occasionally sharp tone; if someone directly asks whether she is human, it answers honestly. Server text and voice prompts include the current speaker's and Jenny's live server roles; DM prompts do not have server roles.

## License and attribution

This project is released under the [MIT License](LICENSE), copyright Mohamed Ayman Elnashar. You may use, modify, and redistribute it, including in commercial projects. Keep the copyright and license notices with copies or substantial portions of the software. The MIT License does not require a separate product, advertising, or marketing credit.

## Contact

Maintainer: Mohamed Ayman Elnashar  
Discord: `theinevitableinvincible`

Open to hiring, questions, suggestions, and collaboration. Please use GitHub Issues for bug reports and feature requests, and follow [SECURITY.md](SECURITY.md) for security reports.

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

Mod metadata readers recognize Forge/NeoForge TOML, Fabric/Quilt JSON, and legacy Forge `mcmod.info`. Localization includes modern JSON and older `.lang` files across resource namespaces. Standard data-pack recipes and advancements are read from singular and plural directory names and namespaces that differ from the loader mod ID. Structured JSON in data-pack and custom asset data folders is also flattened into searchable evidence. Jenny indexes a compact manifest of texture and model resource names and their references, but does not embed image pixels or infer what a texture looks like. Extraction does not validate that a pack's mods support the same Minecraft version or loader, and it cannot decode every mod's private recipe/config format. A mod appearing in `/mods` confirms metadata was found, not that all of its custom content was extracted. One bot installation indexes one pack corpus shared across its Discord servers.

Use `/recipe <item>` for extracted standard recipe cards. Recipe grids show a compact symbol pattern with a legend. Choose separate recipe messages when a search finds multiple recipes. Custom machines and recipe systems need dedicated parsers; a missing standard recipe match means the current corpus has no matching record, not proof that an item has no recipe.

See [tools/rag/README.md](tools/rag/README.md) for the exact expected folder layout, supported extensions, extraction boundaries, build command, and troubleshooting. The startup warning `all_documents.json` not found means the processing stage did not produce the corpus in the bot's `data/processed` folder. A `chroma.sqlite3` file alone does not prove that it contains vectors; check the builder's final document count and generated `data/embeddings/rag_manifest.json`.

Jenny cites retrieved evidence sources in modpack answers. `RAG_MAX_DISTANCE` controls which vector matches count as evidence: lower values are stricter, but may miss relevant material. Tune it with representative questions. If no local evidence qualifies, the answer should say what is unknown; web results are supplementary context only.

At runtime, vector retrieval is limited to Minecraft/mod/config questions and short follow-ups to recent related turns. The heavy RAG and embedding modules load only when needed, reducing normal startup time and idle memory use. The first RAG query may take longer while the local embedding model initializes. Set `RAG_PREWARM=true` in `.env` to trade startup-time resource use for a warmer first query. Shared server chat logs are added for explicit history questions and a small nearby-message slice is added for short, context-dependent follow-ups.

The one-time local index build embeds every extracted document on the machine. To keep that work from saturating a laptop, the defaults cap PyTorch at 2 CPU threads and use 64-document Chroma batches with 16-text embedding batches. Set `RAG_CPU_THREADS`, `RAG_INDEX_BATCH_SIZE`, and `RAG_EMBED_BATCH_SIZE` in `.env` to tune peak resource use; the thread and batch settings affect build speed and memory, not embedding quality. Rebuilding is only needed after changing the mod/config corpus or extraction code.

## What the bot can do

- Reply in servers only when Jenny's name or bot account is mentioned; replies to other users and ordinary main-channel messages do not trigger her. Every DM is treated as a direct conversation.
- Keep bounded recent context plus automatically summarized long-term channel, voice, and user memory. Active streams are checked every 15 minutes; a new stream gets an initial summary, then summaries run after 25 new records or six hours of activity.
- Search recent stored server chat and summarize channels.
- Answer server, member, profile-history, last-message, and token-usage questions; `/help` privately lists commands available in that context. `/serverinfo` and `/user` have 24-hour, 7-day, and 30-day buttons that show only the selected activity window.
- Browse large lists and histories through button-paged embeds. `/recipe` shows extracted recipe cards, and `/trivia` supports timed solo rounds or first-correct multiplayer with difficulty, question count, replay, and a server leaderboard.
- Show member avatars and roles. Assign and remove roles only when the requester is an administrator, outranks the role, and Jenny also has Manage Roles and outranks it.
- Include the current speaker's and Jenny's actual guild roles in server text and voice context, so role-aware answers use live server information.
- Show a Minecraft Singleplayer 26.3 Playing activity with elapsed time in the title, refreshed every 15 seconds and reset when the Python bot restarts. Bot presence cannot use a custom large image; a custom activity image is not included in this repository release.
- Analyze attached images, replied-to images, Discord embed previews, and direct GIF/image links from trusted Discord, Tenor, and Giphy hosts. Animated GIFs are sampled at up to three frames before their visual evidence is passed to the chat model. Recent image context can be reused during text and voice follow-ups.
- Transcribe voice-message attachments posted in Jenny's configured channel.
- Send incoming server messages, Jenny's generated replies, and profile events to the selected logs channel. Direct messages stay private in the local database.
- Show per-user AI token counts, chat message counts, total voice-channel connected time, voice inputs, captured speech time, and speech-to-text/text-to-speech processing time for selectable periods. Server-wide usage is administrator-only; `/myusage` shows only the caller's totals and is available in DMs.
- Voice-channel connection time begins when this tracker is installed and running; Discord does not provide historical voice-presence totals, and downtime across restarts is excluded.
- Browse the latest 100 voice inputs and stage timings with `/voicetimes`; full turn records are written to the ignored `logs/voice-turns.jsonl` file.
- Keep separate Python and Node terminal logs in `logs/python-runtime.log` and `logs/voice-runtime.log`. Logs rotate or are pruned automatically and remain local.
- Let users privately view `/mymemory` or clear conversation memory with `/forgetmydata`. Detailed chat, voice, profile-history, token, and speech records are pruned after the configured retention period (`DATA_RETENTION_DAYS`, default 90).
- Search the indexed mod/config corpus, with exact item/config metadata matches alongside semantic retrieval. Roster questions such as "what mods is Jenny playing?" return the complete local mod manifest. When local evidence is missing, optional web lookup can add clearly labeled background, not proof of installed-pack behavior.

## How conversation summaries work

Jenny stores a short recent conversation window separately from long-term summaries. The short window holds up to 24 message entries, about 12 user and assistant exchanges, for each user and conversation. A server channel, voice room, and DM do not share the same raw chat history.

When a message is logged, Jenny increments that stream's activity counter. A new stream gets its first summary after activity is detected. After that, a background task picks it up at 25 new records or after six hours of accumulated activity. The task checks every 15 minutes and summarizes at most 30 unprocessed records per run. If a provider returns invalid JSON, Jenny retries once with at most 10 records; repeated failures use increasing delays up to six hours instead of retrying on every scheduler pass. Gemini is tried first for these background jobs, followed by OpenRouter, Groq, and Groq backup. Server text memory excludes Jenny's own replies; DM text memory only receives incoming human messages. Jenny saves user memories once in a canonical Discord-ID scope and advances the stream's processed-record cursor.

Server text summaries are scoped to their text channel; voice summaries are scoped to their server. Personal long-term memory uses the user's stable Discord ID and is shared across that person's DMs, server text, and server voice. Legacy scope-specific memories remain readable during migration, but new writes use one canonical row to avoid duplicates. `/mymemory` shows the current shared memory. `/forgetmydata` clears the caller's Jenny conversation histories and saved memories across all scopes. System maintenance notes are excluded from activity counts and summary input. If more than 30 records are waiting, the remaining count is retained so later runs continue processing the backlog.

The default 90-day cleanup removes old detailed message, voice, usage, profile-history, image-context, and short conversation-history records. Rolling summaries are retained until the user clears their memory with `/forgetmydata` or an administrator clears their history. This lets Jenny remember useful context without keeping every raw conversation indefinitely.

See [CHANGELOG.md](CHANGELOG.md) for Jenny's current release notes. `/health` checks the Discord connection, Python API, optional voice service, local RAG corpus, log channel permissions, and Message Content Intent configuration. `/mods`, `/recipe`, and `/trivia` use locally extracted data; pack trivia does not ask an AI model to invent quiz facts. Trivia rounds are public messages with a live countdown. Solo play reserves answers for the host and advances on request. Party play advances automatically, with three points for the final question. Jenny can route chat requests to trivia using the requested mode, difficulty, and question count. Multiplayer scores stay within the server. Configured logs channels receive direct Jenny conversations, slash commands, button interactions, profile changes, and errors, not ordinary unrelated chat messages.

Jenny's Minecraft Playing status is refreshed every 15 seconds and shows `Minecraft` with a second line for `Singleplayer · Version 26.3 · HH:MM:SS`. Discord's bot gateway presence supports basic activity status but does not expose the desktop game's custom artwork card controls. The user-supplied grass-block image is maintainer-local and is not included in this public repository release. The elapsed timer resets when the Python bot restarts.

If chat appears silent, check the Python runtime log for `[EVENT] on_message received`. If that trace never appears, verify Message Content Intent is enabled both in the code and in the Discord Developer Portal, then confirm the bot has View Channel and Read Message History permissions. `/health` also reports the code-side intent and configured log-channel send/embed permissions.

Discord does not expose members' private profile bios through the bot API.

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
