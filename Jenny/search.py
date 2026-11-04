import os
from pathlib import Path
import asyncio
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
TAVILY_API_KEY_BACKUP = os.getenv("TAVILY_API_KEY_BACKUP")


async def perform_search(query, max_results=3):
    """
    Perform a web search using Tavily API with fallback to backup key.
    Returns a summarized string of search results, or None if search fails/unavailable.
    Runs the actual blocking HTTP call in a background thread so it never freezes
    the bot's event loop (heartbeats, other messages, etc keep working while this runs).
    """
    api_keys = [TAVILY_API_KEY, TAVILY_API_KEY_BACKUP]
    
    for i, api_key in enumerate(api_keys):
        if not api_key:
            print(f"Tavily API key {i+1} not found, skipping")
            continue
            
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
                "include_raw_content": False,
            }

            response = await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            summary_parts = []

            if data.get("answer"):
                summary_parts.append(f"Direct answer: {data['answer']}")

            if data.get("results"):
                for j, result in enumerate(data["results"][:max_results], 1):
                    title = result.get("title", "No title")
                    content = result.get("content", "")
                    if len(content) > 200:
                        content = content[:200] + "..."
                    source = result.get("url", "")
                    summary_parts.append(f"{j}. {title} ({source}): {content}" if source else f"{j}. {title}: {content}")

            if summary_parts:
                key_label = "primary" if i == 0 else "backup"
                print(f"[SEARCH] Using {key_label} Tavily key")
                return "\n".join(summary_parts)

            print(f"[SEARCH] No useful search results found with key {i+1}")
            continue  # Try next key

        except requests.exceptions.RequestException as e:
            print(f"[SEARCH] Tavily search failed with key {i+1}: {e}")
            continue  # Try next key
        except Exception as e:
            print(f"[SEARCH] Tavily error with key {i+1}: {e}")
            continue  # Try next key

    print("[SEARCH] All Tavily keys failed")
    return None
