import os
import requests
from dotenv import load_dotenv

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
        print("Tavily API key not found, skipping search")
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
        
        # Extract the most relevant information
        summary_parts = []
        
        # Add the direct answer if available
        if data.get("answer"):
            summary_parts.append(f"Direct answer: {data['answer']}")
        
        # Add top results
        if data.get("results"):
            for i, result in enumerate(data["results"][:max_results], 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", "")
                
                # Truncate content if too long
                if len(content) > 200:
                    content = content[:200] + "..."
                
                summary_parts.append(f"{i}. {title}: {content}")
        
        if summary_parts:
            return "\n".join(summary_parts)
        else:
            print("No useful search results found")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Tavily search request failed: {e}")
        return None
    except Exception as e:
        print(f"Tavily search error: {e}")
        return None

def search_and_summarize(query):
    """
    Determine if search is needed, perform it, and return summarized results.
    Returns None if search is not needed or fails.
    """
    if not needs_search(query):
        return None
    
    print(f"[SEARCH] Performing web search for: {query[:50]}...")
    results = perform_search(query)
    
    if results:
        print(f"[SEARCH] Search successful, results length: {len(results)}")
        return f"Web search results for '{query}':\n{results}"
    else:
        print("[SEARCH] Search failed or returned no results")
        return None
