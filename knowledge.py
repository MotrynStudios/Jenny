"""
Knowledge Manager - Handles temporary learned knowledge.

Separate from conversation history, user memories, and database.
Purpose: Store what Jenny has recently learned so she can reference it naturally.
"""

import time
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict


@dataclass
class KnowledgeEntry:
    """A single piece of knowledge Jenny has learned"""
    topic: str                      # Normalized topic name
    summary: str                    # Concise 1-3 sentence summary
    keywords: List[str]             # Related keywords for matching
    source: str                     # Where this came from (e.g., "tavily", "context")
    confidence: float               # 0.0-1.0 how confident Jenny should be
    created_at: float               # Timestamp when learned
    expires_at: float               # When this knowledge expires
    
    def is_expired(self) -> bool:
        """Check if this knowledge has expired"""
        return time.time() >= self.expires_at
    
    def time_remaining(self) -> float:
        """Seconds until expiration"""
        return max(0, self.expires_at - time.time())
    
    def __str__(self) -> str:
        return f"{self.topic}: {self.summary[:50]}... (confidence: {self.confidence:.1%})"


class KnowledgeManager:
    """
    Manages Jenny's temporary learned knowledge.
    Separate cache from search results - more semantic than text-based caching.
    """
    
    def __init__(self, default_ttl_minutes: int = 120):
        self.knowledge: Dict[str, KnowledgeEntry] = {}
        self.default_ttl_minutes = default_ttl_minutes
        self.access_log: List[tuple] = []  # For debugging
    
    def _normalize_topic(self, topic: str) -> str:
        """Normalize topic name for consistent lookup"""
        return topic.lower().strip()
    
    def _hash_keywords(self, keywords: List[str]) -> set:
        """Create searchable keyword set"""
        return {k.lower().strip() for k in keywords if k}
    
    def learn(
        self,
        topic: str,
        summary: str,
        keywords: List[str],
        source: str = "unknown",
        confidence: float = 0.9,
        ttl_minutes: Optional[int] = None,
    ) -> KnowledgeEntry:
        """
        Learn a new piece of knowledge.
        
        Args:
            topic: What Jenny learned about (e.g., "Create Mod")
            summary: Concise 1-3 sentence explanation
            keywords: Related terms for fuzzy matching
            source: Where this came from (e.g., "tavily", "user_context")
            confidence: How certain Jenny should be (0.0-1.0)
            ttl_minutes: How long to remember this (default: 120 min)
        
        Returns:
            The created KnowledgeEntry
        """
        ttl = ttl_minutes or self.default_ttl_minutes
        normalized_topic = self._normalize_topic(topic)
        
        entry = KnowledgeEntry(
            topic=normalized_topic,
            summary=summary,
            keywords=self._hash_keywords(keywords),
            source=source,
            confidence=confidence,
            created_at=time.time(),
            expires_at=time.time() + (ttl * 60),
        )
        
        self.knowledge[normalized_topic] = entry
        self._log_access("LEARN", normalized_topic, f"from {source}")
        
        return entry
    
    def recall(self, topic: str) -> Optional[KnowledgeEntry]:
        """
        Recall knowledge about a topic.
        
        Returns None if unknown or expired.
        """
        normalized_topic = self._normalize_topic(topic)
        
        if normalized_topic not in self.knowledge:
            self._log_access("MISS", normalized_topic, "unknown")
            return None
        
        entry = self.knowledge[normalized_topic]
        
        if entry.is_expired():
            del self.knowledge[normalized_topic]
            self._log_access("EXPIRED", normalized_topic, f"after {entry.time_remaining():.1f}s")
            return None
        
        self._log_access("HIT", normalized_topic, f"{entry.source} (confidence: {entry.confidence:.1%})")
        return entry
    
    def search_by_keywords(self, query_keywords: List[str]) -> List[KnowledgeEntry]:
        """
        Search for knowledge using keywords.
        Useful for fuzzy matching related topics.
        
        Example:
            search_by_keywords(["minecraft", "mod", "automation"])
            might return: Create Mod, Applied Energistics, etc.
        """
        self._cleanup_expired()
        
        query_set = self._hash_keywords(query_keywords)
        matches = []
        
        for entry in self.knowledge.values():
            if entry.is_expired():
                continue
            
            # Score based on keyword overlap
            overlap = len(query_set & entry.keywords)
            if overlap > 0:
                matches.append((overlap, entry))
        
        # Sort by score (descending)
        matches.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in matches]
    
    def forget(self, topic: str) -> bool:
        """Explicitly forget knowledge about a topic"""
        normalized_topic = self._normalize_topic(topic)
        if normalized_topic in self.knowledge:
            del self.knowledge[normalized_topic]
            self._log_access("FORGET", normalized_topic, "explicit")
            return True
        return False
    
    def clear_expired(self):
        """Remove all expired knowledge entries"""
        expired_topics = [
            topic for topic, entry in self.knowledge.items()
            if entry.is_expired()
        ]
        for topic in expired_topics:
            del self.knowledge[topic]
        
        if expired_topics:
            self._log_access("CLEANUP", f"{len(expired_topics)} entries", "expired")
    
    def _cleanup_expired(self):
        """Internal: clean up expired entries"""
        to_remove = [
            topic for topic, entry in self.knowledge.items()
            if entry.is_expired()
        ]
        for topic in to_remove:
            del self.knowledge[topic]
    
    def _log_access(self, action: str, topic: str, details: str):
        """Internal: log access for debugging"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.access_log.append((timestamp, action, topic, details))
        # Keep log size bounded
        if len(self.access_log) > 1000:
            self.access_log = self.access_log[-500:]
    
    def get_all(self) -> Dict[str, KnowledgeEntry]:
        """Get all active knowledge entries"""
        self._cleanup_expired()
        return dict(self.knowledge)
    
    def print_stats(self):
        """Print knowledge statistics for debugging"""
        self._cleanup_expired()
        print(f"\n[KNOWLEDGE] ===== KNOWLEDGE MANAGER STATS =====")
        print(f"[KNOWLEDGE] Active entries: {len(self.knowledge)}")
        for topic, entry in self.knowledge.items():
            print(f"[KNOWLEDGE]   - {entry}")
        print(f"[KNOWLEDGE] ==========================================\n")
    
    def print_access_log(self, last_n: int = 20):
        """Print recent access log for debugging"""
        print(f"\n[KNOWLEDGE] ===== RECENT ACCESS LOG (last {last_n}) =====")
        for timestamp, action, topic, details in self.access_log[-last_n:]:
            print(f"[KNOWLEDGE] {timestamp} [{action}] {topic}: {details}")
        print(f"[KNOWLEDGE] ======================================\n")


# Global knowledge manager instance
knowledge_manager = KnowledgeManager(default_ttl_minutes=120)
