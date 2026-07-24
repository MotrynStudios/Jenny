import os
import time
import re
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration loader from .env"""
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL")
    GROQ_SECOND_TEXT_MODEL = os.getenv("GROQ_SECOND_TEXT_MODEL")
    GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL")
    
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")
    
    MAX_PROMPT_TOKENS = int(os.getenv("MAX_PROMPT_TOKENS", 2500))
    MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", 500))
    VISION_MAX_TOKENS = int(os.getenv("VISION_MAX_TOKENS", 300))
    
    # Context budget allocation (priority-based)
    SYSTEM_PROMPT_BUDGET = 400      # System message (highest priority)
    CURRENT_MESSAGE_BUDGET = 300    # Current user message
    REPLY_CONTEXT_BUDGET = 250      # Reply context (if exists)
    SEARCH_RESULTS_BUDGET = 400     # Tavily results
    USER_HISTORY_BUDGET = 800       # User memory/history
    CHANNEL_LOG_BUDGET = 400        # Recent channel messages
    
    DISCORD_MAX_LENGTH = 2000
    
    # Cache settings
    TAVILY_CACHE_TTL_SECONDS = 300  # 5 minutes
    RESPONSE_CACHE_TTL_SECONDS = 60  # 1 minute
    
    # Retry settings
    RETRY_DELAY_SECONDS = 1.0
    MAX_RETRIES_PER_MODEL = 1  # Only retry once
    
    # Cooldown settings
    DEFAULT_COOLDOWN_MINUTES = 30


# Initialize clients
groq_client = OpenAI(
    api_key=Config.GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

openrouter_client = OpenAI(
    api_key=Config.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)


# ============================================================================
# STATISTICS TRACKING
# ============================================================================

class ModelStats:
    """Per-model statistics tracking"""
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_response_time = 0.0
        self.rate_limit_count = 0
        self.retry_count = 0
        self.cooldown_count = 0
    
    def record_success(self, response_time: float):
        self.total_requests += 1
        self.successful_requests += 1
        self.total_response_time += response_time
    
    def record_failure(self):
        self.total_requests += 1
        self.failed_requests += 1
    
    def record_rate_limit(self):
        self.rate_limit_count += 1
    
    def record_retry(self):
        self.retry_count += 1
    
    def record_cooldown(self):
        self.cooldown_count += 1
    
    def avg_response_time(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_response_time / self.successful_requests
    
    def __str__(self) -> str:
        success_rate = (self.successful_requests / self.total_requests * 100) if self.total_requests > 0 else 0
        return (
            f"{self.model_name}: "
            f"Requests={self.total_requests}, "
            f"Success={self.successful_requests} ({success_rate:.1f}%), "
            f"Failures={self.failed_requests}, "
            f"AvgTime={self.avg_response_time():.2f}s, "
            f"RateLimits={self.rate_limit_count}, "
            f"Retries={self.retry_count}, "
            f"Cooldowns={self.cooldown_count}"
        )


class StatsTracker:
    """Global statistics tracker"""
    def __init__(self):
        self.models: Dict[str, ModelStats] = {}
    
    def get_stats(self, model_name: str) -> ModelStats:
        if model_name not in self.models:
            self.models[model_name] = ModelStats(model_name)
        return self.models[model_name]
    
    def print_stats(self):
        log_message("[STATS] ===== MODEL STATISTICS =====")
        for model_name in [Config.GROQ_TEXT_MODEL, Config.GROQ_SECOND_TEXT_MODEL, Config.OPENROUTER_MODEL]:
            if model_name:
                log_message(f"[STATS] {self.get_stats(model_name)}")
        log_message("[STATS] ===============================")


stats_tracker = StatsTracker()


# ============================================================================
# COOLDOWN MANAGEMENT
# ============================================================================

class CooldownManager:
    """Manages model cooldowns with thread-safe operations"""
    def __init__(self):
        self.cooldowns: Dict[str, datetime] = {}
    
    def set_cooldown(self, model_name: str, duration_minutes: int = Config.DEFAULT_COOLDOWN_MINUTES):
        """Place a model on cooldown"""
        cooldown_until = datetime.now() + timedelta(minutes=duration_minutes)
        self.cooldowns[model_name] = cooldown_until
        log_message(f"[COOLDOWN] {model_name} on cooldown until {cooldown_until.strftime('%H:%M:%S')} ({duration_minutes} min)")
        stats_tracker.get_stats(model_name).record_cooldown()
    
    def is_available(self, model_name: str) -> bool:
        """Check if a model is available (not on cooldown)"""
        if model_name not in self.cooldowns:
            return True
        
        cooldown_until = self.cooldowns[model_name]
        if datetime.now() >= cooldown_until:
            del self.cooldowns[model_name]
            log_message(f"[COOLDOWN] {model_name} cooldown expired, resuming")
            return True
        
        return False
    
    def get_cooldown_until(self, model_name: str) -> Optional[datetime]:
        """Get the timestamp when a model becomes available"""
        return self.cooldowns.get(model_name)


cooldown_manager = CooldownManager()


# ============================================================================
# CACHING
# ============================================================================

class TavilyCacheEntry:
    """Cache entry for Tavily search results"""
    def __init__(self, result: str, ttl_seconds: int = Config.TAVILY_CACHE_TTL_SECONDS):
        self.result = result
        self.created_at = datetime.now()
        self.expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    
    def is_expired(self) -> bool:
        return datetime.now() >= self.expires_at


class ResponseCacheEntry:
    """Cache entry for AI responses"""
    def __init__(self, response: str, ttl_seconds: int = Config.RESPONSE_CACHE_TTL_SECONDS):
        self.response = response
        self.created_at = datetime.now()
        self.expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    
    def is_expired(self) -> bool:
        return datetime.now() >= self.expires_at


class CacheManager:
    """Manages both Tavily and response caches"""
    def __init__(self):
        self.tavily_cache: Dict[str, TavilyCacheEntry] = {}
        self.response_cache: Dict[str, ResponseCacheEntry] = {}
    
    def _hash_query(self, query: str) -> str:
        """Create a hash of a query for use as cache key"""
        return hashlib.md5(query.encode()).hexdigest()
    
    def get_tavily_result(self, query: str) -> Optional[str]:
        """Get cached Tavily result if available and not expired"""
        key = self._hash_query(query)
        if key in self.tavily_cache:
            entry = self.tavily_cache[key]
            if not entry.is_expired():
                log_message(f"[CACHE_HIT] Tavily cache hit for query (TTL remaining: {(entry.expires_at - datetime.now()).seconds}s)")
                return entry.result
            else:
                del self.tavily_cache[key]
        return None
    
    def cache_tavily_result(self, query: str, result: str):
        """Cache a Tavily result"""
        key = self._hash_query(query)
        self.tavily_cache[key] = TavilyCacheEntry(result)
    
    def get_cached_response(self, messages_hash: str) -> Optional[str]:
        """Get cached response if available and not expired"""
        if messages_hash in self.response_cache:
            entry = self.response_cache[messages_hash]
            if not entry.is_expired():
                log_message(f"[CACHE_HIT] Response cache hit (TTL remaining: {(entry.expires_at - datetime.now()).seconds}s)")
                return entry.response
            else:
                del self.response_cache[messages_hash]
        return None
    
    def cache_response(self, messages_hash: str, response: str):
        """Cache an AI response"""
        self.response_cache[messages_hash] = ResponseCacheEntry(response)
    
    def clear_expired(self):
        """Clean up expired cache entries"""
        # Clean Tavily cache
        expired_keys = [k for k, v in self.tavily_cache.items() if v.is_expired()]
        for key in expired_keys:
            del self.tavily_cache[key]
        
        # Clean response cache
        expired_keys = [k for k, v in self.response_cache.items() if v.is_expired()]
        for key in expired_keys:
            del self.response_cache[key]


cache_manager = CacheManager()


# ============================================================================
# TOKEN ESTIMATION
# ============================================================================

def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars ≈ 1 token)"""
    if not text:
        return 0
    return len(text) // 4


def hash_messages(messages: List[Dict]) -> str:
    """Create a hash of message list for caching purposes"""
    import json
    text = json.dumps(messages, sort_keys=True)
    return hashlib.md5(text.encode()).hexdigest()


# ============================================================================
# CONTEXT OPTIMIZATION (PRIORITY-BASED)
# ============================================================================

def optimize_messages(messages: List[Dict]) -> List[Dict]:
    """
    Optimize messages using priority-based context budgeting.
    
    Priority order (highest → lowest):
    1. System prompt (SYSTEM_PROMPT_BUDGET)
    2. Current user message (CURRENT_MESSAGE_BUDGET)
    3. Reply context (REPLY_CONTEXT_BUDGET)
    4. Tavily search results (SEARCH_RESULTS_BUDGET)
    5. User memory/history (USER_HISTORY_BUDGET)
    6. Recent channel messages (CHANNEL_LOG_BUDGET)
    """
    optimized = []
    system_tokens_used = 0
    reply_context_tokens = 0
    search_tokens = 0
    history_tokens = 0
    log_tokens = 0
    
    # Phase 1: Collect highest-priority items
    system_prompt = None
    current_user_message = None
    reply_context = None
    search_results = []
    user_history = []
    channel_logs = []
    
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if role == "system":
            if "current user message" in content.lower() or "replying to" in content.lower():
                reply_context = msg
            elif "web search" in content.lower():
                search_results.append(msg)
            elif "chat log" in content.lower() or "recent server" in content.lower():
                channel_logs.append(msg)
            else:
                # First system message is the system prompt
                if system_prompt is None:
                    system_prompt = msg
                else:
                    user_history.append(msg)
        elif role == "user":
            if msg == messages[-1]:  # Last message is current user message
                current_user_message = msg
            else:
                user_history.append(msg)
        elif role == "assistant":
            user_history.append(msg)
    
    # Phase 2: Add messages respecting token budgets (priority order)
    if system_prompt:
        system_tokens = estimate_tokens(system_prompt.get("content", ""))
        if system_tokens <= Config.SYSTEM_PROMPT_BUDGET:
            optimized.append(system_prompt)
            system_tokens_used = system_tokens
        else:
            # Trim system prompt if necessary
            content = system_prompt.get("content", "")
            trimmed = content[:Config.SYSTEM_PROMPT_BUDGET * 4]  # Reverse token estimation
            optimized.append({"role": "system", "content": trimmed})
            system_tokens_used = Config.SYSTEM_PROMPT_BUDGET
    
    if current_user_message:
        msg_tokens = estimate_tokens(current_user_message.get("content", ""))
        if msg_tokens <= Config.CURRENT_MESSAGE_BUDGET:
            optimized.append(current_user_message)
        else:
            # Never trim the user's current message, but log warning
            log_message(f"[WARNING] Current user message exceeds budget ({msg_tokens} > {Config.CURRENT_MESSAGE_BUDGET} tokens)")
            optimized.append(current_user_message)
    
    # Reply context
    if reply_context:
        msg_tokens = estimate_tokens(reply_context.get("content", ""))
        if msg_tokens <= Config.REPLY_CONTEXT_BUDGET:
            optimized.append(reply_context)
            reply_context_tokens = msg_tokens
        else:
            content = reply_context.get("content", "")
            trimmed = content[:Config.REPLY_CONTEXT_BUDGET * 4]
            optimized.append({"role": "system", "content": trimmed})
            reply_context_tokens = Config.REPLY_CONTEXT_BUDGET
    
    # Search results
    search_budget_remaining = Config.SEARCH_RESULTS_BUDGET
    for msg in search_results:
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if msg_tokens <= search_budget_remaining:
            optimized.append(msg)
            search_tokens += msg_tokens
            search_budget_remaining -= msg_tokens
        else:
            # Trim search results to fit
            content = msg.get("content", "")
            trimmed = content[:search_budget_remaining * 4]
            optimized.append({"role": "system", "content": trimmed})
            search_tokens += search_budget_remaining
            break
    
    # User history (conversation turns)
    history_budget_remaining = Config.USER_HISTORY_BUDGET
    for msg in reversed(user_history):  # Work backwards to preserve recency
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if msg_tokens <= history_budget_remaining:
            optimized.insert(len(optimized) - 1, msg)  # Insert before current message
            history_tokens += msg_tokens
            history_budget_remaining -= msg_tokens
    
    # Channel logs
    log_budget_remaining = Config.CHANNEL_LOG_BUDGET
    for msg in channel_logs:
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if msg_tokens <= log_budget_remaining:
            optimized.insert(len(optimized) - 1, msg)  # Insert before current message
            log_tokens += msg_tokens
            log_budget_remaining -= msg_tokens
    
    total_tokens = system_tokens_used + estimate_tokens(current_user_message.get("content", "") if current_user_message else "") + reply_context_tokens + search_tokens + history_tokens + log_tokens
    log_message(f"[TOKENS] Prompt optimized: {total_tokens}/{Config.MAX_PROMPT_TOKENS} tokens (System={system_tokens_used}, Reply={reply_context_tokens}, Search={search_tokens}, History={history_tokens}, Log={log_tokens})")
    
    return optimized


# ============================================================================
# ERROR HANDLING & RETRY LOGIC
# ============================================================================

def is_transient_error(error_str: str) -> bool:
    """Check if an error is transient (retry-worthy)"""
    error_lower = error_str.lower()
    return any(x in error_lower for x in [
        "timeout",
        "connection reset",
        "connection error",
        "502",
        "503",
        "gateway",
        "temporarily unavailable",
        "try again",
    ])


def is_availability_issue(error_str: str) -> bool:
    """Check if an error is an availability issue (cooldown-worthy)"""
    error_lower = error_str.lower()
    return any(x in error_lower for x in [
        "429",
        "rate limit",
        "quota",
        "token",
        "exceeded",
        "too many requests",
    ])


def parse_retry_after(error_str: str) -> int:
    """Extract retry-after time from error (returns minutes)"""
    match = re.search(r"retry[- ]after[:\s]+(\d+)\s*s(?:econds?)?", error_str, re.IGNORECASE)
    if match:
        seconds = int(match.group(1))
        return max(1, seconds // 60)  # Convert to minutes, min 1
    return Config.DEFAULT_COOLDOWN_MINUTES


# ============================================================================
# MODEL CALLING
# ============================================================================

async def _call_model(model_name: str, client: OpenAI, messages: List[Dict]) -> Tuple[Optional[str], Optional[str]]:
    """
    Call a specific model. Returns (response, error).
    """
    try:
        start_time = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=Config.MAX_RESPONSE_TOKENS,
        )
        elapsed = time.time() - start_time
        
        content = response.choices[0].message.content
        if len(content) > Config.DISCORD_MAX_LENGTH:
            content = content[:Config.DISCORD_MAX_LENGTH - 3] + "..."
        
        stats_tracker.get_stats(model_name).record_success(elapsed)
        return content, None
    except Exception as e:
        error_str = str(e)
        stats_tracker.get_stats(model_name).record_failure()
        return None, error_str


# ============================================================================
# MAIN GENERATION FUNCTIONS
# ============================================================================

async def generate(messages: List[Dict]) -> str:
    """
    Generate text response with three-tier fallback and intelligent caching.
    
    Fallback order:
    1. GROQ_TEXT_MODEL (primary)
    2. GROQ_SECOND_TEXT_MODEL (secondary)
    3. OpenRouter (final fallback)
    """
    # Clear expired cache entries
    cache_manager.clear_expired()
    
    # Check response cache
    msg_hash = hash_messages(messages)
    cached_response = cache_manager.get_cached_response(msg_hash)
    if cached_response:
        return cached_response
    
    # Optimize messages for token efficiency
    optimized_messages = optimize_messages(messages)
    
    # Try each model in fallback order
    models_to_try = [
        (Config.GROQ_TEXT_MODEL, groq_client, "PRIMARY", stats_tracker),
        (Config.GROQ_SECOND_TEXT_MODEL, groq_client, "SECONDARY", stats_tracker),
        (Config.OPENROUTER_MODEL, openrouter_client, "TERTIARY", stats_tracker),
    ]
    
    for model_name, client, tier, _ in models_to_try:
        if not model_name:
            continue
        
        # Check if model is on cooldown
        if not cooldown_manager.is_available(model_name):
            cooldown_until = cooldown_manager.get_cooldown_until(model_name)
            log_message(f"[{tier}] {model_name} on cooldown until {cooldown_until.strftime('%H:%M:%S')}, skipping")
            continue
        
        log_message(f"[{tier}] Attempting {model_name}")
        
        # Try the model with retry logic for transient errors
        for attempt in range(1 + Config.MAX_RETRIES_PER_MODEL):
            response, error = await _call_model(model_name, client, optimized_messages)
            
            if response:
                log_message(f"[{tier}] {model_name} succeeded")
                cache_manager.cache_response(msg_hash, response)
                return response
            
            if error:
                error_lower = error.lower()
                
                # Check for transient errors (retry)
                if is_transient_error(error) and attempt < Config.MAX_RETRIES_PER_MODEL:
                    log_message(f"[RETRY] {model_name} transient error, retrying in {Config.RETRY_DELAY_SECONDS}s: {error[:80]}")
                    stats_tracker.get_stats(model_name).record_retry()
                    await asyncio.sleep(Config.RETRY_DELAY_SECONDS)
                    continue
                
                # Check for availability issues (cooldown)
                if is_availability_issue(error):
                    log_message(f"[RATE_LIMIT] {model_name}: {error[:80]}")
                    stats_tracker.get_stats(model_name).record_rate_limit()
                    cooldown_minutes = parse_retry_after(error)
                    cooldown_manager.set_cooldown(model_name, cooldown_minutes)
                else:
                    log_message(f"[ERROR] {model_name}: {error[:80]}")
                
                # Move to next model
                break
    
    # All models failed
    log_message("[CRITICAL] All models exhausted, returning fallback message")
    fallback = "ugh, all my brain models just glitched at once. try again in a bit?"
    cache_manager.cache_response(msg_hash, fallback)
    return fallback


async def generate_vision(messages: List[Dict], image_url: str) -> str:
    """
    Generate response for image input with fallback support.
    """
    # Extract user's text input
    user_text = messages[-1]["content"]
    
    vision_messages = [
        {
            "role": "system",
            "content": "You are an image analyzer. Describe what you see objectively and concisely, focusing on elements relevant to the user's message. No personality or conversational elements."
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"The user says: '{user_text}'. Describe this image in detail."
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url}
                }
            ]
        }
    ]
    
    try:
        log_message(f"[VISION] Analyzing image with {Config.GROQ_VISION_MODEL}")
        response = groq_client.chat.completions.create(
            model=Config.GROQ_VISION_MODEL,
            messages=vision_messages,
            max_tokens=Config.VISION_MAX_TOKENS,
        )
        image_analysis = response.choices[0].message.content
        log_message("[VISION] Image analysis complete")
    except Exception as e:
        log_message(f"[VISION] Failed: {e}")
        return await generate(messages)
    
    # Generate response with image context
    text_messages = messages.copy()
    text_messages.insert(-1, {
        "role": "system",
        "content": f"The user sent an image. Here's what's in it: {image_analysis}. React naturally—don't describe or explain, just respond."
    })
    
    return await generate(text_messages)


# ============================================================================
# UTILITIES
# ============================================================================

def log_message(msg: str):
    """Log a message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[AI {timestamp}] {msg}")


def print_statistics():
    """Print all model statistics"""
    stats_tracker.print_stats()


# ============================================================================
# TAVILY INTEGRATION
# ============================================================================

async def cache_tavily_result(query: str, result: str):
    """Cache a Tavily search result (called from search.py)"""
    cache_manager.cache_tavily_result(query, result)


def get_cached_tavily_result(query: str) -> Optional[str]:
    """Get a cached Tavily search result (called from search.py)"""
    return cache_manager.get_tavily_result(query)


# Required for async operations
import asyncio