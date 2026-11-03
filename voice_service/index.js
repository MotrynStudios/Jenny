#!/usr/bin/env node
/**
 * Optional voice process for the same Jenny bot identity used by Python
 * Actual Discord voice capture + Groq STT/TTS
 * Voice-in/Voice-out operation with reply mode support
 */

const { Client, GatewayIntentBits, Partials } = require('discord.js');
const { joinVoiceChannel, createAudioPlayer, createAudioResource, AudioPlayerStatus, EndBehaviorType, VoiceConnectionStatus, entersState } = require('@discordjs/voice');
const prism = require('prism-media');
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');
const path = require('path');
const runtimeLogDir = path.resolve(__dirname, '..', 'logs');
fs.mkdirSync(runtimeLogDir, { recursive: true });
const runtimeLogPath = path.join(runtimeLogDir, 'voice-runtime.log');
let runtimeLogBytes = fs.existsSync(runtimeLogPath) ? fs.statSync(runtimeLogPath).size : 0;
let runtimeLog = fs.createWriteStream(runtimeLogPath, { flags: 'a' });
let rotatingVoiceLog = false;
const pendingVoiceLogWrites = [];
function rotateVoiceRuntimeLog() {
    if (rotatingVoiceLog) return;
    rotatingVoiceLog = true;
    runtimeLog.end(() => {
        try {
            for (let index = 3; index >= 1; index -= 1) {
                const older = `${runtimeLogPath}.${index}`;
                const newer = `${runtimeLogPath}.${index + 1}`;
                if (fs.existsSync(older)) {
                    if (index === 3) fs.rmSync(older, { force: true });
                    else fs.renameSync(older, newer);
                }
            }
            if (fs.existsSync(runtimeLogPath)) fs.renameSync(runtimeLogPath, `${runtimeLogPath}.1`);
            runtimeLogBytes = 0;
            runtimeLog = fs.createWriteStream(runtimeLogPath, { flags: 'a' });
        } catch (error) {
            process.__jennyOriginalStderr?.(`[Voice] Could not rotate runtime log: ${error.message}\n`);
            runtimeLog = fs.createWriteStream(runtimeLogPath, { flags: 'a' });
        } finally {
            rotatingVoiceLog = false;
            const queuedWrites = pendingVoiceLogWrites.splice(0);
            for (const queuedWrite of queuedWrites) writeVoiceRuntimeLog(queuedWrite);
        }
    });
}
function writeVoiceRuntimeLog(buffer) {
    if (rotatingVoiceLog) {
        pendingVoiceLogWrites.push(buffer);
        return;
    }
    if (runtimeLogBytes + buffer.length > 8_000_000) {
        pendingVoiceLogWrites.push(buffer);
        rotateVoiceRuntimeLog();
        return;
    }
    runtimeLog.write(buffer);
    runtimeLogBytes += buffer.length;
}
const redactLogSecrets = value => String(value)
    .replace(/(Bearer\s+|Token\s+)[^\s"'`]+/gi, '$1[REDACTED]')
    .replace(/(\btoken\s*:\s*['"])[^'"]+(['"])/gi, '$1[REDACTED]$2');
for (const stream of [process.stdout, process.stderr]) {
    const originalWrite = stream.write.bind(stream);
    if (stream === process.stderr) process.__jennyOriginalStderr = originalWrite;
    stream.write = (chunk, ...args) => {
        const safeText = redactLogSecrets(Buffer.isBuffer(chunk) ? chunk.toString('utf8') : chunk);
        const safeBuffer = Buffer.from(safeText, 'utf8');
        writeVoiceRuntimeLog(safeBuffer);
        return originalWrite(chunk, ...args);
    };
}
require('dotenv').config({ path: path.resolve(__dirname, '..', '.env') });
// Backward compatibility for existing local installs: use the old voice-only
// file only when the shared root environment does not provide Deepgram.
if (!process.env.DEEPGRAM_API_KEY) {
    require('dotenv').config({ path: path.resolve(__dirname, '.env') });
}

/**
 * Get formatted timestamp for logging
 */
function getTimestamp() {
    const now = new Date();
    return now.toISOString().replace('T', ' ').substring(0, 19);
}

/**
 * Simple timing tracker
 */
class TimingTracker {
    constructor(operationName) {
        this.operationName = operationName;
        this.startTime = Date.now();
        this.checkpoints = {};
    }

    checkpoint(name) {
        const elapsed = Date.now() - this.startTime;
        this.checkpoints[name] = elapsed;
        console.log(`[${getTimestamp()}] [TIMING] ${this.operationName} - ${name}: ${elapsed}ms`);
    }

    end() {
        const total = Date.now() - this.startTime;
        console.log(`[${getTimestamp()}] [TIMING] ${this.operationName} - TOTAL: ${total}ms`);
        return total;
    }
}

// Enable Discord.js Voice debug logging (commented out to reduce console spam)
// process.env.DEBUG = 'discord.js:voice';

// discord.js voice uses FFmpeg from PATH for audio formats that need decoding.
// Avoid machine-specific paths; users can set FFMPEG_PATH in their environment.
if (process.env.FFMPEG_PATH) console.log(`[Voice] Using configured FFmpeg: ${process.env.FFMPEG_PATH}`);

// Configuration
const DISCORD_TOKEN = process.env.DISCORD_TOKEN;
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://127.0.0.1:8000';

async function reportServiceUsage(service, durationMs, guildId, userId) {
    try {
        await axios.post(`${PYTHON_API_URL}/usage/service`, {
            service,
            duration_ms: durationMs,
            guild_id: guildId || null,
            user_id: userId || null
        }, { timeout: 2000 });
    } catch (error) {
        console.warn(`[Usage] Could not record ${service} time: ${error.message}`);
    }
}
const GROQ_API_KEYS = [process.env.GROQ_API_KEY, process.env.GROQ_API_KEY_BACKUP].filter(Boolean);
const DEEPGRAM_API_KEY = process.env.DEEPGRAM_API_KEY;
const WAKE_WORD = process.env.WAKE_WORD || 'jenny';

// Groq API endpoints (STT only)
const GROQ_STT_MODEL = process.env.GROQ_STT_MODEL || 'whisper-large-v3';
const GROQ_STT_LANGUAGE = process.env.GROQ_STT_LANGUAGE || '';
const GROQ_API_URL = 'https://api.groq.com/openai/v1';

// Deepgram TTS API (Flux v2)
const DEEPGRAM_TTS_MODEL = process.env.DEEPGRAM_TTS_MODEL || 'flux-haley-en';
const DEEPGRAM_API_URL = 'https://api.deepgram.com/v2/speak';

// The Python process owns slash-command registration; this client shares its token.
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers  // Required for voice channel member info
    ],
    partials: [Partials.Channel]
});

// Voice connection tracking
const voiceConnections = new Map();
const audioPlayers = new Map();
const voiceReceivers = new Map();
const audioBuffers = new Map();
const voiceChannels = new Map(); // Store voice channel references
const textChannels = new Map(); // The server channel used for text replies

// Global reply mode for voice input
const replyModes = new Map(); // guildId -> chat, vc, or both

function getTextChannel(guildId) {
    const guild = client.guilds.cache.get(guildId);
    if (!guild) return null;
    const configured = textChannels.get(guildId);
    const configuredChannel = configured && guild.channels.cache.get(configured);
    if (configuredChannel?.isTextBased()) return configuredChannel;
    return guild.systemChannel ||
        guild.channels.cache.find(channel => channel.isTextBased() && channel.guildId === guildId) || null;
}

async function notifyPythonVoiceStatus(guildId, inVoice, channelId = null) {
    try {
        await axios.post(`${PYTHON_API_URL}/voice/status`, { guild_id: guildId, in_voice: inVoice, channel_id: channelId }, { timeout: 2000 });
    } catch (error) {
        console.error('[Voice] Could not update observed connection status:', error.message);
    }
}

// Response generation tracking to prevent overlaps
const pendingResponses = new Map(); // guildId -> pending response
const ttsStates = new Map(); // guildId -> playback and generation state
const ttsQueues = new Map(); // guildId -> queued TTS operations
const ttsQueueProcessing = new Set(); // guilds currently draining their queue

function getTTSState(guildId) {
    if (!ttsStates.has(guildId)) {
        ttsStates.set(guildId, {
            isPlaying: false,
            isGenerating: false,
            currentChunkId: 0,
            chunks: [],
            generationId: 0
        });
    }
    return ttsStates.get(guildId);
}

function getTTSQueue(guildId) {
    if (!ttsQueues.has(guildId)) ttsQueues.set(guildId, []);
    return ttsQueues.get(guildId);
}

// Tracks which userIds currently have a live subscribe->decode pipeline attached,
// so speaking 'start' firing again (which happens more often than the stream's
// own silence timeout closes it) doesn't stack duplicate listeners on the same
// cached Opus stream.
const activePipelines = new Set();

// Debounce for end-of-speech: Discord's speaking indicator can fire 'end'
// then 'start' again within milliseconds mid-sentence (breaths, brief pauses),
// so a flush scheduled on 'end' gets cancelled here if 'start' fires again
// before the debounce window elapses, meaning it wasn't really the end of the
// utterance yet.
const pendingFlushTimeouts = new Map(); // userId -> Timeout
const FLUSH_DEBOUNCE_MS = 300;
const SILENCE_END_MS = 300;

function isVoiceMemberMuted(member) {
    return !member?.voice || member.voice.mute || member.voice.selfMute || member.voice.deaf || member.voice.selfDeaf;
}

/**
 * Handle incoming audio chunks
 */
function handleAudioChunk(guildId, userId, chunk) {
    if (!audioBuffers.has(guildId)) {
        audioBuffers.set(guildId, new Map());
    }

    const userBuffers = audioBuffers.get(guildId);
    if (!userBuffers.has(userId)) {
        userBuffers.set(userId, []);
    }

    userBuffers.get(userId).push(chunk);
    // No fixed-size flush here anymore. Slicing every ~20 chunks (~420ms) was
    // cutting full sentences into meaningless fragments before they ever
    // reached Groq, e.g. "jenny, how's the weather" got split into five
    // separate unrelated transcriptions and the wake word never landed intact
    // in any of them. We now wait for the speaking 'end' event (see
    // flushUserAudio below) and send the whole utterance in one request.
    //
    // Safety cap: if someone talks continuously for a long stretch without a
    // pause, don't let the buffer grow forever, force a flush at ~15s.
    const chunks = userBuffers.get(userId);
    if (chunks.length > 750) {
        console.log(`[Voice] Safety cap reached for user ${userId}, forcing flush (${chunks.length} chunks)`);
        flushUserAudio(guildId, userId);
    }
}

/**
 * Flush whatever audio has accumulated for a user and send it for
 * transcription as one complete utterance. Called when Discord's speaking
 * indicator reports the user stopped talking.
 */
function flushUserAudio(guildId, userId) {
    const userBuffers = audioBuffers.get(guildId);
    if (!userBuffers || !userBuffers.has(userId)) return;

    const chunks = userBuffers.get(userId);
    if (chunks.length === 0) return;

    console.log(`[Voice] Flushing audio from user ${userId} (${chunks.length} chunks)`);
    processAudio(guildId, userId, chunks);
    userBuffers.set(userId, []);
}

/**
 * Filter out noise transcriptions
 * STT often hallucinates "thank you" from minor sounds, and repeats words
 */
function filterNoiseTranscript(transcript) {
    if (!transcript) return null;

    const text = transcript.trim().toLowerCase();
    const words = text.split(/\s+/);

    console.log(`[Voice] Filtering transcript: "${transcript}" (${words.length} words)`);

    // Common misrecognitions of "Jenny" to treat as name mentions
    const mentionsJenny = /\b(?:jenny(?:\s*belle)?|jenni|jennie|jeni|chani|china|shani|shaani|jennybell)\b/i.test(text);

    // Filter 1: Specifically filter standalone "thank you" and similar (with or without punctuation) unless "jenny" is mentioned
    if ((text === 'thank you' || text === 'thanks' || text === 'thank' || 
        text === 'thank you.' || text === 'thanks.' || text === 'thank.' ||
        text === 'thank you!' || text === 'thanks!' || text === 'thank!') && !mentionsJenny) {
        console.log('[Voice] Filtered noise transcription (standalone thanks):', transcript);
        return null;
    }

    // Filter 2: Ignore transcriptions that are ONLY common STT hallucinations without "jenny" or similar
    const noisePhrases = ['thank you', 'thanks', 'thank', 'you', 'ok', 'okay', 'yeah', 'yep', 'yes', 'no', 'uh', 'um', 'ah', 'oh', 'mm', 'hm', 'hmm'];
    
    if (words.length <= 3 && noisePhrases.includes(text) && !mentionsJenny) {
        console.log('[Voice] Filtered noise transcription (noise phrase without jenny):', transcript);
        return null;
    }

    // Filter 3: Detect repeated words/phrases (e.g., "you you you", "thank you thank you")
    const wordCounts = {};
    words.forEach(word => {
        wordCounts[word] = (wordCounts[word] || 0) + 1;
    });

    // If any word appears more than 2 times in a short transcription, it's noise
    const maxRepeats = Math.max(...Object.values(wordCounts));
    if (maxRepeats > 2 && words.length < 10) {
        console.log('[Voice] Filtered noise transcription (repeated words):', transcript);
        return null;
    }

    // Filter 4: Very short single-word transcriptions without "jenny" or similar
    if (words.length === 1 && !mentionsJenny) {
        console.log('[Voice] Filtered noise transcription (single word without jenny):', transcript);
        return null;
    }

    // Log if Jenny (or similar) was detected
    if (mentionsJenny) {
        console.log('[Voice] Jenny (or similar) detected in transcript:', transcript);
    }

    console.log(`[Voice] Transcript passed noise filter: "${transcript}"`);
    return transcript;
}

/**
 * Process accumulated audio chunks
 */
async function processAudio(guildId, userId, chunks) {
    const timing = new TimingTracker('Audio Processing');
    const timingsMs = { speech_capture: Math.max(0, chunks.length * 20) };
    
    try {
        console.log(`[${getTimestamp()}] [Voice] Processing audio - combining ${chunks.length} chunks`);
        // Combine chunks into a single buffer
        let stageStartedAt = Date.now();
        const audioBuffer = Buffer.concat(chunks);
        timingsMs.audio_combine = Date.now() - stageStartedAt;
        console.log(`[${getTimestamp()}] [Voice] Combined audio buffer size: ${audioBuffer.length} bytes`);
        timing.checkpoint('Audio combination');

        // Wrap the decoded PCM in a proper WAV header for Groq
        stageStartedAt = Date.now();
        const wavBuffer = pcmToWav(audioBuffer);
        timingsMs.wav_conversion = Date.now() - stageStartedAt;
        console.log(`[${getTimestamp()}] [Voice] WAV conversion complete, size: ${wavBuffer.length} bytes`);
        timing.checkpoint('WAV conversion');

        // Transcribe using Groq
        console.log(`[${getTimestamp()}] [Voice] Sending to Groq for transcription...`);
        stageStartedAt = Date.now();
        const transcript = await transcribeAudio(wavBuffer, guildId, userId);
        timingsMs.stt = Date.now() - stageStartedAt;
        console.log(`[${getTimestamp()}] [Voice] Transcription result: "${transcript}"`);
        timing.checkpoint('STT (Groq)');
        
        if (!transcript) {
            console.log(`[${getTimestamp()}] [Voice] No transcript returned, skipping processing`);
            timing.end();
            return;
        }
        
        // Check for cancellation phrases if there's a pending response
        const pendingResponse = pendingResponses.get(guildId);
        if (pendingResponse && pendingResponse.userId === userId) {
            const lowerTranscript = transcript.toLowerCase();
            const cancellationPhrases = [
                'never mind', 'don\'t reply', 'no reply', 'cancel', 'stop', 'nevermind',
                'actually don\'t', 'actually no', 'forget it', 'ignore that'
            ];
            
            // Common misrecognitions of "Jenny" to treat as name mentions
            const jennyVariations = ['jenny', 'chani', 'china', 'shani', 'shaani', 'jennybelle', 'jenni', 'jennie', 'jeni'];
            
            // Check if any cancellation phrase is present AND Jenny's name was recognized
            const hasCancellation = cancellationPhrases.some(phrase => lowerTranscript.includes(phrase));
            const mentionsJenny = jennyVariations.some(variation => new RegExp(`\\b${variation}\\b`, 'i').test(lowerTranscript));
            
            if (hasCancellation && mentionsJenny) {
                console.log('[Voice] Cancellation detected, aborting pending response');
                await stopTTSPlayback(guildId);
                return; // Don't process this transcription either
            }
        }
        
        // Don't process if audio is currently playing or if there are pending TTS chunks to play
        const ttsState = getTTSState(guildId);
        if (ttsState.isGenerating || ttsState.isPlaying || (ttsState.chunks.length > 0 && ttsState.currentChunkId < ttsState.chunks.length)) {
            console.log('[Voice] Audio currently playing or pending TTS chunks, skipping this transcription');
            const mentionsJenny = /\b(jenny(?:\s*belle)?|chani|china|shani|shaani|jennybelle|jenni|jennie|jeni)\b/i.test(transcript);
            await stopTTSPlayback(guildId);
            if (mentionsJenny) {
                console.log('[Voice] User interrupted playback to address Jenny; processing the new request');
            } else {
                console.log('[Voice] Stopped playback because someone began speaking');
                console.log(`[Voice] TTS status: isPlaying=${ttsState.isPlaying}, pendingChunks=${ttsState.chunks.length}, currentChunk=${ttsState.currentChunkId}`);
                return;
            }
        }
        
        console.log(`[${getTimestamp()}] [Voice] Processing voice transcript: ${transcript}`);

        // Get username from Discord (use display name instead)
        const guild = client.guilds.cache.get(guildId);
        const member = guild.members.cache.get(userId);
        let displayName = member ? member.displayName : 'Unknown';

        // Clean up display name: remove numbers and truncate if too long
        displayName = displayName.replace(/\d+/g, '').trim(); // Remove numbers
        if (displayName.length > 20) {
            displayName = displayName.split(' ')[0].substring(0, 20); // Take first word, max 20 chars
        }
        console.log(`[${getTimestamp()}] [Voice] Using cleaned display name: "${displayName}" (from: ${member?.displayName})`);

        // Get current voice channel ID
        const voiceChannel = voiceChannels.get(guildId);
        const channelId = voiceChannel ? voiceChannel.id : null;

        // Check for reply mode in transcript
        // Voice mode defaults to voice-only unless user explicitly says "reply in chat"
        let replyMode = replyModes.get(guildId) || 'vc'; // Voice defaults to voice-only per guild
        const lowerTranscript = transcript.toLowerCase();

        if (lowerTranscript.includes('reply in chat only') || lowerTranscript.includes('reply in chat')) {
            replyMode = 'chat';
        } else if (lowerTranscript.includes('reply in both')) {
            replyMode = 'both';
        }
        // Voice-only is the default, no need to check for it

        console.log(`[${getTimestamp()}] [Voice] Using reply mode: ${replyMode} (voice input)`);

        // Send to Python API for processing
        timing.checkpoint('Before Python API');
        await sendToPythonAPI(userId, displayName, transcript, guildId, channelId, replyMode, true,
                              timingsMs, timingsMs.speech_capture);
        timingsMs.total_pipeline = Date.now() - timing.startTime;
        try {
            await axios.post(`${PYTHON_API_URL}/voice/turn/timing`, {
                guild_id: guildId,
                user_id: userId,
                username: displayName,
                transcript,
                timings_ms: { total_pipeline: timingsMs.total_pipeline }
            }, { timeout: 2000 });
        } catch (timingError) {
            console.warn(`[Voice] Could not save total pipeline time: ${timingError.message}`);
        }
        timing.end();
    } catch (error) {
        console.error(`[${getTimestamp()}] [Voice] Error processing audio:`, error);
        timing.end();
    }
}

/**
 * Transcribe audio using Groq Whisper
 */
async function transcribeAudio(audioBuffer, guildId = null, userId = null) {
    const timing = new TimingTracker('STT Request');
    const startedAt = Date.now();
    for (let index = 0; index < GROQ_API_KEYS.length; index += 1) {
        const formData = new FormData();
        formData.append('file', audioBuffer, { filename: 'audio.wav', contentType: 'audio/wav' });
        formData.append('model', GROQ_STT_MODEL);
        if (GROQ_STT_LANGUAGE) formData.append('language', GROQ_STT_LANGUAGE);
        formData.append('response_format', 'json');
        try {
            const response = await axios.post(`${GROQ_API_URL}/audio/transcriptions`, formData, {
                headers: {
                    'Authorization': `Bearer ${GROQ_API_KEYS[index]}`,
                    ...formData.getHeaders()
                }
            });
            timing.checkpoint(index === 0 ? 'Groq primary response' : 'Groq backup response');
            timing.end();
            void reportServiceUsage('stt', Date.now() - startedAt, guildId, userId);
            return filterNoiseTranscript(response.data.text);
        } catch (error) {
            console.error(`[${getTimestamp()}] [Voice] Groq STT key ${index + 1} failed:`, error.response?.data || error.message);
        }
    }
    timing.end();
    return null;
}

/**
 * Remove markdown and control characters without discarding the speaker's language.
 */
function sanitizeTextForTTS(text) {
    // Remove asterisks used for italics/bold in Discord
    let cleaned = text.replace(/\*/g, '');

    cleaned = cleaned.replace(/[\u0000-\u001F\u007F]/g, ' ');
    cleaned = cleaned.replace(/\s+/g, ' ').trim();

    if (cleaned !== text) {
        console.log(`[${getTimestamp()}] [Voice] Sanitized TTS text formatting`);
    }

    return cleaned;
}

/**
 * Generate speech using Deepgram Flux TTS (v2)
 */
async function generateSpeech(text, guildId = null, userId = null) {
    const timing = new TimingTracker('TTS Generation');
    const startedAt = Date.now();

    try {
        // Sanitize text to remove non-Latin characters before TTS
        const sanitizedText = sanitizeTextForTTS(text);
        if (!sanitizedText) {
            console.warn('[Voice] Refusing to synthesize empty text after formatting cleanup');
            timing.end();
            return null;
        }
        console.log(`[${getTimestamp()}] [Voice] Generating TTS for:`, sanitizedText);
        console.log(`[${getTimestamp()}] [Voice] Using Deepgram Flux model:`, DEEPGRAM_TTS_MODEL);

        const response = await axios.post(`${DEEPGRAM_API_URL}?model=${DEEPGRAM_TTS_MODEL}&speed=1.1&expressivity=0`, {
            text: sanitizedText
        }, {
            headers: {
                'Authorization': `Token ${DEEPGRAM_API_KEY}`,
                'Content-Type': 'application/json'
            },
            responseType: 'arraybuffer',
            timeout: 10000  // 10 second timeout for TTS generation
        });

        timing.checkpoint('Deepgram API response');
        const audioBuffer = Buffer.from(response.data);
        console.log(`[${getTimestamp()}] [Voice] Deepgram TTS generated, buffer size:`, audioBuffer.length, 'bytes');
        
        if (audioBuffer.length === 0) {
            console.error(`[${getTimestamp()}] [Voice] ERROR: Deepgram TTS returned empty buffer!`);
            timing.end();
            return null;
        }
        
        // Check if it's actually an error response (JSON instead of audio)
        if (audioBuffer.length < 1000) {
            const header = audioBuffer.toString('utf8', 0, Math.min(100, audioBuffer.length));
            if (header.includes('{') || header.includes('error')) {
                console.error('[Voice] ERROR: Deepgram TTS returned JSON error instead of audio:', header);
                return null;
            }
        }
        
        timing.end();
        void reportServiceUsage('tts', Date.now() - startedAt, guildId, userId);
        return audioBuffer;
    } catch (error) {
        console.error(`[${getTimestamp()}] [Voice] Deepgram TTS failed:`, error.response?.data || error.message);
        
        // Log the actual error response if available
        if (error.response?.data) {
            const errorText = Buffer.from(error.response.data).toString('utf8');
            console.error(`[${getTimestamp()}] [Voice] Deepgram error response:`, errorText);
        }
        
        timing.end();
        return null;
    }
}

/**
 * Check if bot is in a voice channel for a guild
 */
function isInVoiceChannel(guildId) {
    return voiceConnections.has(guildId);
}

/**
 * Play audio in voice channel
 */
async function playAudio(guildId, audioBuffer) {
    const state = getTTSState(guildId);
    try {
        // Check if bot is in voice channel
        if (!isInVoiceChannel(guildId)) {
            console.log(`[${getTimestamp()}] [Voice] Bot not in voice channel for guild ${guildId}, skipping audio playback`);
            return false;
        }

        const player = audioPlayers.get(guildId);
        if (!player) {
            console.error(`[${getTimestamp()}] [Voice] No audio player for guild`);
            return false;
        }

        // Write buffer to temp file for audio resource
        const tempFilePath = path.join(__dirname, `temp_audio_${Date.now()}.wav`);
        fs.writeFileSync(tempFilePath, audioBuffer);
        
        const resource = createAudioResource(tempFilePath);
        player.play(resource);

        state.isPlaying = true;
        console.log(`[${getTimestamp()}] [Voice] Audio playback started`);

        // Use once() instead of on() to prevent duplicate listeners accumulating
        player.once(AudioPlayerStatus.Idle, () => {
            state.isPlaying = false;
            console.log(`[${getTimestamp()}] [Voice] Audio playback finished`);
            // Clean up temp file
            try {
                if (fs.existsSync(tempFilePath)) {
                    fs.unlinkSync(tempFilePath);
                }
            } catch (e) {
                console.error(`[${getTimestamp()}] [Voice] Error deleting temp file:`, e);
            }
        });

        player.once('error', (error) => {
            console.error(`[${getTimestamp()}] [Voice] Audio player error:`, error);
            state.isPlaying = false;
            // Clean up temp file on error
            try {
                if (fs.existsSync(tempFilePath)) {
                    fs.unlinkSync(tempFilePath);
                }
            } catch (e) {
                console.error(`[${getTimestamp()}] [Voice] Error deleting temp file:`, e);
            }
        });
        
        return true;
    } catch (error) {
        console.error('[Voice] Error playing audio:', error);
        state.isPlaying = false;
        return false;
    }
}



/**
 * Cancel all pending TTS operations (race-safe)
 */
function cancelPendingTTS(guildId) {
    const state = getTTSState(guildId);
    console.log(`[Voice] Cancelling pending TTS operations for guild ${guildId}`);
    state.generationId += 1;
    state.chunks = [];
    state.currentChunkId = 0;
    state.isGenerating = false;
    state.isPlaying = false;
    getTTSQueue(guildId).splice(0).forEach(operation => operation.reject(new Error('Cancelled')));
    pendingResponses.delete(guildId);
    const player = audioPlayers.get(guildId);
    if (player) {
        try { player.stop(); } catch (error) {
            console.error(`[Voice] Error stopping player for guild ${guildId}:`, error);
        }
    }
}

/**
 * Add TTS operation to queue to prevent race conditions
 */
function enqueueTTSOperation(guildId, text, priority = false) {
    return new Promise((resolve, reject) => {
        const operation = {
            guildId,
            text,
            priority,
            resolve,
            reject,
            timestamp: Date.now()
        };
        
        const queue = getTTSQueue(guildId);
        if (priority) {
            queue.unshift(operation);
        } else {
            queue.push(operation);
        }
        
        processTTSQueue(guildId);
    });
}

/**
 * Process TTS queue
 */
async function processTTSQueue(guildId) {
    const queue = getTTSQueue(guildId);
    const state = getTTSState(guildId);
    if (ttsQueueProcessing.has(guildId) || queue.length === 0) {
        return;
    }
    
    ttsQueueProcessing.add(guildId);
    
    try {
        while (queue.length > 0) {
            while (state.isGenerating || state.isPlaying) {
                await new Promise(resolve => setTimeout(resolve, 50));
            }
            const operation = queue.shift();
            const generationId = state.generationId;
            
            if (pendingResponses.get(guildId)?.cancelCheck) {
                console.log('[Voice] TTS operation cancelled due to new voice activity');
                operation.reject(new Error('Cancelled'));
                continue;
            }
            
            try {
                state.isGenerating = true;
                const audioBuffer = await generateSpeech(operation.text);
                if (generationId !== state.generationId) {
                    operation.reject(new Error('Cancelled'));
                    continue;
                }
                
                if (audioBuffer) {
                    const played = await playAudio(operation.guildId, audioBuffer);
                    if (played) {
                        await new Promise(resolve => {
                            const timer = setInterval(() => {
                                if (!state.isPlaying || generationId !== state.generationId) {
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 50);
                        });
                        if (generationId !== state.generationId) throw new Error('Cancelled');
                        operation.resolve(true);
                    } else {
                        operation.reject(new Error('Playback failed'));
                    }
                } else {
                    operation.reject(new Error('TTS generation failed'));
                }
            } catch (error) {
                console.error('[Voice] TTS operation failed:', error);
                operation.reject(error);
            } finally {
                state.isGenerating = false;
            }
        }
    } finally {
        ttsQueueProcessing.delete(guildId);
    }
}

/**
 * Stop TTS playback (interruption)
 */
async function stopTTSPlayback(guildId) {
    try {
        // Cancel all pending TTS operations
        cancelPendingTTS(guildId);
        
        // Clear TTS chunks queue
        const state = getTTSState(guildId);
        state.chunks = [];
        state.currentChunkId = 0;
        console.log('[Voice] Cleared TTS chunks queue');
        
        console.log(`[Voice] Audio state reset after KILLTTS for guild ${guildId}`);
        return true;
    } catch (error) {
        console.error('[Voice] Error stopping TTS playback:', error);
        return false;
    }
}

/**
 * Split text into sentence chunks for TTS
 * Groups 2-3 sentences per chunk for better flow
 * Improved to handle songs, poetry, and artistic content better
 */
function splitIntoSentences(text) {
    // Handle empty or very short text
    if (!text || text.trim().length < 5) {
        return [text];
    }

    // Common abbreviations that shouldn't be split after
    const abbreviations = ['Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'Sr.', 'Jr.', 'St.', 'vs.', 'etc.', 'e.g.', 'i.e.', 'approx.', 'ca.', 'est.', 'sq.', 'No.', 'Ave.', 'Blvd.', 'Rd.', 'Hwy.', 'mt.', 'ft.', 'in.', 'cm.', 'mm.', 'km.', 'kg.', 'lb.', 'oz.', 'vol.', 'ch.', 'fig.', 'pt.', 'p.', 'a.m.', 'p.m.', 'A.M.', 'P.M.'];
    
    // Detect if this might be a song/poem (contains musical notes, multiple line breaks, or artistic formatting)
    const isArtisticContent = /[\*♫♪]/.test(text) || (text.match(/\n/g) || []).length >= 2;
    
    // Simple sentence splitting - split on . ! ? but avoid abbreviations
    const sentences = [];
    let currentSentence = '';
    
    for (let i = 0; i < text.length; i++) {
        const char = text[i];
        currentSentence += char;
        
        // Check for sentence-ending punctuation (only for artistic content, use ! ? more aggressively)
        if (char === '!' || char === '?' || char === '。' || char === '！' || char === '？') {
            sentences.push(currentSentence.trim());
            currentSentence = '';
        } else if (char === '.' && !isArtisticContent) {
            // Only split on periods for non-artistic content
            // Check if this is an abbreviation
            const lastFewChars = currentSentence.slice(-10).toLowerCase();
            const isAbbrev = abbreviations.some(abbr => lastFewChars.includes(abbr.toLowerCase()));
            
            // Check if it's a decimal number
            const isDecimal = /\d+\.\d*$/.test(currentSentence.trim());
            
            if (!isAbbrev && !isDecimal) {
                sentences.push(currentSentence.trim());
                currentSentence = '';
            }
        }
    }
    
    // Add any remaining text
    if (currentSentence.trim()) {
        sentences.push(currentSentence.trim());
    }
    
    // Fallback: if no sentences were found, just return the original text
    if (sentences.length === 0) {
        return [text];
    }
    
    // Group sentences into chunks
    const chunks = [];
    let currentChunk = '';
    let sentencesInChunk = 0;
    
    for (const sentence of sentences) {
        const sentenceLength = sentence.length;
        
        // For artistic content, use larger chunks to preserve flow
        const maxChunkSize = isArtisticContent ? 300 : 200;
        const longSentenceThreshold = isArtisticContent ? 150 : 100;
        
        // If sentence is very long, make it its own chunk
        if (sentenceLength > longSentenceThreshold) {
            if (currentChunk) {
                chunks.push(currentChunk.trim());
                currentChunk = '';
                sentencesInChunk = 0;
            }
            chunks.push(sentence);
            continue;
        }
        
        // If adding this sentence would make chunk too long, start new chunk
        if (currentChunk.length + sentenceLength > maxChunkSize) {
            if (currentChunk) {
                chunks.push(currentChunk.trim());
                currentChunk = '';
                sentencesInChunk = 0;
            }
        }
        
        // Add sentence to current chunk
        currentChunk += (currentChunk ? ' ' : '') + sentence;
        sentencesInChunk++;
        
        // For artistic content, group more sentences together
        const minSentencesForChunk = isArtisticContent ? 3 : 2;
        const maxSentencesForChunk = isArtisticContent ? 5 : 3;
        
        // If we have enough sentences in chunk, start a new one
        if (sentencesInChunk >= minSentencesForChunk && (sentenceLength > 30 || sentencesInChunk >= maxSentencesForChunk)) {
            chunks.push(currentChunk.trim());
            currentChunk = '';
            sentencesInChunk = 0;
        }
    }
    
    // Add any remaining chunk
    if (currentChunk.trim()) {
        chunks.push(currentChunk.trim());
    }
    
    // Filter out empty chunks
    return chunks.filter(s => s.length > 0);
}

/**
 * Clean text for TTS by removing non-Latin characters (Arabic, etc.)
 * Deepgram TTS may break with non-Latin characters
 */
/**
 * Generate sentence chunks in parallel, then play each as soon as its audio is ready.
 * Later sentences can synthesize while the first sentence is already playing.
 */
async function playTTSInChunks(guildId, text, userId = null) {
    const timing = new TimingTracker('TTS Chunks Playback');
    const state = getTTSState(guildId);
    const generationId = state.generationId;
    state.isGenerating = true;

    try {
        // Clean text to remove non-Latin characters before TTS
        const cleanedText = sanitizeTextForTTS(text);

        const chunks = splitIntoSentences(cleanedText);
        console.log(`[${getTimestamp()}] [Voice] Split into ${chunks.length} chunks`);

        // Synthesize the first sentence immediately; synthesize each following
        // sentence while the previous one is playing. This limits concurrent
        // provider calls while avoiding an all-sentences-before-playback delay.
        console.log(`[${getTimestamp()}] [Voice] Starting sentence-by-sentence TTS pipeline (${chunks.length} chunks)`);
        timing.checkpoint('Before TTS generation');

        const synthesizeChunk = async index => {
            const textChunk = chunks[index];
            console.log(`[${getTimestamp()}] [Voice] Generating TTS for chunk ${index + 1}/${chunks.length}: "${textChunk.substring(0, 50)}..."`);
            const buffer = await generateSpeech(textChunk, guildId, userId);
            return {
                id: index + 1,
                buffer
            };
        };

        state.chunks = [];
        state.currentChunkId = 0;
        let validChunkCount = 0;
        let audioPromise = chunks.length > 0 ? synthesizeChunk(0) : Promise.resolve(null);

        for (let index = 0; index < chunks.length; index += 1) {
            const chunk = await audioPromise;

            if (generationId !== state.generationId) {
                state.isGenerating = false;
                state.chunks = [];
                state.currentChunkId = 0;
                timing.end();
                return false;
            }

            if (!chunk || !chunk.buffer) {
                if (index + 1 < chunks.length) {
                    audioPromise = synthesizeChunk(index + 1);
                }
                continue;
            }

            validChunkCount += 1;
            state.chunks.push(chunk);
            state.currentChunkId = chunk.id;
            console.log(`[${getTimestamp()}] [Voice] Playing ready chunk ${chunk.id}/${chunks.length}`);

            const played = await playAudio(guildId, chunk.buffer);
            if (!played) {
                console.log(`[${getTimestamp()}] [Voice] Failed to play chunk ${chunk.id}, stopping`);
                state.isGenerating = false;
                state.chunks = [];
                state.currentChunkId = 0;
                timing.end();
                return false;
            }

            const playbackFinished = new Promise(resolve => {
                const checkInterval = setInterval(() => {
                    if (!state.isPlaying || generationId !== state.generationId) {
                        clearInterval(checkInterval);
                        console.log(`[${getTimestamp()}] [Voice] Chunk ${chunk.id} finished playing`);
                        resolve();
                    }
                }, 50);
            });
            const nextAudioPromise = index + 1 < chunks.length
                ? synthesizeChunk(index + 1)
                : null;
            await playbackFinished;

            if (generationId !== state.generationId) {
                state.isGenerating = false;
                state.chunks = [];
                state.currentChunkId = 0;
                timing.end();
                return false;
            }

            if (nextAudioPromise) {
                audioPromise = nextAudioPromise;
            }

            if (chunk.id < chunks.length) {
                console.log(`[${getTimestamp()}] [Voice] Waiting 0.4s before the next ready chunk`);
                await new Promise(resolve => setTimeout(resolve, 400));
            }
        }

        console.log(`[${getTimestamp()}] [Voice] Successfully played ${validChunkCount}/${chunks.length} chunks`);

        if (validChunkCount === 0) {
            console.log(`[${getTimestamp()}] [Voice] No valid chunks generated`);
            state.isGenerating = false;
            state.chunks = [];
            state.currentChunkId = 0;
            timing.end();
            return false;
        }

        // Clear chunks queue after playback
        state.chunks = [];
        state.currentChunkId = 0;
        state.isGenerating = false;

        timing.end();
        return true;



    } catch (error) {
        console.error(`[${getTimestamp()}] [Voice] Error in chunked TTS playback:`, error);
        // Clear chunks on error
        state.chunks = [];
        state.currentChunkId = 0;
        state.isGenerating = false;
        timing.end();
        return false;
    }
}

/**
 * Send text to Python API for processing
 */
async function sendToPythonAPI(userId, username, transcript, guildId, channelId, replyMode = 'chat', isVoiceMessage = false,
                               timingsMs = {}, speechDurationMs = 0) {
    const timing = new TimingTracker('Python API Request');
    
    try {
        console.log(`[${getTimestamp()}] [Voice] Sending to Python API: transcript="${transcript}", replyMode=${replyMode}, isVoiceMessage=${isVoiceMessage}`);
        
        const pythonRequestStartedAt = Date.now();
        const response = await axios.post(`${PYTHON_API_URL}/voice/process`, {
            user_id: userId,
            username: username,
            transcript: transcript,
            guild_id: guildId,
            channel_id: channelId,
            reply_mode: replyMode,
            is_voice_message: isVoiceMessage,
            timings_ms: timingsMs,
            speech_duration_ms: speechDurationMs
        });
        timingsMs.python_api = Date.now() - pythonRequestStartedAt;

        timing.checkpoint('Python API response');
        console.log(`[${getTimestamp()}] [Voice] API response status: ${response.data.status}`);
        console.log(`[${getTimestamp()}] [Voice] API response: ${JSON.stringify(response.data)}`);

        if (response.data.status === 'success') {
            console.log(`[Voice] Response from Python: "${response.data.response}"`);
            if (response.data.chat_message) {
                const textChannel = getTextChannel(guildId);
                if (textChannel) {
                    const text = response.data.chat_message;
                    for (let offset = 0; offset < text.length; offset += 1900) {
                        await textChannel.send(text.slice(offset, offset + 1900));
                    }
                }
            }
            
            // Check if this is a system command
            const responseText = response.data.response.trim().toUpperCase();
            if (response.data.reply_mode === 'command' || 
                ['JOIN_VC', 'LEAVE_VC', 'REPLY_MODE_VC', 'REPLY_MODE_CHAT', 'REPLY_MODE_BOTH', 'KILLTTS'].includes(responseText)) {
                console.log(`[Voice] System command received: ${responseText}`);
                
                // Execute the command
                if (responseText === 'JOIN_VC' || responseText === 'LEAVE_VC') {
                    // The Python API queues the corresponding voice operation.
                    console.log(`[Voice] ${responseText} handled through the API command queue`);
                } else if (responseText === 'REPLY_MODE_VC') {
                    replyModes.set(guildId, 'vc');
                    console.log('[Voice] Reply mode set to: Voice only');
                } else if (responseText === 'REPLY_MODE_CHAT') {
                    replyModes.set(guildId, 'chat');
                    console.log('[Voice] Reply mode set to: Chat only');
                } else if (responseText === 'REPLY_MODE_BOTH') {
                    replyModes.set(guildId, 'both');
                    console.log('[Voice] Reply mode set to: Both voice and chat');
                } else if (responseText === 'KILLTTS') {
                    // Stop any ongoing TTS playback
                    console.log('[Voice] KILLTTS command received - stopping TTS');
                    await stopTTSPlayback(guildId);
                }
                
                return; // Don't process as normal response
            }
            
            // Handle empty response (AI decided not to respond)
            if (!responseText || responseText.trim() === '') {
                console.log('[Voice] Empty response - AI decided not to respond');
                pendingResponses.delete(guildId);
                return;
            }
            
            // Track pending response for cancellation
            pendingResponses.set(guildId, {
                userId,
                transcript,
                timestamp: Date.now()
            });

            // Handle reply mode - use the reply_mode from API response
            const actualReplyMode = response.data.reply_mode || replyMode;
            console.log(`[${getTimestamp()}] [Voice] Reply mode: ${actualReplyMode}`);

            // Handle "none" reply mode - AI decided not to respond
            if (actualReplyMode === 'none') {
                console.log('[Voice] AI decided not to respond (NO_RESPONSE)');
                pendingResponses.delete(guildId);
                return;
            }

            const textReply = response.data.chat_message || response.data.response;
            let sentTextReply = false;
            let ttsWasAttempted = false;
            const ttsStartedAt = Date.now();
            if (actualReplyMode === 'vc' || actualReplyMode === 'both') {
                console.log(`[${getTimestamp()}] [Voice] Voice mode requested, checking voice connection...`);

                // Check if bot is in voice channel
                if (!isInVoiceChannel(guildId)) {
                    console.log(`[Voice] Bot not in voice channel, sending text response instead`);
                    // Send text response as fallback
                    const guildInfo = client.guilds.cache.get(guildId);
                    if (guildInfo) {
                        const textChannel = getTextChannel(guildId);
                        if (textChannel) {
                            await textChannel.send(textReply);
                            sentTextReply = true;
                        } else {
                            console.error('[Voice] Logs channel not found');
                        }
                    }
                } else {
                    console.log(`[Voice] Bot in voice channel, generating speech...`);
                    
                    // Check if there are pending TTS chunks or audio currently playing
                    const ttsState = getTTSState(guildId);
                    if (ttsState.isGenerating || ttsState.isPlaying || (ttsState.chunks.length > 0 && ttsState.currentChunkId < ttsState.chunks.length)) {
                        console.log(`[Voice] Skipping TTS - audio currently playing or pending chunks`);
                        console.log(`[Voice] TTS status: isPlaying=${ttsState.isPlaying}, pendingChunks=${ttsState.chunks.length}, currentChunk=${ttsState.currentChunkId}`);
                        // Still send text response if it's "both" mode
                        if (actualReplyMode === 'both') {
                            const guildInfo = client.guilds.cache.get(guildId);
                            if (guildInfo) {
                                const textChannel = getTextChannel(guildId);
                                if (textChannel) {
                                    await textChannel.send(textReply);
                                    sentTextReply = true;
                                }
                            }
                        }
                    } else {
                        ttsWasAttempted = true;
                        const played = await playTTSInChunks(guildId, response.data.response, userId);
                        if (played) {
                            console.log(`[Voice] Audio response played in voice channel`);
                        } else {
                            console.log(`[Voice] Audio playback failed, sending text response`);
                            // Fallback to text if audio fails
                            const guildInfo = client.guilds.cache.get(guildId);
                            if (guildInfo) {
                                const textChannel = getTextChannel(guildId);
                                if (textChannel) {
                                    await textChannel.send(textReply);
                                    sentTextReply = true;
                                }
                            }
                        }
                    }
                }
            }
            
            if (ttsWasAttempted) {
                try {
                    await axios.post(`${PYTHON_API_URL}/voice/turn/timing`, {
                        guild_id: guildId,
                        user_id: userId,
                        username,
                        transcript,
                        timings_ms: {
                            python_api: timingsMs.python_api || 0,
                            tts_generation_and_playback: Date.now() - ttsStartedAt
                        }
                    }, { timeout: 2000 });
                } catch (timingError) {
                    console.warn(`[Voice] Could not save TTS timing: ${timingError.message}`);
                }
            }

            if ((actualReplyMode === 'chat' || actualReplyMode === 'both') && !sentTextReply) {
                console.log(`[Voice] Chat mode - sending text response`);
                // Send text response via Python API (it will handle Discord)
                const guildInfo = client.guilds.cache.get(guildId);
                if (guildInfo) {
                    // Send to this guild's configured text channel.
                    const textChannel = getTextChannel(guildId);
                    if (textChannel) {
                        await textChannel.send(textReply);
                    } else {
                        console.error('[Voice] Logs channel not found');
                    }
                }
            }
        } else {
            console.log(`[${getTimestamp()}] [Voice] No response from Python API or status is not success`);
            console.log(`[${getTimestamp()}] [Voice] Response data: ${JSON.stringify(response.data)}`);
        }
        timing.end();
    } catch (error) {
        console.error(`[${getTimestamp()}] [Voice] Error sending to Python API:`, error);
        console.error(`[${getTimestamp()}] [Voice] Error details:`, error.response?.data || error.message);
        timing.end();
    }
}

/**
 * Wrap the decoded PCM in a proper WAV header for Groq
 * The Groq API expects standard WAV format with headers. The PCM data
 * from the voice receiver is raw audio data with no header at all, so Groq was receiving unplayable "audio". Chunks
 * from the receiver are now decoded PCM (48kHz, stereo, 16-bit) via
 * prism.opus.Decoder, so those are the defaults here.
 */
function pcmToWav(pcmBuffer, sampleRate = 48000, channels = 2, bitDepth = 16) {
    const byteRate = sampleRate * channels * (bitDepth / 8);
    const blockAlign = channels * (bitDepth / 8);
    const dataSize = pcmBuffer.length;
    const header = Buffer.alloc(44);

    header.write('RIFF', 0);
    header.writeUInt32LE(36 + dataSize, 4);
    header.write('WAVE', 8);
    header.write('fmt ', 12);
    header.writeUInt32LE(16, 16);
    header.writeUInt16LE(1, 20); // PCM format
    header.writeUInt16LE(channels, 22);
    header.writeUInt32LE(sampleRate, 24);
    header.writeUInt32LE(byteRate, 28);
    header.writeUInt16LE(blockAlign, 32);
    header.writeUInt16LE(bitDepth, 34);
    header.write('data', 36);
    header.writeUInt32LE(dataSize, 40);

    return Buffer.concat([header, pcmBuffer]);
}

/**
 * Join a voice channel with voice receive
 */
async function joinVoiceChannelCommand(interactionOrMessage) {
    const isInteraction = interactionOrMessage.isChatInputCommand?.();
    const message = isInteraction ? interactionOrMessage : interactionOrMessage;
    const voiceChannel = message.member?.voice?.channel;

    if (!voiceChannel) {
        const reply = 'You need to be in a voice channel!';
        if (isInteraction) {
            await interactionOrMessage.reply(reply);
        } else {
            await message.reply(reply);
        }
        return;
    }

    if (isInteraction) {
        await interactionOrMessage.deferReply();
    }

    try {
        const currentConnection = voiceConnections.get(message.guild.id);
        if (currentConnection && currentConnection.joinConfig.channelId === voiceChannel.id &&
            currentConnection.state.status !== VoiceConnectionStatus.Destroyed) {
            const alreadyConnected = 'Jenny is already connected to this voice channel.';
            if (isInteraction) await interactionOrMessage.editReply(alreadyConnected);
            else await message.reply(alreadyConnected);
            return;
        }
        if (currentConnection) currentConnection.destroy();
        const connection = joinVoiceChannel({
            channelId: voiceChannel.id,
            guildId: message.guild.id,
            adapterCreator: message.guild.voiceAdapterCreator,
            selfDeaf: false,
            selfMute: false
        });

        voiceConnections.set(message.guild.id, connection);
        voiceChannels.set(message.guild.id, voiceChannel);

        const player = createAudioPlayer();
        audioPlayers.set(message.guild.id, player);
        connection.subscribe(player);

        const receiver = connection.receiver;
        voiceReceivers.set(message.guild.id, receiver);

        console.log('[Voice] VoiceReceiver created');
        console.log(`[Voice] Receiver ready for channel ${voiceChannel.id}`);
        
        // Set up speaking event handlers
        let speakingEventCount = 0;
        receiver.speaking.on('start', (userId) => {
            speakingEventCount++;
            // Reduce speaking event logging - only log every 25 events
            if (speakingEventCount % 25 === 0 || speakingEventCount === 1) {
                console.log(`[Voice] Speaking event fired! Count: ${speakingEventCount}, User: ${userId}`);
            }
            
            if (userId === client.user.id) return;
            
            const channel = voiceChannels.get(message.guild.id);
            if (!channel) {
                console.error('[Voice] Voice channel not found for speaking event');
                return;
            }
            
            const member = channel.members.get(userId);
            const displayName = member?.displayName || member?.user?.username || userId;
            if (isVoiceMemberMuted(member)) {
                const buffer = audioBuffers.get(message.guild.id);
                if (buffer) buffer.delete(userId);
                if (pendingFlushTimeouts.has(userId)) {
                    clearTimeout(pendingFlushTimeouts.get(userId));
                    pendingFlushTimeouts.delete(userId);
                }
                return;
            }
            if (speakingEventCount % 25 === 0 || speakingEventCount === 1) {
                console.log(`[Voice] Speaking START: ${displayName} (${userId})`);
            }

            if (pendingFlushTimeouts.has(userId)) {
                clearTimeout(pendingFlushTimeouts.get(userId));
                pendingFlushTimeouts.delete(userId);
                // Only log this occasionally to reduce spam
                if (speakingEventCount % 25 === 0) {
                    console.log(`[Voice] Cancelled pending flush for ${displayName}, still talking`);
                }
            }

            if (activePipelines.has(userId)) {
                // Only log this rarely to reduce spam
                if (speakingEventCount % 50 === 0) {
                    console.log(`[Voice] ${displayName} already has an active pipeline, skipping duplicate subscription`);
                }
                return;
            }

            try {
                console.log(`[Voice] Dynamic subscription to ${displayName} on speaking event...`);
                const opusStream = receiver.subscribe(userId, {
                    end: {
                        behavior: EndBehaviorType.AfterSilence,
                        duration: SILENCE_END_MS
                    }
                });
                console.log(`[Voice] Dynamic subscription successful for ${displayName}`);
                activePipelines.add(userId);

                const pcmStream = opusStream.pipe(new prism.opus.Decoder({
                    rate: 48000,
                    channels: 2,
                    frameSize: 960
                }));

                let chunkCount = 0;
                pcmStream.on('data', (chunk) => {
                    chunkCount++;
                    // Only log every 50 chunks to reduce console spam
                    if (chunkCount % 50 === 0) {
                        console.log(`[Voice] Dynamic audio chunk ${chunkCount} from ${displayName}: ${chunk.length} bytes`);
                    }
                    handleAudioChunk(message.guild.id, userId, chunk);
                });
                
                opusStream.on('error', (error) => {
                    console.error(`[Voice] Dynamic stream error for ${displayName}:`, error);
                    activePipelines.delete(userId);
                });

                pcmStream.on('error', (error) => {
                    console.error(`[Voice] Opus decode error for ${displayName}:`, error);
                });
                
                opusStream.on('end', () => {
                    console.log(`[Voice] Dynamic stream ended for ${displayName} (total chunks: ${chunkCount})`);
                    activePipelines.delete(userId);
                });
            } catch (error) {
                console.error(`[Voice] Error dynamically subscribing to ${displayName}:`, error);
            }
        });
        
        receiver.speaking.on('end', (userId) => {
            const channel = voiceChannels.get(message.guild.id);
            if (!channel) {
                console.error('[Voice] Voice channel not found for speaking end event');
                return;
            }

            const member = channel.members.get(userId);
            const displayName = member?.displayName || member?.user?.username || userId;
            // Reduce speaking END logging - only log every 25 events
            if (speakingEventCount % 25 === 0 || speakingEventCount === 1) {
                console.log(`[Voice] Speaking END: ${displayName} (${userId})`);
            }

            // Check if user is muted - skip processing if they are
            if (isVoiceMemberMuted(member)) {
                const buffer = audioBuffers.get(message.guild.id);
                if (buffer) buffer.delete(userId);
                return;
            }

            const timeoutHandle = setTimeout(() => {
                pendingFlushTimeouts.delete(userId);
                flushUserAudio(message.guild.id, userId);
            }, FLUSH_DEBOUNCE_MS);
            pendingFlushTimeouts.set(userId, timeoutHandle);
        });

        const reply = `Joined voice channel: ${voiceChannel.name} with voice receive`;
        if (isInteraction) {
            await interactionOrMessage.editReply(reply);
        } else {
            await message.reply(reply);
        }

        console.log(`[Voice] Joined voice channel: ${voiceChannel.name}`);
    } catch (error) {
        console.error('[Voice] Error joining voice channel:', error);
        const reply = 'Error joining voice channel';
        if (isInteraction) {
            await interactionOrMessage.editReply(reply);
        } else {
            await message.reply(reply);
        }
    }
}

/**
 * Leave a voice channel
 */
async function leaveVoiceChannelCommand(interactionOrMessage) {
    const isInteraction = interactionOrMessage.isChatInputCommand?.();
    const message = isInteraction ? interactionOrMessage : interactionOrMessage;
    const connection = voiceConnections.get(message.guild.id);

    if (!connection) {
        const reply = 'Not in a voice channel';
        if (isInteraction) {
            await interactionOrMessage.reply(reply);
        } else {
            await message.reply(reply);
        }
        return;
    }

    connection.destroy();
    voiceConnections.delete(message.guild.id);
    audioPlayers.delete(message.guild.id);
    voiceReceivers.delete(message.guild.id);
    audioBuffers.delete(message.guild.id);
    voiceChannels.delete(message.guild.id);
    activePipelines.clear();
    pendingFlushTimeouts.forEach((handle) => clearTimeout(handle));
    pendingFlushTimeouts.clear();

    const reply = 'Left voice channel';
    if (isInteraction) {
        await interactionOrMessage.reply(reply);
    } else {
        await message.reply(reply);
    }

    console.log('[Voice] Left voice channel');
}

/**
 * Test TTS command
 */
async function testTTSCommand(interactionOrMessage, testText) {
    const isInteraction = interactionOrMessage.isChatInputCommand?.();
    const message = isInteraction ? interactionOrMessage : interactionOrMessage;
    const guildId = message.guild.id;

    console.log('[Voice] Testing TTS with:', testText);
    console.log('[Voice] Current guild ID:', guildId);
    console.log('[Voice] Voice connections:', Array.from(voiceConnections.keys()));
    console.log('[Voice] Audio players:', Array.from(audioPlayers.keys()));

    const reply = voiceConnections.has(guildId)
        ? '✅ TTS test queued for voice channel'
        : '❌ Not in voice channel - join with /joinvc first';
    if (isInteraction) await interactionOrMessage.reply(reply);
    else await message.reply(reply);
    if (voiceConnections.has(guildId)) {
        enqueueTTSOperation(guildId, testText, true).catch(error => console.error('[Voice] TTS test failed:', error.message));
    }
}

/**
 * Test beep command
 */
async function testBeepCommand(interactionOrMessage) {
    const isInteraction = interactionOrMessage.isChatInputCommand?.();
    const message = isInteraction ? interactionOrMessage : interactionOrMessage;
    const guildId = message.guild.id;

    console.log('[Voice] Testing with simple beep');
    const sampleRate = 48000;
    const duration = 0.5;
    const frequency = 440;
    const samples = sampleRate * duration;
    const beepBuffer = Buffer.alloc(samples * 2);

    for (let i = 0; i < samples; i++) {
        const t = i / sampleRate;
        const sample = Math.sin(2 * Math.PI * frequency * t) * 0.3;
        const int16 = Math.floor(sample * 32767);
        beepBuffer.writeInt16LE(i * 2, int16);
    }

    const wavBuffer = pcmToWav(beepBuffer);

    if (voiceConnections.has(guildId)) {
        await playAudio(guildId, wavBuffer);
        const reply = '✅ Beep played in voice channel';
        if (isInteraction) {
            await interactionOrMessage.reply(reply);
        } else {
            await message.reply(reply);
        }
    } else {
        const reply = '❌ Not in voice channel';
        if (isInteraction) {
            await interactionOrMessage.reply(reply);
        } else {
            await message.reply(reply);
        }
    }
}

/**
 * Voice test command
 */
async function voiceTestCommand(interactionOrMessage) {
    const isInteraction = interactionOrMessage.isChatInputCommand?.();
    const message = isInteraction ? interactionOrMessage : interactionOrMessage;

    const reply = 'Starting minimal voice receive test...';
    if (isInteraction) {
        await interactionOrMessage.reply(reply);
    } else {
        await message.reply(reply);
    }

    console.log('[Voice] MINIMAL VOICE TEST START');

    const voiceChannel = message.member.voice.channel;
    if (!voiceChannel) {
        const reply = 'You need to be in a voice channel!';
        if (isInteraction) {
            await interactionOrMessage.editReply(reply);
        } else {
            await message.reply(reply);
        }
        return;
    }

    const connection = voiceConnections.get(message.guild.id);
    if (!connection) {
        const reply = 'Bot not in voice channel - use /joinvc first';
        if (isInteraction) {
            await interactionOrMessage.editReply(reply);
        } else {
            await message.reply(reply);
        }
        return;
    }

    console.log('[Voice] Connection found:', connection.state.status);
    console.log('[Voice] Connection type:', connection.constructor.name);
    console.log('[Voice] Connection methods:', Object.getOwnPropertyNames(Object.getPrototypeOf(connection)));

    const receiver = voiceReceivers.get(message.guild.id);
    if (receiver) {
        console.log('[Voice] Receiver found');
        console.log('[Voice] Receiver type:', receiver.constructor.name);
        console.log('[Voice] Receiver methods:', Object.getOwnPropertyNames(Object.getPrototypeOf(receiver)));
        console.log('[Voice] Speaking map size:', receiver.speaking.users.size);
        console.log('[Voice] SSRC map size:', receiver.ssrcMap.map.size);
    } else {
        console.log('[Voice] No receiver found');
    }

    const finalReply = 'Voice test complete - check console for details';
    if (isInteraction) {
        await interactionOrMessage.editReply(finalReply);
    } else {
        await message.reply(finalReply);
    }
}

/**
 * Speak command
 */
async function speakCommand(interactionOrMessage, textToSpeak) {
    const isInteraction = interactionOrMessage.isChatInputCommand?.();
    const message = isInteraction ? interactionOrMessage : interactionOrMessage;
    const guildId = message.guild.id;

    console.log('[Voice] TTS command with:', textToSpeak);
    console.log('[Voice] Current guild ID:', guildId);
    console.log('[Voice] Voice connections:', Array.from(voiceConnections.keys()));
    console.log('[Voice] Audio players:', Array.from(audioPlayers.keys()));

    const reply = voiceConnections.has(guildId)
        ? '✅ Playing in voice channel'
        : '❌ Not in voice channel - join with /joinvc first';
    if (isInteraction) await interactionOrMessage.reply(reply);
    else await message.reply(reply);
    if (voiceConnections.has(guildId)) {
        enqueueTTSOperation(guildId, textToSpeak, true).catch(error => console.error('[Voice] Speak command failed:', error.message));
    }
}

/**
 * Register slash commands - DISABLED to avoid conflicts with Python bot
 * Voice service now only handles message-based commands like !joinvc
 */
// async function registerSlashCommands() {
//     const commands = [
//         new SlashCommandBuilder()
//             .setName('joinvc')
//             .setDescription('Join the voice channel'),
//         new SlashCommandBuilder()
//             .setName('leavevc')
//             .setDescription('Leave the voice channel'),
//         new SlashCommandBuilder()
//             .setName('record')
//             .setDescription('Start manual voice recording (5 seconds)'),
//         new SlashCommandBuilder()
//             .setName('stoprecord')
//             .setDescription('Stop manual voice recording'),
//         new SlashCommandBuilder()
//             .setName('testtts')
//             .setDescription('Test text-to-speech')
//             .addStringOption(option =>
//                 option.setName('text')
//                     .setDescription('Text to speak')
//                     .setRequired(false)
//             ),
//         new SlashCommandBuilder()
//             .setName('testbeep')
//             .setDescription('Test with a simple beep sound'),
//         new SlashCommandBuilder()
//             .setName('voicetest')
//             .setDescription('Test voice receive functionality'),
//         new SlashCommandBuilder()
//             .setName('speak')
//             .setDescription('Speak text in voice channel')
//             .addStringOption(option =>
//                 option.setName('text')
//                     .setDescription('Text to speak')
//                     .setRequired(true)
//             ),
//         new SlashCommandBuilder()
//             .setName('voicestatus')
//             .setDescription('Check if bot is in voice channel'),
//     ];
//
//     const rest = new REST({ version: '10' }).setToken(DISCORD_TOKEN);
//
//     try {
//         console.log('[Voice] Started refreshing application (/) commands.');
//
//         await rest.put(
//             Routes.applicationCommands(client.user.id),
//             { body: commands },
//         );
//
//         console.log('[Voice] Successfully reloaded application (/) commands.');
//     } catch (error) {
//         console.error('[Voice] Error reloading application (/) commands:', error);
//     }
// }

/**
 * Handle Discord events
 */
client.once('ready', () => {
    console.log(`[Voice] Voice service logged in as ${client.user.tag}`);
    console.log(`[Voice] Connected to Python API at: ${PYTHON_API_URL}`);
    console.log(`[Voice] Groq STT initialized`);
    console.log(`[Voice] Deepgram TTS initialized`);
    console.log(`[Voice] STT Model: ${GROQ_STT_MODEL}`);
    console.log(`[Voice] TTS Model: ${DEEPGRAM_TTS_MODEL}`);
    console.log('[Voice] Discord.js Voice Receive enabled');
    console.log('[Voice] Ready for real voice input/output');

    const heartbeat = () => axios.post(`${PYTHON_API_URL}/voice/service/heartbeat`, { status: 'online' }, { timeout: 2000 })
        .catch(error => console.warn(`[Voice] Python API heartbeat failed: ${error.message}`));
    void heartbeat();
    setInterval(heartbeat, 10000);

    // Register slash commands - DISABLED to avoid conflicts with Python bot
    // registerSlashCommands();

    // Start polling for voice commands from Python API
    setInterval(pollVoiceCommands, 1000); // Poll every second
});

// Poll for voice commands from Python API
async function pollVoiceCommands() {
    try {
        // Get list of guilds the bot is in
        const guilds = Array.from(client.guilds.cache.values());

        for (const guild of guilds) {
            try {
                const guildId = guild.id;
                const response = await axios.get(`${PYTHON_API_URL}/voice/command/${guildId}`);
                if (['chat', 'vc', 'both'].includes(response.data.reply_mode)) {
                    replyModes.set(guildId, response.data.reply_mode);
                }
                if (response.data.text_channel_id) textChannels.set(guildId, response.data.text_channel_id);

                if (response.data.status === 'success' && response.data.command) {
                    console.log(`[Voice] Received command: ${response.data.command} for guild ${guildId}`);

                    if (response.data.text_channel_id) textChannels.set(guildId, response.data.text_channel_id);

                    const command = response.data.command;
                    
                    if (command === 'join') {
                        console.log(`[Voice] Processing join command for guild ${guild.id}`);
                        console.log(`[Voice] Requested channel ID: ${response.data.channel_id}`);
                        
                        // Use specific channel if provided, otherwise find active channel
                        let voiceChannel;
                        if (response.data.channel_id) {
                            voiceChannel = guild.channels.cache.get(response.data.channel_id);
                            console.log(`[Voice] Looking for channel ID ${response.data.channel_id}:`, voiceChannel ? `Found ${voiceChannel.name}` : 'Not found');
                        }
                        
                        if (!voiceChannel) {
                            console.log(`[Voice] No specific channel found, searching for active channels`);
                            // Find a voice channel to join - prefer channels with members, but join any if needed
                            voiceChannel = guild.channels.cache.find(channel => 
                                channel.type === 'GUILD_VOICE' && channel.members.size > 0
                            );
                            console.log(`[Voice] Active channel search result:`, voiceChannel ? `Found ${voiceChannel.name}` : 'None found');
                            
                            // If no active channel, find any voice channel
                            if (!voiceChannel) {
                                console.log(`[Voice] No active channels, searching for any voice channel`);
                                voiceChannel = guild.channels.cache.find(channel => 
                                    channel.type === 'GUILD_VOICE'
                                );
                                console.log(`[Voice] Any channel search result:`, voiceChannel ? `Found ${voiceChannel.name}` : 'None found');
                            }
                        }
                        
                        if (voiceChannel) {
                            const currentConnection = voiceConnections.get(guild.id);
                            if (currentConnection && currentConnection.joinConfig.channelId === voiceChannel.id &&
                                currentConnection.state.status !== VoiceConnectionStatus.Destroyed) {
                                console.log(`[Voice] Already connected to ${voiceChannel.name}; skipping duplicate join`);
                                continue;
                            }
                            if (currentConnection) currentConnection.destroy();
                            console.log(`[Voice] Attempting to join voice channel: ${voiceChannel.name} (${voiceChannel.id})`);
                            
                            try {
                                // Direct join without message/interaction wrapper
                                const connection = joinVoiceChannel({
                                    channelId: voiceChannel.id,
                                    guildId: guild.id,
                                    adapterCreator: guild.voiceAdapterCreator,
                                    selfDeaf: false,
                                    selfMute: false
                                });

                                console.log(`[Voice] Connection created for guild ${guild.id}, channel ${voiceChannel.id}`);

                                // Set up error handler for connection
                                connection.on('error', (error) => {
                                    console.error('[Voice] Voice connection error:', error);
                                });

                                // Wait for connection to be ready with timeout
                                try {
                                    await entersState(connection, VoiceConnectionStatus.Ready, 30000);
                                    console.log(`[Voice] Connection is ready`);
                                await notifyPythonVoiceStatus(guild.id, true, voiceChannel.id);
                                } catch (error) {
                                    console.error(`[Voice] Connection failed to reach ready state:`, error);
                                    connection.destroy();
                                    await notifyPythonVoiceStatus(guild.id, false);
                                    throw error;
                                }

                                voiceConnections.set(guild.id, connection);
                                voiceChannels.set(guild.id, voiceChannel);

                                const player = createAudioPlayer();
                                audioPlayers.set(guild.id, player);
                                connection.subscribe(player);

                                const receiver = connection.receiver;
                                voiceReceivers.set(guild.id, receiver);

                                console.log('[Voice] VoiceReceiver created');
                                console.log(`[Voice] Receiver ready for channel ${voiceChannel.id}`);

                                // Set up speaking event handlers
                                let speakingEventCount = 0;
                                receiver.speaking.on('start', (userId) => {
                                    speakingEventCount++;
                                    if (speakingEventCount % 25 === 0 || speakingEventCount === 1) {
                                        console.log(`[Voice] Speaking event fired! Count: ${speakingEventCount}, User: ${userId}`);
                                    }

                                    if (userId === client.user.id) return;

                                    const member = voiceChannel.members.get(userId);
                                    if (!member) {
                                        console.error('[Voice] Member not found for speaking event');
                                        return;
                                    }

                                    const displayName = member?.displayName || member?.user?.username || userId;
                                    if (isVoiceMemberMuted(member)) {
                                        const buffer = audioBuffers.get(guild.id);
                                        if (buffer) buffer.delete(userId);
                                        return;
                                    }
                                    if (speakingEventCount % 25 === 0 || speakingEventCount === 1) {
                                        console.log(`[Voice] ${displayName} started speaking`);
                                    }

                                    // Cancel any pending flush if user starts speaking again
                                    if (pendingFlushTimeouts.has(userId)) {
                                        clearTimeout(pendingFlushTimeouts.get(userId));
                                        pendingFlushTimeouts.delete(userId);
                                        // Only log this occasionally to reduce spam
                                        if (speakingEventCount % 25 === 0) {
                                            console.log(`[Voice] Cancelled pending flush for ${displayName}, still talking`);
                                        }
                                    }

                                    // Check if user is muted - skip processing if they are
                                    if (activePipelines.has(userId)) {
                                        // Only log this occasionally to reduce spam
                                        if (speakingEventCount % 50 === 0) {
                                            console.log(`[Voice] Pipeline already active for ${displayName}, skipping`);
                                        }
                                        return;
                                    }

                                    try {
                                        const opusStream = receiver.subscribe(userId, {
                                            end: { behavior: EndBehaviorType.AfterSilence, duration: SILENCE_END_MS }
                                        });
                                        if (!opusStream) {
                                            console.error(`[Voice] Failed to subscribe to ${displayName}`);
                                            return;
                                        }

                                        activePipelines.add(userId);
                                        let chunkCount = 0;

                                        // Use prism-media's opus decoder instead of @discordjs/opus
                                        const pcmStream = opusStream.pipe(new prism.opus.Decoder({ channels: 2, rate: 48000 }));
                                        const chunks = [];

                                        pcmStream.on('data', (chunk) => {
                                            chunks.push(chunk);
                                            chunkCount++;
                                            handleAudioChunk(guild.id, userId, chunk);
                                        });

                                        pcmStream.on('error', (error) => {
                                            console.error(`[Voice] Opus decode error for ${displayName}:`, error);
                                        });

                                        opusStream.on('end', () => {
                                            console.log(`[Voice] Dynamic stream ended for ${displayName} (total chunks: ${chunkCount})`);
                                            activePipelines.delete(userId);
                                        });
                                    } catch (error) {
                                        console.error(`[Voice] Error dynamically subscribing to ${displayName}:`, error);
                                    }
                                });

                                receiver.speaking.on('end', (userId) => {
                                    const member = voiceChannel.members.get(userId);
                                    const displayName = member?.displayName || member?.user?.username || userId;

                                    if (speakingEventCount % 25 === 0 || speakingEventCount === 1) {
                                        console.log(`[Voice] Speaking END: ${displayName} (${userId})`);
                                    }

                                    // Check if user is muted - skip processing if they are
                                    if (isVoiceMemberMuted(member)) {
                                        const buffer = audioBuffers.get(guild.id);
                                        if (buffer) buffer.delete(userId);
                                        return;
                                    }

                                    if (pendingFlushTimeouts.has(userId)) {
                                        clearTimeout(pendingFlushTimeouts.get(userId));
                                        pendingFlushTimeouts.delete(userId);
                                        // Only log this occasionally to reduce spam
                                        if (speakingEventCount % 25 === 0) {
                                            console.log(`[Voice] Cancelled pending flush for ${displayName}, still talking`);
                                        }
                                    }

                                    const timeoutHandle = setTimeout(() => {
                                        pendingFlushTimeouts.delete(userId);
                                        flushUserAudio(guild.id, userId);
                                    }, FLUSH_DEBOUNCE_MS);
                                    pendingFlushTimeouts.set(userId, timeoutHandle);
                                });

                                console.log(`[Voice] Successfully joined voice channel: ${voiceChannel.name}`);
                            } catch (error) {
                                console.error(`[Voice] Error joining voice channel:`, error);
                                await notifyPythonVoiceStatus(guild.id, false);
                                // Clean up on error
                                if (voiceConnections.has(guild.id)) {
                                    voiceConnections.get(guild.id).destroy();
                                    voiceConnections.delete(guild.id);
                                }
                            }
                        } else {
                            console.log('[Voice] No voice channel found in guild');
                        }
                    } else if (command === 'leave') {
                        const connection = voiceConnections.get(guild.id);
                        if (connection) {
                            connection.destroy();
                            await notifyPythonVoiceStatus(guild.id, false);
                            voiceConnections.delete(guild.id);
                            audioPlayers.delete(guild.id);
                            voiceReceivers.delete(guild.id);
                            audioBuffers.delete(guild.id);
                            voiceChannels.delete(guild.id);
                            activePipelines.clear();
                            pendingFlushTimeouts.forEach((handle) => clearTimeout(handle));
                            pendingFlushTimeouts.clear();
                            console.log(`[Voice] Left voice channel in guild ${guildId}`);
                        }
                    } else if (command === 'replymode') {
                        const mode = response.data.mode;
                        replyModes.set(guildId, mode);
                        console.log(`[Voice] Reply mode set to: ${mode}`);
                    }
                }
            } catch (error) {
                // Ignore errors for individual guilds (might not have commands)
            }
        }
    } catch (error) {
        console.error('[Voice] Error polling voice commands:', error.message);
    }
}

client.on('messageCreate', async (message) => {
    // Ignore messages from bots (including Jenny's Python bot)
    if (message.author.bot) return;

    // Ignore messages that are replies to other messages (to avoid processing Jenny's responses)
    if (message.type === 'REPLY') return;

    // Process voice commands - DISABLED
    // All voice commands now handled by Python bot via API
    // await handleVoiceCommand(message);
});

// Handle slash commands - DISABLED to avoid conflicts with Python bot
// Voice service now only handles message-based commands like !joinvc
// client.on('interactionCreate', async (interaction) => {
//     if (!interaction.isChatInputCommand()) return;
// 
//     const { commandName } = interaction;
// 
//     try {
//         switch (commandName) {
//             case 'joinvc':
//                 await joinVoiceChannelCommand(interaction);
//                 break;
//             case 'leavevc':
//                 await leaveVoiceChannelCommand(interaction);
//                 break;
//             case 'record':
//                 await startManualRecording(interaction);
//                 break;
//             case 'stoprecord':
//                 await stopManualRecording(interaction);
//                 break;
//             case 'testtts':
//                 const testText = interaction.options.getString('text') || 'This is a test of the text to speech system.';
//                 await testTTSCommand(interaction, testText);
//                 break;
//             case 'testbeep':
//                 await testBeepCommand(interaction);
//                 break;
//             case 'voicetest':
//                 await voiceTestCommand(interaction);
//                 break;
//             case 'speak':
//                 const speakText = interaction.options.getString('text');
//                 await speakCommand(interaction, speakText);
//                 break;
//             case 'voicestatus':
//                 const guildId = interaction.guild.id;
//                 const inVoice = isInVoiceChannel(guildId);
//                 const status = inVoice ? `✅ Bot is in voice channel` : `❌ Bot is not in voice channel`;
//                 await interaction.reply(status);
//                 break;
//             default:
//                 await interaction.reply('Unknown command');
//         }
//     } catch (error) {
//         console.error('[Voice] Error handling slash command:', error);
//         // Only reply if the interaction hasn't been acknowledged yet
//         if (!interaction.replied && !interaction.deferred) {
//             try {
//                 await interaction.reply('There was an error executing this command!');
//             } catch (replyError) {
//                 console.error('[Voice] Error sending error reply:', replyError);
//             }
//         }
//     }
// });

// TTS polling for Python bot integration
let ttsPollingActive = false;
setInterval(async () => {
    try {
        // Only poll if we have active voice connections
        if (voiceConnections.size === 0) {
            return;
        }
        
        // Only poll if Python API is available
        try {
            const healthCheck = await axios.get(`${PYTHON_API_URL}/health`, { timeout: 2000 });
            if (healthCheck.data.status !== 'healthy') {
                return;
            }
        } catch (error) {
            // Python API not available, skip polling
            return;
        }
        
        // Check for TTS requests from Python bot
        for (const [guildId, connection] of voiceConnections.entries()) {
            try {
                // Check if there are pending TTS chunks or audio currently playing
                const ttsState = getTTSState(guildId);
                if (ttsState.isGenerating || ttsState.isPlaying || (ttsState.chunks.length > 0 && ttsState.currentChunkId < ttsState.chunks.length)) {
                    console.log(`[Voice] Skipping TTS request for guild ${guildId} - audio currently playing or pending chunks`);
                    continue;
                }
                
                const response = await axios.get(`${PYTHON_API_URL}/voice/tts/${guildId}`, { timeout: 2000 });
                if (response.data.status === 'success' && response.data.text) {
                    console.log(`[Voice] TTS request from Python bot: "${response.data.text}"`);
                    const played = await playTTSInChunks(guildId, response.data.text, response.data.user_id || null);
                    if (!played) {
                        console.log(`[Voice] Failed to play TTS from Python bot`);
                    }
                }
            } catch (error) {
                // No TTS request for this guild, continue
                if (error.response?.status !== 404) {
                    console.error(`[Voice] Error checking TTS for guild ${guildId}:`, error.message);
                }
            }
        }
    } catch (error) {
        console.error('[Voice] Error in TTS polling:', error);
    }
}, 1000);

/**
 * Handle voice commands - DISABLED
 * All voice commands now handled by Python bot via API
 */
// async function handleVoiceCommand(message) {
//     const content = message.content.toLowerCase();
//     const guildId = message.guild.id;
//
//     // Manual recording command - DISABLED
//     // if (content.startsWith('!record')) {
//     //     await startManualRecording(message);
//     //     return;
//     // }
//
//     // Stop manual recording command - DISABLED
//     // if (content.startsWith('!stoprecord')) {
//     //     await stopManualRecording(message);
//     //     return;
//     // }
//
//     // Voice control commands ONLY - call the wrapper functions with message
//     if (content.startsWith('!joinvc')) {
//         await joinVoiceChannelCommand(message);
//         return;
//     }
//
//     if (content.startsWith('!leavevc')) {
//         await leaveVoiceChannelCommand(message);
//         return;
//     }
//
//     // Reply mode commands
//     if (content.includes('set reply mode to chat')) {
//         globalReplyMode = 'chat';
//         await message.reply('Global reply mode set to: Chat only (text only)');
//         return;
//     }
//
//     if (content.includes('set reply mode to voice only')) {
//         globalReplyMode = 'vc';
//         await message.reply('Global reply mode set to: Voice only (no text response)');
//         return;
//     }
//
//     if (content.includes('set reply mode to both')) {
//         globalReplyMode = 'both';
//         await message.reply('Global reply mode set to: Both voice and text');
//         return;
//     }
//
//     if (content.includes('get reply mode')) {
//         await message.reply(`Current reply mode: ${globalReplyMode}`);
//         return;
//     }
//
//     // Test TTS directly for debugging
//     if (content.startsWith('!testtts')) {
//         const testText = content.replace('!testtts', '').trim() || 'This is a test of the text to speech system.';
//         await testTTSCommand(message, testText);
//         return;
//     }
//
//     // Test with a simple beep sound
//     if (content.startsWith('!testbeep')) {
//         await testBeepCommand(message);
//         return;
//     }
//
//     // Minimal voice receive test
//     if (content.startsWith('!voicetest')) {
//         await voiceTestCommand(message);
//         return;
//     }
//
//     // Direct TTS command with better debugging - DISABLED
//     // if (content.startsWith('!tts ')) {
//     //     const textToSpeak = content.replace('!tts ', '').trim();
//     //     await speakCommand(message, textToSpeak);
//     //     return;
//     // }
//
//     // Do NOT process text wake words - Jenny bot handles text chat
//     // Voice service ONLY handles voice input
// }

// Login
client.login(DISCORD_TOKEN);
