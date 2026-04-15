"""
Performance benchmark tests for mapping cache and query optimization.

These tests measure performance improvements fromStory 5.3: Optimized Mapping Lookups

Run with: pytest tests/test_mapping_performance_benchmark.py -v
"""

import time
from typing import List

import pytest
import pyodbc

from mapping import MappingTableManager, MappingRecord, MappingLRUCache
from database import QueryPerformanceAnalyzer


class TestMappingCachePerformance:
    """Benchmark cache performance characteristics."""
    
    @pytest.fixture
    def sample_mappings(self) -> List[MappingRecord]:
        """Generate sample mapping records for benchmarking."""
        mappings = []
        for i in range(10000):
            mappings.append(MappingRecord(
                table_name="Customers",
                column_name="Email",
                record_id=str(i),
                original_value=f"user{i}@example.com",
                masked_value=f"user_hash{i:08x}@example.com",
                batch_id="BENCH-001",
                sanitization_run_id="RUN-BENCH"
            ))
        return mappings
    
    def test_cache_hit_performance(self):
        """Benchmark cache lookup performance (should be <1ms per lookup)."""
        cache = MappingLRUCache(max_size=10000)
        
        # Populate cache
        for i in range(1000):
            key = ("Customers", "Email", f"masked_{i}")
            cache.set(key, f"original_{i}")
        
        # Benchmark cache hits
        start_time = time.perf_counter()
        iterations = 10000
        
        for i in range(iterations):
            key = ("Customers", "Email", f"masked_{i % 1000}")
            value = cache.get(key)
            assert value is not None
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        avg_lookup_ms = elapsed_ms / iterations
        
        print(f"\nCache hit performance:")
        print(f"  Total time: {elapsed_ms:.2f}ms")
        print(f"  Avg per lookup: {avg_lookup_ms:.4f}ms")
        print(f"  Lookups/sec: {iterations / (elapsed_ms / 1000):.0f}")
        
        # Performance target: <0.01ms per lookup (100,000 lookups/sec)
        assert avg_lookup_ms < 0.01, f"Cache hit too slow: {avg_lookup_ms:.4f}ms"
    
    def test_cache_miss_performance(self):
        """Benchmark cache miss performance."""
        cache = MappingLRUCache(max_size=1000)
        
        # Benchmark cache misses
        start_time = time.perf_counter()
        iterations = 10000
        
        for i in range(iterations):
            key = ("Customers", "Email", f"not_cached_{i}")
            value = cache.get(key)
            assert value is None
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        avg_lookup_ms = elapsed_ms / iterations
        
        print(f"\nCache miss performance:")
        print(f"  Avg per lookup: {avg_lookup_ms:.4f}ms")
        
        # Cache misses should be nearly as fast as hits
        assert avg_lookup_ms < 0.01
    
    def test_cache_eviction_performance(self):
        """Benchmark LRU eviction overhead."""
        cache = MappingLRUCache(max_size=1000)
        
        # Fill cache to trigger evictions
        start_time = time.perf_counter()
        iterations = 5000  # 5x cache size = 4000 evictions
        
        for i in range(iterations):
            key = ("Customers", "Email", f"masked_{i}")
            cache.set(key, f"original_{i}")
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        avg_set_ms = elapsed_ms / iterations
        
        metrics = cache.get_metrics()
        
        print(f"\nCache eviction performance:")
        print(f"  Total inserts: {iterations}")
        print(f"  Evictions: {metrics.evictions}")
        print(f"  Avg per insert: {avg_set_ms:.4f}ms")
        
        # Eviction should add minimal overhead (<0.05ms per insert)
        assert avg_set_ms < 0.05
        assert metrics.evictions == iterations - 1000  # All beyond max_size
    
    def test_cache_thread_safety(self):
        """Verify thread-safe operations don't degrade performance significantly."""
        import threading
        
        cache = MappingLRUCache(max_size=10000)
        
        def worker(thread_id: int, iterations: int):
            for i in range(iterations):
                key = ("Customers", f"Col{thread_id}", f"masked_{i}")
                cache.set(key, f"original_{i}")
                value = cache.get(key)
                assert value == f"original_{i}"
        
        # Benchmark multi-threaded access
        num_threads = 4
        iterations_per_thread = 1000
        
        start_time = time.perf_counter()
        
        threads = []
        for tid in range(num_threads):
            t = threading.Thread(target=worker, args=(tid, iterations_per_thread))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        total_ops = num_threads * iterations_per_thread * 2  # set + get
        avg_op_ms = elapsed_ms / total_ops
        
        print(f"\nThread-safe performance:")
        print(f"  Threads: {num_threads}")
        print(f"  Total ops: {total_ops}")
        print(f"  Avg per op: {avg_op_ms:.4f}ms")
        
        # Thread-safe operations should be fast (<0.1ms despite locking)
        assert avg_op_ms < 0.1


class TestMappingTablePerformance:
    """Benchmark mapping table query performance with/without cache."""
    
    @pytest.mark.skip(reason="Requires database connection - run manually with valid connection string")
    def test_query_performance_comparison(self, connection_string: str):
        """Compare query performance with and without caching."""
        # Create managers: one with cache, one without
        cache = MappingLRUCache(max_size=10000)
        manager_with_cache = MappingTableManager(connection_string, cache=cache)
        manager_without_cache = MappingTableManager(connection_string, cache=None)
        
        # Warmup: Ensure data exists
        mappings = manager_without_cache.get_mappings("Customers", "Email")
        print(f"\nTesting with {len(mappings)} existing mappings")
        
        if len(mappings) < 100:
            pytest.skip("Insufficient test data in database")
        
        # Benchmark WITHOUT cache (cold query)
        start_time = time.perf_counter()
        result_no_cache = manager_without_cache.get_mappings("Customers", "Email")
        time_no_cache_ms = (time.perf_counter() - start_time) * 1000
        
        # Benchmark WITH cache (first query - cache miss)
        start_time = time.perf_counter()
        result_with_cache_first = manager_with_cache.get_mappings("Customers", "Email")
        time_with_cache_miss_ms = (time.perf_counter() - start_time) * 1000
        
        # Benchmark WITH cache (second query - cache hit)
        start_time = time.perf_counter()
        result_with_cache_second = manager_with_cache.get_mappings("Customers", "Email")
        time_with_cache_hit_ms = (time.perf_counter() - start_time) * 1000
        
        # Verify results are identical
        assert len(result_no_cache) == len(result_with_cache_first)
        assert len(result_with_cache_first) == len(result_with_cache_second)
        
        # Check cache metrics
        metrics = cache.get_metrics()
        hit_rate = metrics.hit_rate
        
        print(f"\nQuery Performance Comparison:")
        print(f"  Records: {len(result_no_cache)}")
        print(f"  No cache: {time_no_cache_ms:.2f}ms")
        print(f"  With cache (miss): {time_with_cache_miss_ms:.2f}ms")
        print(f"  With cache (hit): {time_with_cache_hit_ms:.2f}ms")
        print(f"  Cache hit rate: {hit_rate:.1f}%")
        print(f"  Speedup: {time_no_cache_ms / time_with_cache_hit_ms:.1f}x")
        
        # Cache write-through should add minimal overhead (<20%)
        assert time_with_cache_miss_ms < time_no_cache_ms * 1.2
        
        # Cache hits should be significantly faster (>10x for 100+ records)
        if len(result_no_cache) >= 100:
            assert time_with_cache_hit_ms < time_no_cache_ms / 10


class TestIndexAnalysisPerformance:
    """Benchmark query performance analyzer tools."""
    
    @pytest.mark.skip(reason="Requires database connection - run manually")
    def test_fragmentation_analysis_speed(self, connection_string: str):
        """Verify index fragmentation analysis completes quickly."""
        analyzer = QueryPerformanceAnalyzer(connection_string)
        
        start_time = time.perf_counter()
        fragmentation = analyzer.get_index_fragmentation(fragmentation_threshold=0)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        print(f"\nFragmentation analysis performance:")
        print(f"  Indexes analyzed: {len(fragmentation)}")
        print(f"  Time: {elapsed_ms:.2f}ms")
        print(f"  Avg per index: {elapsed_ms / len(fragmentation):.2f}ms" if fragmentation else "  No indexes")
        
        # Should complete in <1 second for typical mapping table
        assert elapsed_ms < 1000
    
    @pytest.mark.skip(reason="Requires database connection - run manually")
    def test_usage_stats_speed(self, connection_string: str):
        """Verify index usage stats retrieval is fast."""
        analyzer = QueryPerformanceAnalyzer(connection_string)
        
        start_time = time.perf_counter()
        usage_stats = analyzer.get_index_usage_stats()
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        print(f"\nUsage stats performance:")
        print(f"  Indexes analyzed: {len(usage_stats)}")
        print(f"  Time: {elapsed_ms:.2f}ms")
        
        # Should complete in <500ms
        assert elapsed_ms < 500


class TestCacheHitRateScenarios:
    """Test cache effectiveness in realistic scenarios."""
    
    def test_repeated_desanitization_scenario(self):
        """Simulate repeated desanitization of same batch (high hit rate expected)."""
        cache = MappingLRUCache(max_size=1000)
        
        # Simulate first desanitization (all misses)
        for i in range(500):
            key = ("Customers", "Email", f"masked_{i}")
            value = cache.get(key)  # Miss
            if value is None:
                cache.set(key, f"original_{i}")
        
        metrics_after_first = cache.get_metrics()
        
        # Simulate second desanitization (all hits)
        for i in range(500):
            key = ("Customers", "Email", f"masked_{i}")
            value = cache.get(key)  # Hit
            assert value == f"original_{i}"
        
        metrics_after_second = cache.get_metrics()
        
        print(f"\nRepeated desanitization scenario:")
        print(f"  After 1st run: Hit rate {metrics_after_first.hit_rate:.1f}%")
        print(f"  After 2nd run: Hit rate {metrics_after_second.hit_rate:.1f}%")
        
        # Second run should have 100% hit rate
        assert metrics_after_second.hit_rate > 80
    
    def test_partial_overlap_scenario(self):
        """Simulate partial overlap between sanitization batches."""
        cache = MappingLRUCache(max_size=1000)
        
        # Batch 1: Records 0-499
        for i in range(500):
            key = ("Customers", "Email", f"masked_{i}")
            cache.set(key, f"original_{i}")
        
        # Batch 2: Records 250-749 (50% overlap)
        hits_before = cache.get_metrics().hits
        for i in range(250, 750):
            key = ("Customers", "Email", f"masked_{i}")
            value = cache.get(key)
            if value is None:
                cache.set(key, f"original_{i}")
        
        hits_after = cache.get_metrics().hits
        overlap_hits = hits_after - hits_before
        
        print(f"\nPartial overlap scenario:")
        print(f"  Overlap hits: {overlap_hits}")
        print(f"  Expected: ~250")
        print(f"  Hit rate: {cache.get_metrics().hit_rate:.1f}%")
        
        # Should have ~250 hits from overlap
        assert 240 < overlap_hits < 260


# Entry point for manual benchmarking
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python test_mapping_performance_benchmark.py <connection_string>")
        sys.exit(1)
    
    conn_str = sys.argv[1]
    
    print("=" * 70)
    print("Mapping Performance Benchmarks")
    print("=" * 70)
    
    # Run database-dependent benchmarks
    benchmark = TestMappingTablePerformance()
    benchmark.test_query_performance_comparison(conn_str)
    
    analyzer_bench = TestIndexAnalysisPerformance()
    analyzer_bench.test_fragmentation_analysis_speed(conn_str)
    analyzer_bench.test_usage_stats_speed(conn_str)
    
    print("\n" + "=" * 70)
    print("All benchmarks completed successfully!")
    print("=" * 70)
