"""
LRU Cache for optimized mapping lookups.

This module provides thread-safe caching for frequently accessed mappings,
reducing database load and improving desanitization performance.

Story 5.3: Optimized Mapping Lookups
"""

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Any, Tuple


@dataclass
class CacheMetrics:
    """Metrics for cache performance monitoring."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0
    
    @property
    def total_requests(self) -> int:
        """Total number of cache requests."""
        return self.hits + self.misses
    
    def reset(self) -> None:
        """Reset all metrics to zero."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.invalidations = 0


@dataclass
class CacheEntry:
    """Individual cache entry with optional TTL."""
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    
    def is_expired(self, ttl_seconds: Optional[int]) -> bool:
        """Check if entry has expired based on TTL."""
        if ttl_seconds is None:
            return False
        return (datetime.now() - self.created_at).total_seconds() > ttl_seconds


class MappingLRUCache:
    """
    Thread-safe LRU (Least Recently Used) cache for mapping lookups.
    
    Features:
    - LRU eviction policy when cache is full
    - Optional TTL (time-to-live) for entries
    - Thread-safe operations using RLock
    - Comprehensive metrics tracking
    - Cache invalidation support
    
    Usage:
        cache = MappingLRUCache(max_size=10000)
        
        # Cache lookup
        key = ("Customers", "Email", "user_abc123@example.com")
        value = cache.get(key)
        if value is None:
            # Cache miss - fetch from database
            value = fetch_from_db(key)
            cache.set(key, value)
        
        # Monitor performance
        metrics = cache.get_metrics()
        print(f"Hit rate: {metrics.hit_rate:.2f}%")
    
    Attributes:
        max_size: Maximum number of entries (default: 10000)
        ttl_seconds: Optional time-to-live for entries (default: None = no expiration)
    """
    
    def __init__(
        self,
        max_size: int = 10000,
        ttl_seconds: Optional[int] = None
    ):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of cache entries (default: 10000)
            ttl_seconds: Optional TTL in seconds (None = no expiration)
            
        Raises:
            ValueError: If max_size <= 0
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        
        # OrderedDict for LRU ordering (most recent = end)
        self._cache: OrderedDict[Tuple, CacheEntry] = OrderedDict()
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Metrics tracking
        self._metrics = CacheMetrics()
    
    def get(self, key: Tuple[str, str, str]) -> Optional[str]:
        """
        Retrieve value from cache.
        
        Args:
            key: Cache key tuple (table_name, column_name, masked_value)
            
        Returns:
            Cached original value or None if not found/expired
            
        Notes:
            - Updates LRU order on hit (moves to end)
            - Increments hit/miss metrics
            - Removes expired entries on access
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._metrics.misses += 1
                return None
            
            # Check expiration
            if entry.is_expired(self.ttl_seconds):
                # Remove expired entry
                del self._cache[key]
                self._metrics.misses += 1
                self._metrics.evictions += 1
                return None
            
            # Cache hit - update LRU order (move to end)
            self._cache.move_to_end(key)
            entry.last_accessed = datetime.now()
            entry.access_count += 1
            self._metrics.hits += 1
            
            return entry.value
    
    def set(self, key: Tuple[str, str, str], value: str) -> None:
        """
        Store value in cache.
        
        Args:
            key: Cache key tuple (table_name, column_name, masked_value)
            value: Original value to cache
            
        Notes:
            - Evicts LRU entry if cache is full
            - Updates existing entry if key already cached
        """
        with self._lock:
            # Update existing entry
            if key in self._cache:
                entry = self._cache[key]
                entry.value = value
                entry.last_accessed = datetime.now()
                entry.access_count += 1
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return
            
            # Evict LRU entry if cache is full
            if len(self._cache) >= self.max_size:
                # Remove first item (least recently used)
                self._cache.popitem(last=False)
                self._metrics.evictions += 1
            
            # Add new entry
            self._cache[key] = CacheEntry(value=value)
    
    def invalidate(self, key: Optional[Tuple[str, str, str]] = None) -> int:
        """
        Invalidate cache entries.
        
        Args:
            key: Specific key to invalidate (None = clear all)
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            if key is None:
                # Clear all entries
                count = len(self._cache)
                self._cache.clear()
                self._metrics.invalidations += count
                return count
            
            # Remove specific key
            if key in self._cache:
                del self._cache[key]
                self._metrics.invalidations += 1
                return 1
            
            return 0
    
    def invalidate_table(self, table_name: str) -> int:
        """
        Invalidate all cache entries for a specific table.
        
        Args:
            table_name: Name of table to invalidate
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            # Find all keys for this table
            keys_to_remove = [
                key for key in self._cache.keys()
                if key[0] == table_name
            ]
            
            # Remove them
            for key in keys_to_remove:
                del self._cache[key]
            
            count = len(keys_to_remove)
            self._metrics.invalidations += count
            return count
    
    def invalidate_column(self, table_name: str, column_name: str) -> int:
        """
        Invalidate all cache entries for a specific column.
        
        Args:
            table_name: Name of table
            column_name: Name of column
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            # Find all keys for this table.column
            keys_to_remove = [
                key for key in self._cache.keys()
                if key[0] == table_name and key[1] == column_name
            ]
            
            # Remove them
            for key in keys_to_remove:
                del self._cache[key]
            
            count = len(keys_to_remove)
            self._metrics.invalidations += count
            return count
    
    def get_metrics(self) -> CacheMetrics:
        """
        Get current cache performance metrics.
        
        Returns:
            CacheMetrics object with hit rate, evictions, etc.
        """
        with self._lock:
            return CacheMetrics(
                hits=self._metrics.hits,
                misses=self._metrics.misses,
                evictions=self._metrics.evictions,
                invalidations=self._metrics.invalidations
            )
    
    def reset_metrics(self) -> None:
        """Reset all performance metrics to zero."""
        with self._lock:
            self._metrics.reset()
    
    def get_size(self) -> int:
        """Get current number of cached entries."""
        with self._lock:
            return len(self._cache)
    
    def get_capacity(self) -> float:
        """
        Get cache capacity utilization as percentage.
        
        Returns:
            Percentage of cache filled (0-100)
        """
        with self._lock:
            return (len(self._cache) / self.max_size) * 100
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries from cache.
        
        Returns:
            Number of entries removed
        """
        if self.ttl_seconds is None:
            return 0
        
        with self._lock:
            keys_to_remove = [
                key for key, entry in self._cache.items()
                if entry.is_expired(self.ttl_seconds)
            ]
            
            for key in keys_to_remove:
                del self._cache[key]
            
            count = len(keys_to_remove)
            self._metrics.evictions += count
            return count
    
    def get_stats(self) -> dict:
        """
        Get comprehensive cache statistics.
        
        Returns:
            Dictionary with detailed statistics
        """
        with self._lock:
            metrics = self.get_metrics()
            return {
                "max_size": self.max_size,
                "current_size": len(self._cache),
                "capacity_percent": self.get_capacity(),
                "ttl_seconds": self.ttl_seconds,
                "metrics": {
                    "total_requests": metrics.total_requests,
                    "hits": metrics.hits,
                    "misses": metrics.misses,
                    "hit_rate_percent": metrics.hit_rate,
                    "evictions": metrics.evictions,
                    "invalidations": metrics.invalidations
                }
            }
    
    def __repr__(self) -> str:
        """String representation of cache state."""
        metrics = self.get_metrics()
        return (
            f"MappingLRUCache(size={self.get_size()}/{self.max_size}, "
            f"hit_rate={metrics.hit_rate:.1f}%, "
            f"evictions={metrics.evictions})"
        )
    
    def __len__(self) -> int:
        """Support len() builtin."""
        return self.get_size()
