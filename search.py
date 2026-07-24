import os
import requests
from dotenv import load_dotenv

# Import cache functions from ai module
try:
    from ai import get_cached_tavily_result, cache_tavily_result
except ImportError:
    # Fallback if ai module is not available yet
    def get_cached_tavily_result(query):
        return None
    
    async def cache_tavily_result(query, result):
        pass

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Keywords and patterns that indicate a need for web search
SEARCH_INDICATORS = [
    # Time-sensitive topics
    "news", "latest", "recent", "current", "yesterday", "this week", "this month",
    "breaking", "update", "new", "released", "announced",
    
    # Factual information that changes
    "price", "cost", "how much", "stock", "market", "crypto", "bitcoin", "ethereum",
    "weather", "forecast", "temperature",
    
    # Documentation and technical info
    "documentation", "docs", "api", "tutorial", "guide", "how to", "install", "setup",
    "config", "configuration", "syntax", "example",
    
    # People and current status
    "who is", "where is", "what happened", "did", "died", "alive", "age", "born",
    
    # Events and dates
    "when", "date", "release date", "launch", "schedule", "upcoming", "happening",
    
    # Facts and verification
    "is it true", "fact check", "verify", "real", "fake", "scam", "legit",
    
    # Product reviews and comparisons
    "review", "rating", "best", "vs", "versus", "compare", "better", "recommendation",
    
    # Technical specifications
    "specs", "specifications", "features", "requirements", "compatible", "support",
]

# Patterns that should NOT trigger search (casual conversation)
SKIP_PATTERNS = [
    "how are you", "how's it going", "what's up", "how do you feel",
    "good morning", "good night", "hello", "hi", "hey",
]

def needs_search(query):
    """
    Determine if a query requires web search based on keywords and patterns.
    Returns True if the query likely needs current/external information.
    """
    query_lower = query.lower()
    
    # First check for casual conversation patterns to skip
    for skip_pattern in SKIP_PATTERNS:
        if skip_pattern in query_lower:
            return False
    
    # Check for search indicators
    for indicator in SEARCH_INDICATORS:
        if indicator in query_lower:
            return True
    
    # Check for question words that often need current info
    question_words = ["what", "when", "where", "who", "how", "why"]
    if any(word in query_lower.split() for word in question_words):
        # Additional heuristics for questions
        if any(phrase in query_lower for phrase in ["current", "latest", "now", "today"]):
            return True
    
    return False

def perform_search(query, max_results=3):
    """
    Perform a web search using Tavily API.
    Returns a summarized string of search results or None if search fails.
    """
    if not TAVILY_API_KEY:
        print("[SEARCH] Tavily API key not found, skipping search")
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
        
        data = response.json()
        
        # Extract the most relevant information (concise format)
        summary_parts = []
        
        # Add the direct answer if available
        if data.get("answer"):
            answer = data['answer']
            if len(answer) > 300:
                answer = answer[:300] + "..."
            summary_parts.append(f"Answer: {answer}")
        
        # Add top results (keep very concise)
        if data.get("results"):
            summary_parts.append("Results:")
            for i, result in enumerate(data["results"][:max_results], 1):
                title = result.get("title", "No title")
                content = result.get("content", "")
                
                # Trim content significantly
                if len(content) > 150:
                    content = content[:150] + "..."
                
                summary_parts.append(f"{i}. {title}: {content}")
        
        if summary_parts:
            result = "\n".join(summary_parts)
            print(f"[SEARCH] Search successful, result length: {len(result)} chars")
            return result
        else:
            print("[SEARCH] No useful search results found")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"[SEARCH] Tavily request failed: {e}")
        return None
    except Exception as e:
        print(f"[SEARCH] Tavily error: {e}")
        return None

def search_and_summarize(query):
    """
    Determine if search is needed, check cache, perform it if needed, and return results.
    Returns None if search is not needed or fails.
    Integrates with AI module's Tavily cache.
    """
    if not needs_search(query):
        return None
    
    print(f"[SEARCH] Query needs search: {query[:50]}...")
    
    # Check AI cache first
    cached_result = get_cached_tavily_result(query)
    if cached_result:
        print(f"[SEARCH] Using cached result")
        return f"Web search results for '{query}':\n{cached_result}"
    
    # Perform actual search
    print(f"[SEARCH] Performing web search...")
    results = perform_search(query)
    
    if results:
        # Cache the result
        import asyncio
        try:
            # Try to cache asynchronously if in async context
            loop = asyncio.get_event_loop()
            loop.create_task(cache_tavily_result(query, results))
        except RuntimeError:
            # Fallback if not in async context
            pass
        
        return f"Web search results for '{query}':\n{results}"
    else:
        print("[SEARCH] Search failed or returned no results")
        return None
