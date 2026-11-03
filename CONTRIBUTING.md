# Contributing to Jenny

Thanks for helping improve Jenny. Contributions should keep the bot usable across multiple Discord servers and should not require the maintainer's private modpack, local database, or API accounts.

## Before opening a change

- Search existing commands and helpers before adding another implementation of the same behavior.
- Keep guild settings and channel memory scoped by guild. Personal long-term memory is keyed by stable Discord user ID and shared across that user's DMs, server text, and voice; raw short-term histories remain scoped to their conversation.
- Keep credentials, `.env` files, local databases, logs, generated indexes, mod JARs, and private config files out of commits.
- Update `README.md` when setup, supported providers, data formats, permissions, or user-facing behavior changes. Update `CHANGELOG.md` for user-visible changes.
- Explain what you changed, how you checked it, and any setup or migration steps.

## Local checks

Run the checks from the repository root:

```sh
python -m compileall -q Jenny jenny_api_server.py jenny_rag_integration.py tools
node --check voice_service/index.js
```

The current repository has syntax checks, not a comprehensive automated integration test suite. Do not describe a syntax check as proof that Discord permissions, provider credentials, voice playback, or RAG retrieval work end to end.

## Pull requests

Keep changes focused, describe behavior visible to users, and include relevant logs or screenshots only after removing tokens, user-identifying content, and private server data. Do not submit `.env`, `memory.db`, generated `data/`, `logs/`, or Minecraft pack files.
