# Jenny changelog

## 0.89

### Fixed

- Corrected the repository display name to `Jenny`; the maintainer's GitHub username remains `theinevitableinvincible`.

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
