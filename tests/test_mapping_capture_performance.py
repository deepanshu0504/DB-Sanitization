"""
Performance benchmark tests for Story 1.2: Mapping Capture During Sanitization.

Verifies acceptance criterion: Mapping capture overhead must be <5% compared to baseline.

Run with: pytest tests/test_mapping_capture_performance.py -v -s
"""

import os
import time
import uuid
import pytest
from typing import Generator, List, Dict, Any

import pyodbc

from database.schema_inspector import SchemaInspector
from mapping.mapping_table_manager import MappingTableManager, MappingRecord


# ============================================================================
# CONFIGURATION
# ============================================================================

# Number of rows for performance testing
BENCHMARK_ROWS = 10000

# Acceptable overhead percentage (acceptance criterion)
MAX_OVERHEAD_PERCENT = 5.0


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def test_connection_string() -> str:
    """Provide test database connection string from environment."""
    server = os.getenv("TEST_DB_SERVER", "localhost")
    database = os.getenv("TEST_DB_NAME", "SanitizationTest")
    auth_type = os.getenv("TEST_DB_AUTH", "windows")
    
    if auth_type == "windows":
        return f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
    else:
        username = os.getenv("TEST_DB_USER", "sa")
        password = os.getenv("TEST_DB_PASSWORD", "")
        return f"DRIVER{{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password};"


@pytest.fixture
def test_db_with_large_dataset(
    test_connection_string: str
) -> Generator[pyodbc.Connection, None, None]:
    """
    Setup test database with large dataset for performance testing.
    
    Creates:
    - PerfTest table with BENCHMARK_ROWS rows
    - token_mappings table
    """
    conn = pyodbc.connect(test_connection_string)
    cursor = conn.cursor()
    
    # Clean up
    cursor.execute("IF OBJECT_ID('dbo.PerfTest', 'U') IS NOT NULL DROP TABLE dbo.PerfTest")
    cursor.execute("IF OBJECT_ID('dbo.token_mappings', 'U') IS NOT NULL DROP TABLE dbo.token_mappings")
    conn.commit()
    
    # Create test table
    cursor.execute("""
        CREATE TABLE dbo.PerfTest (
            RowID INT PRIMARY KEY,
            Email NVARCHAR(255),
            Phone NVARCHAR(20),
            Name NVARCHAR(100)
        )
    """)
    conn.commit()
    
    # Insert test data in batches
    print(f"\n[Setup] Inserting {BENCHMARK_ROWS:,} test rows...")
    batch_size = 1000
    
    for batch_start in range(0, BENCHMARK_ROWS, batch_size):
        batch_data = [
            (
                i,
                f"user{i}@example.com",
                f"555-{i:04d}",
                f"User {i}"
            )
            for i in range(batch_start, min(batch_start + batch_size, BENCHMARK_ROWS))
        ]
        
        cursor.executemany("""
            INSERT INTO dbo.PerfTest (RowID, Email, Phone, Name)
            VALUES (?, ?, ?, ?)
        """, batch_data)
        conn.commit()
        
        if (batch_start + batch_size) % 5000 == 0:
            print(f"  [Setup] Inserted {batch_start + batch_size:,} rows...")
    
    print(f"  [Setup] ✓ {BENCHMARK_ROWS:,} rows inserted")
    
    # Create mapping table
    mapping_manager = MappingTableManager(test_connection_string)
    mapping_manager.create_table(drop_existing=True)
    
    yield conn
    
    # Cleanup
    print("\n[Teardown] Cleaning up test tables...")
    cursor.execute("DROP TABLE IF EXISTS dbo.PerfTest")
    cursor.execute("DROP TABLE IF EXISTS dbo.token_mappings")
    conn.commit()
    cursor.close()
    conn.close()


# ============================================================================
# PERFORMANCE BENCHMARK TESTS
# ============================================================================

def test_mapping_capture_overhead_acceptance_criterion(
    test_connection_string: str,
    test_db_with_large_dataset
):
    """
    PRIMARY ACCEPTANCE TEST: Verify mapping capture overhead is <5%.
    
    This test:
    1. Baseline: Simulate sanitization WITHOUT mapping capture
    2. Test: Simulate sanitization WITH mapping capture
    3. Calculate overhead percentage
    4. Assert overhead < 5% (acceptance criterion)
    """
    conn = test_db_with_large_dataset
    schema_inspector = SchemaInspector(test_connection_string)
    mapping_manager = MappingTableManager(test_connection_string)
    
    # Get PK info
    pk_info = schema_inspector.get_primary_key_columns("PerfTest", "dbo")
    
    print(f"\n{'='*80}")
    print(f"PERFORMANCE BENCHMARK: Mapping Capture Overhead")
    print(f"{'='*80}")
    print(f"Dataset size: {BENCHMARK_ROWS:,} rows")
    print(f"Acceptance criterion: Overhead < {MAX_OVERHEAD_PERCENT}%")
    print(f"{'-'*80}\n")
    
    # ========================================================================
    # BASELINE: Sanitization WITHOUT mapping capture
    # ========================================================================
    
    print("[Baseline] Measuring sanitization without mapping capture...")
    
    # Fetch all data (simulates sanitization query)
    cursor = conn.cursor()
    
    baseline_start = time.time()
    
    cursor.execute("SELECT RowID, Email FROM dbo.PerfTest WHERE Email IS NOT NULL")
    rows = cursor.fetchall()
    
    # Simulate masking (deterministic hash-based)
    updates = []
    for row_id, email in rows:
        masked = f"masked_{row_id}@example.com"  # Simple masking simulation
        updates.append((email, masked))
    
    # Simulate bulk update
    cursor.execute("""
        CREATE TABLE #temp_updates (
            original_value NVARCHAR(MAX),
            masked_value NVARCHAR(MAX)
        )
    """)
    cursor.executemany(
        "INSERT INTO #temp_updates VALUES (?, ?)",
        updates
    )
    
    cursor.execute("""
        UPDATE t
        SET t.Email = u.masked_value
        FROM dbo.PerfTest t
        INNER JOIN #temp_updates u ON t.Email = u.original_value
    """)
    
    cursor.execute("DROP TABLE #temp_updates")
    conn.commit()
    
    baseline_duration = time.time() - baseline_start
    baseline_throughput = BENCHMARK_ROWS / baseline_duration
    
    print(f"  ✓ Baseline completed")
    print(f"  Duration: {baseline_duration:.2f}s")
    print(f"  Throughput: {baseline_throughput:.0f} rows/sec")
    print()
    
    # Reset data
    print("[Reset] Restoring original data...")
    cursor.execute("""
        UPDATE dbo.PerfTest
        SET Email = 'user' + CAST(RowID AS NVARCHAR) + '@example.com'
    """)
    conn.commit()
    
    # ========================================================================
    # TEST: Sanitization WITH mapping capture
    # ========================================================================
    
    print("[Test] Measuring sanitization with mapping capture...")
    
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    test_start = time.time()
    
    # Fetch data with PK
    pk_select = schema_inspector.build_pk_select_expression(pk_info)
    cursor.execute(f"""
        SELECT {pk_select} AS record_id, Email
        FROM dbo.PerfTest
        WHERE Email IS NOT NULL
    """)
    rows = cursor.fetchall()
    
    # Simulate masking + mapping record creation
    updates = []
    mapping_records = []
    
    for record_id, email in rows:
        masked = f"masked_{record_id}@example.com"
        updates.append((email, masked))
        
        mapping_records.append(MappingRecord(
            table_name="PerfTest",
            column_name="Email",
            record_id=str(record_id),
            original_value=email,
            masked_value=masked,
            batch_id=batch_id,
            sanitization_run_id=run_id
        ))
    
    # Transaction-safe update + mapping capture
    conn.autocommit = False
    
    try:
        # Bulk update
        cursor.execute("""
            CREATE TABLE #temp_updates (
                original_value NVARCHAR(MAX),
                masked_value NVARCHAR(MAX)
            )
        """)
        cursor.executemany(
            "INSERT INTO #temp_updates VALUES (?, ?)",
            updates
        )
        
        cursor.execute("""
            UPDATE t
            SET t.Email = u.masked_value
            FROM dbo.PerfTest t
            INNER JOIN #temp_updates u ON t.Email = u.original_value
        """)
        
        cursor.execute("DROP TABLE #temp_updates")
        
        # Mapping capture (same transaction)
        successful, errors = mapping_manager.insert_batch_no_commit(
            conn,
            mapping_records,
            batch_size=5000
        )
        
        # Commit together
        conn.commit()
        
    finally:
        conn.autocommit = True
    
    test_duration = time.time() - test_start
    test_throughput = BENCHMARK_ROWS / test_duration
    
    print(f"  ✓ Test completed")
    print(f"  Duration: {test_duration:.2f}s")
    print(f"  Throughput: {test_throughput:.0f} rows/sec")
    print(f"  Mappings captured: {len(successful):,}")
    print()
    
    # ========================================================================
    # CALCULATE OVERHEAD
    # ========================================================================
    
    overhead_seconds = test_duration - baseline_duration
    overhead_percent = (overhead_seconds / baseline_duration) * 100
    
    print(f"{'='*80}")
    print(f"RESULTS")
    print(f"{'='*80}")
    print(f"Baseline duration:        {baseline_duration:.2f}s")
    print(f"With mapping capture:     {test_duration:.2f}s")
    print(f"Overhead (absolute):      {overhead_seconds:.2f}s")
    print(f"Overhead (percentage):    {overhead_percent:.1f}%")
    print(f"Acceptance threshold:     {MAX_OVERHEAD_PERCENT}%")
    print()
    
    if overhead_percent < MAX_OVERHEAD_PERCENT:
        print(f"✓ PASS: Overhead {overhead_percent:.1f}% is below {MAX_OVERHEAD_PERCENT}% threshold")
    else:
        print(f"✗ FAIL: Overhead {overhead_percent:.1f}% exceeds {MAX_OVERHEAD_PERCENT}% threshold")
    
    print(f"{'='*80}\n")
    
    # ASSERT ACCEPTANCE CRITERION
    assert overhead_percent < MAX_OVERHEAD_PERCENT, (
        f"Mapping capture overhead ({overhead_percent:.1f}%) exceeds "
        f"acceptance criterion of {MAX_OVERHEAD_PERCENT}%"
    )
    
    # Verify mappings actually captured
    assert len(successful) == BENCHMARK_ROWS, (
        f"Expected {BENCHMARK_ROWS:,} mappings, captured {len(successful):,}"
    )


def test_mapping_throughput_benchmark(
    test_connection_string: str,
    test_db_with_large_dataset
):
    """
    Benchmark pure mapping insertion throughput.
    
    This isolates mapping capture performance from sanitization overhead.
    """
    mapping_manager = MappingTableManager(test_connection_string)
    conn = test_db_with_large_dataset
    
    print(f"\n{'='*80}")
    print(f"MAPPING INSERTION THROUGHPUT BENCHMARK")
    print(f"{'='*80}\n")
    
    # Create test mapping records
    batch_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    
    mapping_records = [
        MappingRecord(
            table_name="PerfTest",
            column_name="Email",
            record_id=str(i),
            original_value=f"user{i}@example.com",
            masked_value=f"masked{i}@example.com",
            batch_id=batch_id,
            sanitization_run_id=run_id
        )
        for i in range(BENCHMARK_ROWS)
    ]
    
    print(f"Inserting {BENCHMARK_ROWS:,} mappings...")
    
    start = time.time()
    successful, errors = mapping_manager.insert_batch_no_commit(
        conn,
        mapping_records,
        batch_size=5000
    )
    conn.commit()
    duration = time.time() - start
    
    throughput = len(successful) / duration
    
    print(f"  ✓ Completed")
    print(f"  Duration: {duration:.2f}s")
    print(f"  Throughput: {throughput:.0f} mappings/sec")
    print(f"  Successful: {len(successful):,}")
    print(f"  Failed: {len(errors)}")
    print(f"{'='*80}\n")
    
    # Performance expectations
    assert len(successful) == BENCHMARK_ROWS
    assert throughput > 1000, f"Mapping throughput {throughput:.0f}/sec is below 1000/sec minimum"


def test_scaling_with_batch_sizes(
    test_connection_string: str,
    test_db_with_large_dataset
):
    """
    Test how mapping capture performance scales with different batch sizes.
    
    This helps identify optimal batch_size configuration.
    """
    mapping_manager = MappingTableManager(test_connection_string)
    conn = test_db_with_large_dataset
    
    print(f"\n{'='*80}")
    print(f"BATCH SIZE SCALING TEST")
    print(f"{'='*80}\n")
    
    # Test different batch sizes
    batch_sizes = [1000, 2500, 5000, 10000]
    results = {}
    
    for batch_size in batch_sizes:
        # Clean up previous mappings
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE dbo.token_mappings")
        conn.commit()
        
        # Create test mappings
        batch_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        
        mapping_records = [
            MappingRecord(
                table_name="PerfTest",
                column_name="Email",
                record_id=str(i),
                original_value=f"user{i}@example.com",
                masked_value=f"masked{i}@example.com",
                batch_id=batch_id,
                sanitization_run_id=run_id
            )
            for i in range(BENCHMARK_ROWS)
        ]
        
        # Measure performance
        start = time.time()
        successful, errors = mapping_manager.insert_batch_no_commit(
            conn,
            mapping_records,
            batch_size=batch_size
        )
        conn.commit()
        duration = time.time() - start
        
        throughput = len(successful) / duration
        results[batch_size] = {
            'duration': duration,
            'throughput': throughput,
            'successful': len(successful)
        }
        
        print(f"Batch size {batch_size:,}:")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Throughput: {throughput:.0f} mappings/sec")
        print()
    
    # Find optimal batch size
    best_batch_size = max(results.keys(), key=lambda k: results[k]['throughput'])
    best_throughput = results[best_batch_size]['throughput']
    
    print(f"{'='*80}")
    print(f"OPTIMAL CONFIGURATION")
    print(f"{'='*80}")
    print(f"Best batch size: {best_batch_size:,}")
    print(f"Best throughput: {best_throughput:.0f} mappings/sec")
    print(f"{'='*80}\n")
    
    # Verify all batch sizes work
    for batch_size, result in results.items():
        assert result['successful'] == BENCHMARK_ROWS


# ============================================================================
# DIAGNOSTIC TESTS
# ============================================================================

def test_query_performance_with_pk_extraction(
    test_connection_string: str,
    test_db_with_large_dataset
):
    """
    Measure overhead of PK extraction in SELECT query.
    
    Compares:
    - SELECT column FROM table (baseline)
    - SELECT pk, column FROM table (for mapping capture)
    """
    conn = test_db_with_large_dataset
    schema_inspector = SchemaInspector(test_connection_string)
    cursor = conn.cursor()
    
    print(f"\n{'='*80}")
    print(f"QUERY PERFORMANCE: PK Extraction Overhead")
    print(f"{'='*80}\n")
    
    # Baseline: Without PK
    print("[Baseline] SELECT without PK...")
    start = time.time()
    cursor.execute("SELECT Email FROM dbo.PerfTest WHERE Email IS NOT NULL")
    rows = cursor.fetchall()
    baseline_duration = time.time() - start
    print(f"  Duration: {baseline_duration:.3f}s")
    print(f"  Rows: {len(rows):,}")
    print()
    
    # Test: With PK
    print("[Test] SELECT with PK...")
    pk_info = schema_inspector.get_primary_key_columns("PerfTest", "dbo")
    pk_select = schema_inspector.build_pk_select_expression(pk_info)
    
    start = time.time()
    cursor.execute(f"""
        SELECT {pk_select} AS record_id, Email
        FROM dbo.PerfTest
        WHERE Email IS NOT NULL
    """)
    rows = cursor.fetchall()
    test_duration = time.time() - start
    print(f"  Duration: {test_duration:.3f}s")
    print(f"  Rows: {len(rows):,}")
    print()
    
    # Calculate overhead
    overhead = ((test_duration - baseline_duration) / baseline_duration) * 100
    
    print(f"PK extraction overhead: {overhead:.1f}%")
    print(f"{'='*80}\n")
    
    # PK extraction should add minimal overhead (<2%)
    assert overhead < 2.0, f"PK extraction overhead {overhead:.1f}% is unexpectedly high"


if __name__ == "__main__":
    """
    Run benchmarks directly for development/tuning.
    
    Usage: python tests/test_mapping_capture_performance.py
    """
    import sys
    
    try:
        # Setup test connection
        test_conn_str = os.getenv(
            "TEST_CONNECTION_STRING",
            "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=SanitizationTest;Trusted_Connection=yes;"
        )
        
        print("\n" + "="*80)
        print("MAPPING CAPTURE PERFORMANCE BENCHMARK SUITE")
        print("="*80)
        print(f"\nDataset size: {BENCHMARK_ROWS:,} rows")
        print(f"Acceptance criterion: Overhead < {MAX_OVERHEAD_PERCENT}%")
        print("\nStarting benchmarks...\n")
        
        pytest.main([__file__, "-v", "-s"])
        
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user.")
        sys.exit(1)
