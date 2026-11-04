# Jenny changelog

## 0.94f

- Fixed cold exact-ID recipe lookups by reading extracted records before loading vector search. The encoder uses local cached weights when available, and `/health` distinguishes a cold index from a loaded one.
- Focused recipe Web searches on the output item and added an opt-in `/report` form for public GitHub issues.
- Documented tested Minecraft 1.21.1 NeoForge coverage, the roadmap, and the MotrynStudios repository.

- Rewrote setup, provider, configuration, and support docs. Added a FAQ and a file-by-file guide.
- Made the free GPT-OSS route the OpenRouter default. Removed unused settings and old voice command handlers. Fixed duplicate voice text copies and overlapping speech polls.
- Replaced queued join notices with one confirmed voice result. Failed connection attempts and reconnects now stop after a deadline.
- Cached recent command activity and visible embeds in the channel log for follow-ups, and expanded recent conversation budgets by 1,000 tokens.
- Made Web search open an optional query field and removed duplicate text acknowledgements after command embeds.
- Fixed stale voice joins after restarts with a fresh intent check, expiring operations, and live connection snapshots.
- Added a one-second ASCII trivia clock with a progress bar and private wrong-answer feedback.
- Added recipe output and ingredient autocomplete, mod autocomplete, `/modcontents`, page jump/search, and external web lookup buttons. Added TaCZ workbench cards and server-wide `/roles`.
- Redesigned trivia with a separate ASCII clock, configurable round time, distinct question categories, and a prebuilt cache targeting 100 questions per category. Fixed stale buttons, duplicate solo advances, and repeated guesses in party rounds.
- Routed model-selected commands through the slash handlers in chat, DMs, and voice. Blocked control text at the speech boundary and removed keyword shortcuts.
- Fixed direct replies to embed results and scoped follow-up context to the correct channel. Skipped rate-limited model accounts until they can be retried.
- Fixed removed mod data lingering in the next RAG build and included source links in web search evidence.
- Fixed repeated voice joins by removing the command extractor that turned any mention of `CMD:joinvc` into an action, tightening Jenny's join intent rules, and making the voice API ignore joins that are already connected or queued. Trivia now falls through Gemini, OpenRouter, Groq, and Groq backup, validating each question against local pack facts before caching it.
- Fixed `/replymode` to control chat-triggered replies only; voice turns and voice notes default to speech and post answers in chat only when requested. Routed natural-language mode changes through Jenny's AI command flow, removed presence refresh log spam, tightened pack-data answers, and added retrieval timing logs.
- Added `/models` and per-server `/setmodel` controls for chat and image routes; model status and choices now reflect configured provider keys. Tightened Jenny's default replies so she keeps casual text and voice answers brief.
- Fixed role requests with trailing AI text, exact name resolution, and direct mentions; recipe files stored as one object now appear in complete `/recipe` and `/searchpack` results.
- Made slash command results public, added seven-day summaries, kept only durable details long term, and removed a duplicate cleanup helper.
- Made command failures public too; hid unused `/myusage` page controls, cached Gemini trivia separately, and displayed average solve times.

## 0.93

- Fixed trivia answer leaks and added public rounds with a live countdown and distinct solo and party rules.
- Routed chat trivia and role requests through the model. Fixed DM token usage and custom mod workbench recipe retrieval.

## 0.92

### Improved

- Capped local RAG embedding threads and reduced indexing batch sizes to keep rebuilds more responsive on laptops without changing retrieval quality.

## 0.91

### Fixed

- Fixed memory attribution and duplicate scoped records; Jenny's replies, persona, and temporary command requests no longer become user memories.
- Fixed trivia crashes on older list-shaped manifests, item data, and recipe result formats.

### Improved

- Unified activity and usage ranges as Daily, Weekly, and Monthly; Jenny now uses nearby channel context for short follow-ups and sharper, more varied banter.
- Deferred RAG imports and embedding startup by default; Gemini now leads background memory maintenance, with existing provider fallbacks retained.
- Expanded mod data parsing across resource namespaces and legacy Forge localization and metadata.

### Added

- Added searchable structured custom JSON and a compact texture/model asset manifest for mod resources.
- Added name-based role requests with exact matching, ambiguity prompts, hierarchy checks, and server interaction audit logs.
- Added human-readable speaker names to stored history while retaining API-required `user` and `assistant` roles.

### Removed

- Removed ordinary unrelated chat copies from configured logs channels; direct Jenny conversations, commands, profile changes, and errors are still logged.

## 0.90

### Fixed

- Made “more” continue the saved solo trivia flow by opening its next question; multiplayer rounds remain open for the group to answer.

## 0.89

### Added and improved

- Added paged embeds with Back, page, and Next controls for large command results, including server usage member lists.
- Saved recent command results and active trivia state in SQLite so follow-up messages can refer to the last result or continue a solo quiz.
- Added `/recipe` with readable recipe cards, shaped-grid layouts, paging, and optional separate recipe messages.
- Reworked trivia into timed solo questions and multiplayer rounds with 1/2/3 points by difficulty, first-correct scoring, play-again controls, and a server leaderboard.
- Added clue levels grounded in extracted metadata, item/block names, and recipe outputs.
- Added TaCZ custom gunpack JSONC extraction and indexed gun, ammo, and attachment stats; custom models and textures remain outside the text index.
- Added Fabric and Quilt mod metadata parsing alongside Forge and NeoForge metadata.
- Documented RAG format support and its per-installation, per-modpack limits.

### Fixed

- Fixed malformed indentation in the server message handler that prevented the handler from loading.
- Replaced the old single-user trivia dropdown with timed rounds, round progression, and multiplayer scoring.
- Kept incorrect guessers in the participant record for the leaderboard.

## 0.88

### Added and improved

- Added the MIT license under Mohamed Ayman Elnashar, with standard commercial-use and notice-retention terms.
- Added public-project contact details and clarified contribution, support, and security-reporting routes.
- Prepared the repository identity and setup documentation for a multi-user public release.

## 0.87

### Added and improved

- Prepared the supplied Minecraft grass-block icon locally for a future client-side Rich Presence integration; the image asset is not included in this repository release.
- Added vision input from Discord image embeds and direct GIF/image URLs on trusted Discord, Tenor, and Giphy hosts, in server messages, replies, and DMs.
- Added a complete-manifest roster response for questions like "what mods is Jenny playing?" and made RAG roster summaries use the same 79-mod manifest as `/mods`.
- Added exact local metadata matches alongside over-fetched semantic candidates to improve item, recipe, and config retrieval.
- Filtered vector results to the explicitly named mod when a question scopes itself to one, reducing cross-mod noise from large Create-family indexes.
- Prevented whitespace-only config chunks from being generated or returned as retrieval evidence.
- Changed server replies to require Jenny's actual name or a direct bot mention; text messages no longer use fuzzy voice wake-word guesses such as "China".
- Made `/help` describe name-triggered replies correctly and include `/myusage` among the commands available in DMs.
- Added separately selectable 24-hour, 7-day, and 30-day activity panels to `/serverinfo` and `/user`, including voice-channel connected time in addition to speech/STT/TTS metrics.
- Counted voice-channel presence from the tracker forward and excluded bot downtime after restarts, instead of guessing historical connection time.
- Refined Jenny's chat guidance toward short, natural replies with occasional mood variation and fewer service-desk follow-ups.

### Fixed

- Fixed the mismatch where the help embed said main-channel messages always trigger replies even though server responses are now mention-only.
- Fixed pack-list questions going through top-k semantic search and returning an incomplete or inconsistent subset.
- Expanded image discovery beyond attachments so embedded Discord previews and direct GIF links can reach the vision model.

## 0.86

### Added and improved

- Rebuilt the Minecraft activity as a normal Playing status with the name `Minecraft`, a second line for singleplayer/version/session time, and 15-second refreshes. Discord bot accounts cannot set custom activity artwork, timestamps, or buttons through the bot gateway API.
- Registered the missing `on_message` event. Chat replies, incoming message logs, and message-triggered tools can now run.
- Added a receive trace before message-handler early returns and a friendly error reply when message handling fails.
- Added `/health` for Discord/API/voice/RAG/log-channel status and a Message Content Intent reminder.
- Added `/mods` browsing and interactive `/trivia` grounded in locally extracted mod descriptions; Jenny can also list mods or start trivia when asked in chat.
- Changed `/changelog` to show one release per embed with exactly Back, page number, and Next buttons. The page number opens a jump form, and historical entries remain available.
- `/setlogschannel` now verifies that Jenny can post an embed before replacing the saved channel. Slash-command and message-handler failures are also sent to that channel when possible.
- Profile audit logs now include global username changes reported by member updates, and failed log delivery is printed to runtime logs.

### Fixed

- Corrected the principal cause of no chat responses and no incoming chat logs: `on_message` had no `@bot.event` registration.
- Expanded the API health response to report bot initialization, indexed corpus size, RAG readiness, and voice heartbeat age.

## 0.85

### Fixed

- Delayed the initial game activity update until Discord's gateway settles after login, reducing the risk of reconnects during startup.

## 0.84

### Added and improved

- Added Jenny Belle's supplied character background and clear, natural likes and dislikes to the shared chat and voice persona prompt.
- Added the current speaker's and Jenny's live server roles to server text and voice conversation prompts, with other members' roles still retrieved only when relevant.
- Added a Minecraft Singleplayer 26.3 Playing activity with an elapsed session timer in its title. The timer refreshes once a minute and resets when the bot process restarts.
- Updated the README and runtime changelog to match the current profile, role context, and activity behavior.

## 0.83

### Fixed and improved

- Fixed mod metadata extraction for TOML dependency array tables and author arrays, so valid mods such as YetAnotherConfigLib no longer get skipped.
- Normalized nested mod language metadata before ChromaDB indexing, preventing a malformed metadata value from aborting an entire vector batch.
- Updated project documentation to explain runtime module placement, the full RAG build flow, cross-context personal memory, and empty-index troubleshooting.

## 0.82

### Added and improved

- Linked a person's long-term memory across DMs, server text, and server voice using their stable Discord user ID.
- Kept old scope-specific memories readable and merged them into shared memory as summaries run.
- Updated `/mymemory` to show shared and current-scope memory. `/forgetmydata` now clears that user's Jenny conversation histories and saved memories across all scopes so shared memories can be meaningfully erased.

## 0.81

### Fixed and improved

- Prevented automatic summaries from repeatedly spending a full request on the same malformed, oversized batch. Summaries now use smaller batches, retry a smaller portion once, and back off after repeated failures.
- Limited memory updates to users present in the summarized stream and fixed DM summaries that were attributed to `unknown`.
- Avoided adding stored profile history to ordinary chat prompts unless the user asks about profile details.
- Removed repeated voice prompt instructions and an unused prompt argument.
- Kept earlier changelog entries when the bot starts.

## 0.8

Jenny's current public feature baseline. This list describes intended available behavior; individual services still need their credentials, Discord permissions, data, and configuration.

### What Jenny can do

- Chat in the configured main channel, reply to mentions and replies elsewhere, and answer direct messages.
- Join voice channels, transcribe speech, and respond by voice, text, or both.
- Transcribe Discord voice-message attachments posted in her configured channel.
- Understand attached images and sampled GIF frames, respond to the user's question, and reuse recent image context across chat and voice.
- Answer Minecraft mod, modpack, config, and recipe questions from indexed local data, and search the web when local data is incomplete.
- State when evidence is missing rather than inventing pack-specific facts.
- Keep scoped short-term conversation history, user-controlled memory, and automatic long-term user, server, channel, and voice summaries.
- Use recent same-user text, voice, replies, and images to resolve follow-up questions.
- Run supported commands from natural language and slash commands.
- Show server and member information, avatars, roles, account creation dates, join dates, and 24-hour, weekly, and monthly activity.
- Assign or remove roles when the requester is an administrator, both role hierarchies allow it, and Jenny has Manage Roles.
- Track profile changes and show profile history, recent changes, and last saved message time.
- Log incoming server messages, Jenny's generated replies, and profile events to the configured server logs channel.
- Search saved messages and summarize recent channel conversations.
- Show token counts and speech-to-text and text-to-speech processing time by day, week, or month, plus a paginated report of recent voice inputs and stage timings.
- Show `/help` privately with commands visible to the caller; let members privately view or clear their own Jenny memory.
- Keep separate Python, Node, and voice-turn logs, with log rotation and configurable retention for detailed records.
- Use configured primary and backup provider accounts with fallback behavior.
- Respond warmly and playfully, including original song-like lines. She can discuss lyrics a user supplies, but does not fetch or continue copyrighted lyrics.

### Release notes

- Replaced prior changelog entries with this single 0.8 baseline. This reset affects changelog rows only; conversation and usage records are preserved.
- Added natural language role changes, channel message logging, voice-note transcription, cross-modal image context, and period-based token and speech usage reports.
- Added `/user`, `/voicetimes`, private `/help`, `/mymemory`, and `/forgetmydata`; automatic conversation summaries and 90-day default database cleanup.
- Removed stale guild-scoped slash command registrations left by old test syncs; global commands are now the single source of command definitions.
- Expanded RAG extraction to nested mod JARs, SNBT, and INI config files.
- Discord does not expose a member's private profile bio to the bot API.
