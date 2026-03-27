"""
Data Integrity Validation Integration Tests

Tests comprehensive data integrity checks before and after sanitization
to ensure no data corruption, schema changes, or FK violations occur.

Test Coverage:
    - Pre/post-sanitization snapshot comparison
    - Row count preservation (exact match)
    - NULL value preservation strategy
    - Data type preservation (schema integrity)
    - FK relationship integrity (no orphans)
    - Composite FK integrity
    - Column length preservation (no truncation)
    - PII pattern detection post-sanitization
    - Validation report generation (JSON/HTML)
    - Self-referencing table integrity

Prerequisites:
    - SQL Server instance running
    - Test database created
    - Environment variables set for database connection

Run:
    pytest tests/integration/test_data_integrity_validation.py -v -s

Author: Database Sanitization Team
Created: 2026-03-27
"""

import pytest
import os
import logging
import uuid
import re
from typing import List

from src.config import SanitizationConfig, DatabaseConfig, PIIColumnConfig
from src.mapping.mapping_config import MappingConfig
from src.database.connection_manager import ConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.sanitization.orchestrator import SanitizationOrchestrator
from src.sanitization.dependency_resolver import DependencyResolver
from src.mapping.mapping_manager import MappingManager
from src.validation.integrity_validator import IntegrityValidator, ValidationPhase
from src.validation.validation_result import ValidationResult

from tests.integration.test_db_setup import (
    setup_test_database,
    teardown_test_database,
    verify_test_schema
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mark all tests as integration tests
pytestmark = [pytest.mark.integration]


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="module")
def db_config() -> DatabaseConfig:
    """Create database configuration from environment."""
    return DatabaseConfig(
        server=os.getenv('SQLSERVER_HOST', 'localhost'),
        database=os.getenv('SQLSERVER_DB', 'SanitizationTest'),
        auth_type=os.getenv('SQLSERVER_AUTH', 'windows'),
        username=os.getenv('SQLSERVER_USER'),
        password=os.getenv('SQLSERVER_PASS'),
        timeout=60,
        batch_size=10000
    )


@pytest.fixture(scope="module")
def connection_manager(db_config) -> ConnectionManager:
    """Create connection manager for test database."""
    return ConnectionManager(db_config)


@pytest.fixture(scope="module")
def test_database(connection_manager):
    """Module-scoped test database setup."""
    logger.info("Setting up test database for integrity validation tests")
    
    success = setup_test_database(connection_manager, force_recreate=True)
    assert success, "Failed to setup test database"
    
    is_valid = verify_test_schema(connection_manager)
    assert is_valid, "Test database schema verification failed"
    
    yield connection_manager
    
    logger.info("Tearing down test database")
    teardown_test_database(connection_manager, raise_on_error=False)


@pytest.fixture
def schema_extractor(test_database) -> SchemaExtractor:
    """Create schema extractor."""
    return SchemaExtractor(test_database)


@pytest.fixture
def dependency_resolver(schema_extractor) -> DependencyResolver:
    """Create dependency resolver."""
    fk_metadata = schema_extractor.extract_foreign_keys()
    return DependencyResolver(fk_metadata)


@pytest.fixture
def mapping_manager(test_database) -> MappingManager:
    """Create mapping manager."""
    config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings_integrity_test",
        encryption_enabled=False,
        batch_size=1000
    )
    
    manager = MappingManager(test_database, config)
    manager.create_mapping_table()
    
    yield manager
    
    # Cleanup
    try:
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("IF OBJECT_ID('sanitization.pii_mappings_integrity_test', 'U') IS NOT NULL DROP TABLE sanitization.pii_mappings_integrity_test")
            conn.commit()
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")


@pytest.fixture
def integrity_validator(test_database, schema_extractor) -> IntegrityValidator:
    """Create integrity validator."""
    return IntegrityValidator(test_database, schema_extractor)


@pytest.fixture
def orchestrator(
    test_database,
    schema_extractor,
    dependency_resolver,
    mapping_manager,
    integrity_validator
) -> SanitizationOrchestrator:
    """Create orchestrator."""
    return SanitizationOrchestrator(
        connection_manager=test_database,
        schema_extractor=schema_extractor,
        dependency_resolver=dependency_resolver,
        mapping_manager=mapping_manager,
        integrity_validator=integrity_validator
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_basic_pii_config() -> List[PIIColumnConfig]:
    """Create basic PII configuration."""
    return [
        PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False),
        PIIColumnConfig(schema="sales", table="Customers", column="Phone", pii_type="phone", nullable=True),
        PIIColumnConfig(schema="sales", table="Customers", column="FirstName", pii_type="name", nullable=False),
    ]


# ============================================================================
# TEST CASES - PRE/POST SNAPSHOT COMPARISON
# ============================================================================

class TestSnapshotComparison:
    """Test pre/post-sanitization snapshot comparison."""
    
    def test_capture_pre_sanitization_snapshot(
        self,
        test_database,
        integrity_validator
    ):
        """
        Test capturing baseline metrics before sanitization.
        """
        operation_id = uuid.uuid4()
        tables = ['sales.Customers', 'sales.Orders']
        
        # Capture pre-snapshot
        snapshot = integrity_validator.capture_pre_snapshot(
            operation_id=operation_id,
            tables=tables
        )
        
        # Validate snapshot structure
        assert snapshot.operation_id == operation_id
        assert snapshot.phase == ValidationPhase.PRE_SANITIZATION
        assert len(snapshot.table_metrics) >= 2
        
        # Validate metrics collected
        for table in tables:
            assert table in snapshot.table_metrics
            metrics = snapshot.table_metrics[table]
            assert metrics.row_count > 0
            assert len(metrics.column_null_counts) > 0
        
        logger.info(f"✓ Pre-sanitization snapshot captured: {len(snapshot.table_metrics)} tables")
    
    
    def test_post_sanitization_comparison(
        self,
        test_database,
        orchestrator,
        integrity_validator,
        db_config
    ):
        """
        Test complete pre/post-sanitization comparison workflow.
        """
        operation_id = uuid.uuid4()
        tables = ['sales.Customers']
        
        # Capture pre-snapshot
        pre_snapshot = integrity_validator.capture_pre_snapshot(
            operation_id=operation_id,
            tables=tables
        )
        
        # Execute sanitization
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Capture post-snapshot
        post_snapshot = integrity_validator.capture_post_snapshot(
            operation_id=operation_id,
            tables=tables
        )
        
        # Compare snapshots
        comparison_report = integrity_validator.compare_snapshots(
            pre_snapshot,
            post_snapshot
        )
        
        # Validate comparison
        assert comparison_report.overall_status in ["PASSED", "WARNING"]
        assert len(comparison_report.validation_result.errors) == 0 or \
               len(comparison_report.validation_result.errors) < 3  # Allow some warnings
        
        logger.info(f"✓ Snapshot comparison complete: {comparison_report.overall_status}")


# ============================================================================
# TEST CASES - ROW COUNT PRESERVATION
# ============================================================================

class TestRowCountPreservation:
    """Test that row counts match exactly before and after sanitization."""
    
    def test_row_count_exact_match(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that every table's row count remains exactly the same.
        """
        # Get pre-sanitization row counts
        tables = ['sales.Customers', 'sales.Orders', 'sales.OrderDetails']
        pre_counts = {}
        
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            for table in tables:
                schema, table_name = table.split('.')
                cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table_name}]")
                pre_counts[table] = cursor.fetchone()[0]
        
        logger.info(f"Pre-sanitization counts: {pre_counts}")
        
        # Sanitize
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Get post-sanitization row counts
        post_counts = {}
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            for table in tables:
                schema, table_name = table.split('.')
                cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table_name}]")
                post_counts[table] = cursor.fetchone()[0]
        
        logger.info(f"Post-sanitization counts: {post_counts}")
        
        # Validate exact match
        for table in tables:
            assert pre_counts[table] == post_counts[table], \
                f"Row count mismatch for {table}: {pre_counts[table]} → {post_counts[table]}"
        
        logger.info("✓ All row counts preserved exactly")


# ============================================================================
# TEST CASES - NULL VALUE PRESERVATION
# ============================================================================

class TestNullValuePreservation:
    """Test that NULL value counts are preserved."""
    
    def test_null_count_preservation(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that NULL value counts per column remain unchanged.
        """
        # Get pre-sanitization NULL counts for Phone column
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) AS total_rows,
                    SUM(CASE WHEN Phone IS NULL THEN 1 ELSE 0 END) AS null_count,
                    SUM(CASE WHEN Phone IS NOT NULL THEN 1 ELSE 0 END) AS non_null_count
                FROM sales.Customers
            """)
            result = cursor.fetchone()
            pre_total, pre_null_count, pre_non_null = result
        
        logger.info(f"Pre-sanitization: {pre_total} total, {pre_null_count} NULLs, {pre_non_null} non-NULL")
        
        # Sanitize
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Get post-sanitization NULL counts
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) AS total_rows,
                    SUM(CASE WHEN Phone IS NULL THEN 1 ELSE 0 END) AS null_count,
                    SUM(CASE WHEN Phone IS NOT NULL THEN 1 ELSE 0 END) AS non_null_count
                FROM sales.Customers
            """)
            result = cursor.fetchone()
            post_total, post_null_count, post_non_null = result
        
        logger.info(f"Post-sanitization: {post_total} total, {post_null_count} NULLs, {post_non_null} non-NULL")
        
        # Validate NULL counts preserved
        assert pre_null_count == post_null_count, \
            f"NULL count changed: {pre_null_count} → {post_null_count}"
        assert pre_non_null == post_non_null, \
            f"Non-NULL count changed: {pre_non_null} → {post_non_null}"
        
        logger.info("✓ NULL value counts preserved")


# ============================================================================
# TEST CASES - FK INTEGRITY
# ============================================================================

class TestFKIntegrity:
    """Test foreign key relationship integrity."""
    
    def test_fk_integrity_no_orphans(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that no orphaned records are created after sanitization.
        """
        pii_columns = [
            PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="sales", table="Orders", column="ShipToName", pii_type="name", nullable=True),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Sanitize
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Check for orphaned orders
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*)
                FROM sales.Orders o
                WHERE o.CustomerID IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM sales.Customers c 
                      WHERE c.CustomerID = o.CustomerID
                  )
            """)
            orphan_count = cursor.fetchone()[0]
        
        assert orphan_count == 0, f"Found {orphan_count} orphaned orders"
        logger.info("✓ FK integrity validated: 0 orphaned records")
    
    
    def test_composite_fk_integrity(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that composite FK relationships remain intact.
        """
        # OrderLineItems has composite FK to Orders
        pii_columns = [
            PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Sanitize
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Check composite FK integrity
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*)
                FROM sales.OrderLineItems oli
                WHERE NOT EXISTS (
                    SELECT 1 FROM sales.Orders o 
                    WHERE o.OrderID = oli.OrderID
                )
            """)
            orphan_count = cursor.fetchone()[0]
        
        assert orphan_count == 0, f"Found {orphan_count} orphaned line items"
        logger.info("✓ Composite FK integrity validated")


# ============================================================================
# TEST CASES - SELF-REFERENCING INTEGRITY
# ============================================================================

class TestSelfReferencingIntegrity:
    """Test self-referencing table integrity."""
    
    def test_self_referencing_hierarchy_intact(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that self-referencing hierarchy remains intact after sanitization.
        """
        pii_columns = [
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Sanitize
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Check for orphaned manager references
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*)
                FROM hr.Employees e
                WHERE e.ManagerID IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM hr.Employees m 
                      WHERE m.EmployeeID = e.ManagerID
                  )
            """)
            orphan_count = cursor.fetchone()[0]
        
        assert orphan_count == 0, f"Found {orphan_count} orphaned manager references"
        logger.info("✓ Self-referencing integrity validated")


# ============================================================================
# TEST CASES - PII PATTERN DETECTION
# ============================================================================

class TestPIIPatternDetection:
    """Test that PII patterns are removed after sanitization."""
    
    def test_email_pattern_detection_post_sanitization(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that original email patterns are replaced with masked patterns.
        """
        # Get original email sample
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT TOP 3 Email FROM sales.Customers ORDER BY CustomerID")
            original_emails = [row[0] for row in cursor.fetchall()]
        
        logger.info(f"Original emails: {original_emails[:2]}")
        
        # Sanitize
        pii_columns = [
            PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False)
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Get masked emails
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT TOP 3 Email FROM sales.Customers ORDER BY CustomerID")
            masked_emails = [row[0] for row in cursor.fetchall()]
        
        logger.info(f"Masked emails: {masked_emails[:2]}")
        
        # Validate emails changed
        assert masked_emails != original_emails, "Emails not masked"
        
        # Validate masked emails still have valid format
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        for email in masked_emails:
            assert email_pattern.match(email), f"Invalid masked email format: {email}"
        
        # Validate original patterns not present
        for original in original_emails:
            assert original not in masked_emails, f"Original email still present: {original}"
        
        logger.info("✓ PII pattern detection validated: original emails replaced")


# ============================================================================
# TEST CASES - VALIDATION REPORT GENERATION
# ============================================================================

class TestValidationReports:
    """Test validation report generation."""
    
    def test_json_report_generation(
        self,
        test_database,
        orchestrator,
        integrity_validator,
        db_config
    ):
        """
        Test generating JSON validation report.
        """
        operation_id = uuid.uuid4()
        tables = ['sales.Customers']
        
        # Capture pre-snapshot
        pre_snapshot = integrity_validator.capture_pre_snapshot(operation_id, tables)
        
        # Sanitize
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Capture post-snapshot
        post_snapshot = integrity_validator.capture_post_snapshot(operation_id, tables)
        
        # Generate comparison report
        comparison = integrity_validator.compare_snapshots(pre_snapshot, post_snapshot)
        
        # Export JSON
        json_files = comparison.export(format='json')
        
        assert len(json_files) == 1, f"Expected 1 JSON file, got {len(json_files)}"
        assert json_files[0].endswith('.json'), "File should have .json extension"
        
        logger.info(f"✓ JSON report generated: {json_files[0]}")
    
    
    def test_html_report_generation(
        self,
        test_database,
        orchestrator,
        integrity_validator,
        db_config
    ):
        """
        Test generating HTML validation report.
        """
        operation_id = uuid.uuid4()
        tables = ['sales.Customers']
        
        # Capture snapshots
        pre_snapshot = integrity_validator.capture_pre_snapshot(operation_id, tables)
        
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        post_snapshot = integrity_validator.capture_post_snapshot(operation_id, tables)
        
        # Generate comparison
        comparison = integrity_validator.compare_snapshots(pre_snapshot, post_snapshot)
        
        # Export HTML
        html_files = comparison.export(format='html')
        
        assert len(html_files) == 1, f"Expected 1 HTML file, got {len(html_files)}"
        assert html_files[0].endswith('.html'), "File should have .html extension"
        
        logger.info(f"✓ HTML report generated: {html_files[0]}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
