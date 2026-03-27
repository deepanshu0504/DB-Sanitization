"""Unit tests for correlation ID context management.

Tests the correlation ID context manager, getters/setters, and thread isolation.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.logging.correlation import (
    correlation_context,
    CorrelationContext,
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    new_correlation_id,
)


class TestCorrelationIDFunctions:
    """Test suite for correlation ID utility functions."""
    
    def test_set_and_get_correlation_id(self):
        """Test basic set and get operations."""
        set_correlation_id("test-123")
        
        assert get_correlation_id() == "test-123"
        
        # Cleanup
        clear_correlation_id()
    
    def test_clear_correlation_id(self):
        """Test clearing correlation ID."""
        set_correlation_id("test-456")
        clear_correlation_id()
        
        assert get_correlation_id() is None
    
    def test_new_correlation_id_generates_uuid(self):
        """Test that new_correlation_id generates valid UUIDs."""
        correlation_id = new_correlation_id()
        
        # UUID format: 8-4-4-4-12 characters
        assert len(correlation_id) == 36
        assert correlation_id.count("-") == 4
    
    def test_new_correlation_id_generates_unique_ids(self):
        """Test that each call generates a unique ID."""
        id1 = new_correlation_id()
        id2 = new_correlation_id()
        id3 = new_correlation_id()
        
        assert id1 != id2
        assert id2 != id3
        assert id1 != id3


class TestCorrelationContextFunction:
    """Test suite for correlation_context context manager function."""
    
    def test_context_sets_correlation_id(self):
        """Test that entering context sets correlation ID."""
        with correlation_context("operation-123") as corr_id:
            assert get_correlation_id() == "operation-123"
            assert corr_id == "operation-123"
    
    def test_context_clears_on_exit(self):
        """Test that exiting context clears correlation ID."""
        with correlation_context("operation-456"):
            assert get_correlation_id() == "operation-456"
        
        # Should be None after exiting context
        assert get_correlation_id() is None
    
    def test_auto_generate_correlation_id(self):
        """Test that correlation ID is auto-generated when not provided."""
        with correlation_context() as corr_id:
            assert corr_id is not None
            assert len(corr_id) == 36  # UUID format
            assert get_correlation_id() == corr_id
    
    def test_auto_generate_disabled(self):
        """Test behavior when auto-generate is disabled."""
        with correlation_context(auto_generate=False) as corr_id:
            # Should use default when no ID provided and auto_generate=False
            assert corr_id == "NO_CORRELATION"
            assert get_correlation_id() == "NO_CORRELATION"
    
    def test_nested_contexts(self):
        """Test that nested contexts work correctly."""
        with correlation_context("outer") as outer_id:
            assert get_correlation_id() == "outer"
            
            with correlation_context("inner") as inner_id:
                assert get_correlation_id() == "inner"
                assert inner_id == "inner"
            
            # Should restore outer ID after inner context exits
            assert get_correlation_id() == "outer"
        
        # Should be None after all contexts exit
        assert get_correlation_id() is None
    
    def test_nested_contexts_with_auto_generate(self):
        """Test nested contexts with auto-generated IDs."""
        with correlation_context() as outer_id:
            outer = get_correlation_id()
            assert outer == outer_id
            
            with correlation_context() as inner_id:
                inner = get_correlation_id()
                assert inner == inner_id
                assert inner != outer
            
            # Should restore outer ID
            assert get_correlation_id() == outer
    
    def test_context_preserves_previous_id(self):
        """Test that context preserves and restores previous ID."""
        set_correlation_id("previous-123")
        
        with correlation_context("temporary-456"):
            assert get_correlation_id() == "temporary-456"
        
        # Should restore previous ID
        assert get_correlation_id() == "previous-123"
        
        # Cleanup
        clear_correlation_id()
    
    def test_context_on_exception(self):
        """Test that context clears ID even when exception occurs."""
        try:
            with correlation_context("exception-test"):
                assert get_correlation_id() == "exception-test"
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Should still clear ID after exception
        assert get_correlation_id() is None


class TestCorrelationContextClass:
    """Test suite for CorrelationContext class."""
    
    def test_class_based_context_start_stop(self):
        """Test explicit start/stop methods."""
        context = CorrelationContext("test-context")
        
        context.start()
        assert get_correlation_id() == "test-context"
        
        context.stop()
        assert get_correlation_id() is None
    
    def test_class_based_context_manager(self):
        """Test using class as context manager."""
        with CorrelationContext("class-test") as corr_id:
            assert corr_id == "class-test"
            assert get_correlation_id() == "class-test"
        
        assert get_correlation_id() is None
    
    def test_class_auto_generates_id(self):
        """Test that class auto-generates ID when not provided."""
        context = CorrelationContext()
        
        assert context.correlation_id is not None
        assert len(context.correlation_id) == 36  # UUID format
    
    def test_class_restores_previous_id(self):
        """Test that class restores previous ID on stop."""
        set_correlation_id("previous")
        
        context = CorrelationContext("new")
        context.start()
        assert get_correlation_id() == "new"
        
        context.stop()
        assert get_correlation_id() == "previous"
        
        # Cleanup
        clear_correlation_id()
    
    def test_class_repr(self):
        """Test string representation of CorrelationContext."""
        context = CorrelationContext("repr-test")
        
        repr_str = repr(context)
        assert "CorrelationContext" in repr_str
        assert "repr-test" in repr_str


class TestThreadIsolation:
    """Test suite for thread isolation of correlation IDs."""
    
    def test_correlation_ids_isolated_between_threads(self):
        """Test that different threads have independent correlation IDs."""
        results = {}
        
        def thread_function(thread_id: str, correlation_id: str):
            set_correlation_id(correlation_id)
            time.sleep(0.01)  # Small delay to allow thread interleaving
            results[thread_id] = get_correlation_id()
            clear_correlation_id()
        
        thread1 = threading.Thread(
            target=thread_function,
            args=("thread1", "correlation-1")
        )
        thread2 = threading.Thread(
            target=thread_function,
            args=("thread2", "correlation-2")
        )
        
        thread1.start()
        thread2.start()
        
        thread1.join()
        thread2.join()
        
        # Each thread should have its own correlation ID
        assert results["thread1"] == "correlation-1"
        assert results["thread2"] == "correlation-2"
    
    def test_context_manager_thread_isolation(self):
        """Test that context managers maintain thread isolation."""
        results = {}
        
        def thread_function(thread_id: str, correlation_id: str):
            with correlation_context(correlation_id):
                time.sleep(0.01)  # Small delay
                results[thread_id] = get_correlation_id()
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            executor.submit(thread_function, "t1", "corr-1")
            executor.submit(thread_function, "t2", "corr-2")
            executor.submit(thread_function, "t3", "corr-3")
        
        assert results["t1"] == "corr-1"
        assert results["t2"] == "corr-2"
        assert results["t3"] == "corr-3"
    
    def test_main_thread_not_affected_by_other_threads(self):
        """Test that correlation ID in main thread is not affected by other threads."""
        set_correlation_id("main-thread")
        
        def other_thread_function():
            set_correlation_id("other-thread")
            time.sleep(0.01)
        
        thread = threading.Thread(target=other_thread_function)
        thread.start()
        thread.join()
        
        # Main thread should still have its own ID
        assert get_correlation_id() == "main-thread"
        
        # Cleanup
        clear_correlation_id()
    
    def test_nested_contexts_across_threads(self):
        """Test nested contexts work correctly in concurrent threads."""
        results = {}
        
        def thread_function(thread_id: str):
            with correlation_context("outer") as outer_id:
                results[f"{thread_id}_outer"] = get_correlation_id()
                
                with correlation_context("inner") as inner_id:
                    results[f"{thread_id}_inner"] = get_correlation_id()
                
                results[f"{thread_id}_restored"] = get_correlation_id()
        
        threads = []
        for i in range(3):
            thread = threading.Thread(target=thread_function, args=(f"t{i}",))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Each thread should have maintained its own context stack
        for i in range(3):
            assert results[f"t{i}_outer"] == "outer"
            assert results[f"t{i}_inner"] == "inner"
            assert results[f"t{i}_restored"] == "outer"
