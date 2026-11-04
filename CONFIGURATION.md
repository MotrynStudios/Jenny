# Jenny configuration reference

Copy [`.env.example`](.env.example) to `.env` in the root of the repository. Leave optional API keys empty. Use one setting per line and save as plain text. Restart Python and Node after changing values. Existing environment variables in the process take precedence over the file. Older voice installs may still load `voice_service/.env` as a fallback when no Deepgram key is available from the shared configuration. New installs only need the root file.

For account setup and current quotas, see [API keys and free usage](README.md#api-keys-and-free-usage).

## Credentials

| Setting | Required for | What to enter |
| --- | --- | --- |
| `DISCORD_TOKEN` | Running Jenny | The token from the Bot page in the Discord Developer Portal. Both runtimes use it. |
| `GROQ_API_KEY` | Groq chat, vision or Whisper | A GroqCloud API key. Can serve all three tasks. |
| `GROQ_API_KEY_BACKUP` | Optional fallback | Another authorized key. Uses the same configured model IDs as the primary. |
| `OPENROUTER_API_KEY` | Optional OpenRouter text route | An OpenRouter API key. Leave blank if using Groq only. |
| `GEMINI_API_KEY` | Optional Gemini route | A Google AI Studio API key. Enable it only for an eligible use case. |
| `TAVILY_API_KEY` | Web search | A Tavily API key. Local pack search works without it. |
| `TAVILY_API_KEY_BACKUP` | Optional web search fallback | A second authorized Tavily key. |
| `DEEPGRAM_API_KEY` | Spoken replies | A Deepgram key with access to the selected Flux voice. |
| `GITHUB_REPORT_TOKEN` | Optional `/report` posting | A fine-grained GitHub token limited to the target repository with **Issues: write**. Blank disables posting. |
| `GITHUB_REPORT_REPO` | Optional `/report` destination | Repository in `owner/name` form. Defaults to `MotrynStudios/Jenny`. Use your own issue tracker for a fork. |

To enable reports, create a [fine-grained token](https://github.com/settings/personal-access-tokens/new) for the issue tracker only. Ensure Issues are enabled. The form submits its title and details to GitHub under the token account and returns the issue link privately. It does not attach Discord messages or account IDs. Only enter information suitable for a public issue. See [GitHub's required permissions](https://docs.github.com/en/rest/issues/issues#create-an-issue).

## Models and output limits

| Setting | Default | What it changes |
| --- | --- | --- |
| `OPENROUTER_MODEL` | `openai/gpt-oss-120b:free` | Model ID used for OpenRouter text calls. The unsuffixed ID is a paid route. |
| `GROQ_TEXT_MODEL` | `openai/gpt-oss-120b` | Text model used on both Groq keys. |
| `GROQ_VISION_MODEL` | `qwen/qwen3.8-27b` | Model used for image descriptions. See [Groq vision](https://console.groq.com/docs/vision). |
| `GROQ_STT_MODEL` | `whisper-large-v3` | Speech transcription model for voice notes and Node voice capture. |
| `GROQ_STT_LANGUAGE` | Empty | Optional language hint for Node voice transcription, for example `en`. Empty lets Whisper detect it. |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Gemini model ID for its configured text and image routes. |
| `DEEPGRAM_TTS_MODEL` | `flux-haley-en` | Spoken voice ID sent to Deepgram's Flux endpoint. Choose a model from the [Flux catalog](https://developers.deepgram.com/docs/flux-tts/voices). |
| `AI_MAX_TOKENS` | `1500` | Upper limit on normal generated replies. Maintenance and trivia have separate output budgets. |
| `VISION_MAX_TOKENS` | `300` | Maximum tokens for an image description. |

By default chat uses OpenRouter, Groq, Groq backup, then Gemini, skipping providers with missing keys. Image analysis uses Groq, Groq backup, then Gemini. `/setmodel` changes the preferred text or image route in one server, and `/models` shows the configured choices. Memory maintenance and live trivia prefer Gemini when configured. Extraction trivia starts at the last configured provider in the default text route and works back through the chain if needed. A quota or provider error can move the request to another provider. Configuring fallback keys does not guarantee capacity.

## Local services and RAG

| Setting | Default | What it changes |
| --- | --- | --- |
| `PYTHON_API_URL` | `http://127.0.0.1:8000` | Address Node calls for Python voice integration. The stock Python launcher binds its local API to this address. Leave it as-is for a normal install. |
| `RAG_MAX_DISTANCE` | `1.4` | Threshold for vector result distance. Lower values reject more distant results. It does not change recipe autocomplete or literal pack search. |
| `RAG_CPU_THREADS` | `2` | Number of PyTorch CPU threads requested for the local embedding model. |
| `RAG_INDEX_BATCH_SIZE` | `64` | Number of documents per Chroma indexing batch, capped at 256. |
| `RAG_EMBED_BATCH_SIZE` | `16` | Number of texts encoded together, capped at 128. |
| `RAG_PREWARM` | `false` | Set to `true` to load RAG in the background at startup. Otherwise the first RAG request loads it. |
| `DATA_RETENTION_DAYS` | `90` | Retention window for supported local database records during cleanup. It does not set provider retention or terminal log rotation. |

Use positive integers for token caps, threads, batches and retention. Use a number such as `1.4` for the distance threshold. Install FFmpeg and put it on `PATH` for voice playback. The voice wake name is handled by the runtime's Jenny name detection.

## Discord settings

Channel IDs, chat reply mode, enabled state and model preferences are stored per server. Set them with `/setmainchannel`, `/setlogschannel`, `/replymode`, `/togglejenny` and `/setmodel`. They do not belong in `.env`. Use a separate bot installation for a separate modpack index.

## Storage and privacy

- `Jenny/memory.db` stores chat, voice transcripts, summaries, configuration, profiles, usage and cached command results.
- `data/trivia_cache.sqlite3` stores generated trivia and solve times. `data/raw_data/`, `data/processed/`, and `data/embeddings/` store extraction and retrieval artifacts. The embedding model comes from [Hugging Face](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). The vector database is [Chroma](https://docs.trychroma.com/).
- `logs/python-runtime.log` and `logs/voice-runtime.log` capture local runtime output and rotate. `logs/voice-turns.jsonl` records individual voice timings and may include transcripts. Extraction and indexing have their own logs.
- When Jenny calls a provider, the request can contain relevant messages, memories, retrieved pack facts, an image, audio or a search query depending on the feature. Provider data handling is separate from local retention.
- `/mymemory` displays the caller's saved personal summary privately. `/forgetmydata` clears the caller's conversation memory and saved summary. Usage and audit records have their own retention and are not all erased by this command.
- The local API is for two trusted processes on the same machine. Keep it on loopback. Do not include tokens, databases, logs, private prompts, or extracted pack data in Git or in public bug reports.
