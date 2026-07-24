"""
Improved search pipeline - Returns structured knowledge instead of formatted text.

Flow:
1. Check if Jenny already knows it (KnowledgeManager)
2. Decide if search is needed
3. Query Tavily
4. Summarize results
5. Store as knowledge
6. Return structured data
"""

import os
import re
import requests
from typing import Optional, Dict
from datetime import datetime
from dotenv import load_dotenv
from knowledge import knowledge_manager, KnowledgeEntry

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# ============================================================================
# SEARCH DECISION LOGIC
# ============================================================================

# Things that strongly indicate a search is needed
SEARCH_REQUIRED = [
    # Time-sensitive topics
    "news", "latest", "recent", "current", "today", "this week", "this month",
    "breaking", "update", "new", "released", "announced", "just happened",
    
    # Current information that changes
    "price", "cost", "how much", "stock", "market", "crypto", "bitcoin", "ethereum",
    "weather", "forecast", "temperature",
    
    # Specific release/launch dates
    "release date", "launch", "when did", "when was", "when is", "schedule",
    "coming soon", "upcoming",
    
    # Fact-checking
    "is it true", "fact check", "verify", "is that real", "did that happen",
]

# Things that might need search (heuristic-based)
SEARCH_MAYBE = [
    # Documentation and technical questions
    "documentation", "docs", "api", "tutorial", "guide", 
    # Installation/setup (but not generic "how to")
    "install", "setup", "config", "configuration",
    # Technical details
    "syntax", "example", "code", "github",
    # Person/location/thing lookups (but these are vague - should be with proper noun)
    "who is", "where is", 
    # Specific factual questions
    "review", "rating", "specs", "specifications", "features", "requirements",
]

# Things that should NOT search (casual conversation)
SKIP_SEARCH = [
    "how are you", "how's it going", "what's up", "how do you feel",
    "how's your day", "how have you been",
    "good morning", "good night", "good evening", "hello", "hi", "hey",
    "thanks", "thank you", "appreciate", "cool", "nice", "awesome",
]

# Proper nouns (things Jenny might not know about)
SEARCH_PROPER_NOUNS = [
    # Minecraft mods
    "create mod", "create", "applied energistics", "ae2", "refined storage",
    "thermal expansion", "ender io", "ic2", "buildcraft", "tinkers construct",
    "decayedcraft", "modpacks", "ftb", "omnifactory",
    # Specific games
    "baldur's gate 3", "starfield", "helldivers", "palworld",
    # Specific people
    "elon musk", "mark zuckerberg", "sam altman", "tesla", "meta", "openai",
    # Specific events/companies
    "nvidia", "amd", "intel", "apple", "microsoft", "google",
    # Specific products
    "iphone", "ipad", "macbook", "playstation", "xbox", "switch",
]


def _is_proper_noun_query(query: str) -> bool:
    """Check if query contains proper nouns Jenny might not know"""
    query_lower = query.lower()
    return any(noun.lower() in query_lower for noun in SEARCH_PROPER_NOUNS)


def _extract_topic(query: str) -> str:
    """Extract the main topic from a query"""
    # Remove common prefixes
    for prefix in ["do you know", "do you", "are you", "have you", "can you", 
                   "what is", "what's", "who is", "who's", "where is", "where's",
                   "tell me about", "explain", "help me with"]:
        if query.lower().startswith(prefix):
            topic = query[len(prefix):].strip()
            return topic
    
    # Try to find the first proper noun or key term
    words = query.split()
    for word in words:
        if word[0].isupper() and len(word) > 1:
            return word
    
    return query


def should_search(query: str) -> tuple[bool, str]:
    """
    Decide if a search is needed.
    
    Returns: (should_search: bool, reason: str)
    """
    query_lower = query.lower()
    
    # Skip casual conversation
    for pattern in SKIP_SEARCH:
        if pattern in query_lower:
            return False, f"casual conversation: '{pattern}'"
    
    # Check for explicit search requirement
    for indicator in SEARCH_REQUIRED:
        if indicator in query_lower:
            return True, f"search required keyword: '{indicator}'"
    
    # Check if it's asking about a proper noun
    if _is_proper_noun_query(query):
        return True, "query contains proper noun"
    
    # Check for maybe-search patterns
    for indicator in SEARCH_MAYBE:
        if indicator in query_lower:
            return True, f"maybe-search keyword: '{indicator}'"
    
    return False, "no search indicators"


# ============================================================================
# TAVILY INTEGRATION
# ============================================================================

def _call_tavily(query: str, max_results: int = 3) -> Optional[Dict]:
    """
    Call Tavily API and return raw response.
    
    Returns None if API fails.
    """
    if not TAVILY_API_KEY:
        print("[SEARCH] Tavily API key not configured")
        return None
    
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"[SEARCH] Tavily API error: {e}")
        return None
    except Exception as e:
        print(f"[SEARCH] Unexpected error calling Tavily: {e}")
        return None


def _summarize_tavily_response(query: str, data: Dict) -> tuple[str, list[str], float]:
    """
    Summarize Tavily response into concise knowledge.
    
    Returns: (summary: str, keywords: List[str], confidence: float)
    """
    summary_parts = []
    keywords = set([query.lower()])
    confidence = 0.85
    
    # Extract answer if available (highest quality)
    if data.get("answer"):
        answer = data['answer'].strip()
        # Trim to 150 chars to keep it concise
        if len(answer) > 150:
            # Try to cut at a sentence boundary
            sentences = answer.split('.')
            answer = sentences[0] + '.' if sentences[0] else answer[:150]
        summary_parts.append(answer)
        confidence = 0.95  # Direct answers are more confident
    
    # Add concise snippets from top results
    if data.get("results"):
        for result in data["results"][:2]:  # Only top 2
            title = result.get("title", "").strip()
            content = result.get("content", "").strip()
            
            if title:
                keywords.add(title.lower())
            
            # Extract first sentence or 100 chars max
            if content:
                sentences = content.split('.')
                snippet = sentences[0][:100] if sentences[0] else content[:100]
                if snippet and snippet not in summary_parts:
                    summary_parts.append(snippet)
                
                keywords.update(word.lower() for word in title.split() if len(word) > 3)
    
    # Join into a concise summary
    summary = " ".join(summary_parts)
    summary = summary[:250]  # Hard cap at 250 chars
    
    if not summary:
        summary = f"Information about {query} from web search."
    
    return summary, list(keywords), confidence


# ============================================================================
# PUBLIC API
# ============================================================================

def search_and_learn(query: str) -> Optional[KnowledgeEntry]:
    """
    Main search pipeline:
    1. Check if Jenny already knows it (within 2 hour cache)
    2. Decide if search is needed
    3. Search if needed
    4. Store as knowledge
    5. Return knowledge entry
    
    Returns:
        KnowledgeEntry if found (cached or searched)
        None if search was not needed or failed
    """
    topic = _extract_topic(query)
    
    # Step 1: Check if already known (recently learned)
    existing = knowledge_manager.recall(topic)
    if existing:
        print(f"[SEARCH] Already know about '{topic}' (cached from {existing.source})")
        return existing
    
    # Step 2: Decide if search needed
    should_search_result, reason = should_search(query)
    if not should_search_result:
        print(f"[SEARCH] Skip searching '{query}' - {reason}")
        return None
    
    # Step 3: Perform search
    print(f"[SEARCH] Searching for '{query}' - {reason}")
    tavily_data = _call_tavily(query)
    if not tavily_data:
        print(f"[SEARCH] Tavily search failed for '{query}'")
        return None
    
    # Step 4: Summarize and store
    summary, keywords, confidence = _summarize_tavily_response(query, tavily_data)
    
    knowledge_entry = knowledge_manager.learn(
        topic=topic,
        summary=summary,
        keywords=keywords,
        source="tavily",
        confidence=confidence,
        ttl_minutes=120,  # Remember for 2 hours
    )
    
    print(f"[SEARCH] Learned: {knowledge_entry}")
    return knowledge_entry


def get_knowledge_context(query: str) -> Optional[str]:
    """
    Get knowledge context to inject into prompt.
    
    Returns a formatted knowledge string or None.
    """
    topic = _extract_topic(query)
    knowledge = knowledge_manager.recall(topic)
    
    if not knowledge:
        return None
    
    # Format as background knowledge (not as search results)
    return (
        f"Background knowledge (learned from {knowledge.source}): "
        f"{knowledge.summary}"
    )


# ============================================================================
# DEBUG UTILITIES
# ============================================================================

def print_knowledge_stats():
    """Print knowledge manager statistics"""
    knowledge_manager.print_stats()


def print_search_log(last_n: int = 20):
    """Print recent search activity"""
    knowledge_manager.print_access_log(last_n)
