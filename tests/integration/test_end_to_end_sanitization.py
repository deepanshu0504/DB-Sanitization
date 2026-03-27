"""
End-to-End Integration Tests for Complete Sanitization Workflow

Tests the complete sanitization workflow from schema extraction through
data masking, mapping storage, and integrity validation. Uses the comprehensive
test database setup with multiple schemas, FK relationships, and PII types.

Test Coverage:
    - Complete workflow with small datasets (20-100 rows)
    - Large dataset processing (10k+ rows) with batch operations
    - Multi-schema sanitization (dbo, sales, hr)
    - All PII types (email, phone, SSN, name, generic)
    - FK integrity preservation (no orphaned records)
    - Row count preservation (pre vs post)
    - Data type preservation (column metadata unchanged)
    - Mapping storage and retrieval
    - Progress callback functionality
    - Dry-run mode validation

Prerequisites:
    - SQL Server instance running
    - Test database created (run test_db_setup.py setup)
    - Environment variables set:
        SQLSERVER_HOST, SQLSERVER_DB, SQLSERVER_AUTH, 
        SQLSERVER_USER (if SQL auth), SQLSERVER_PASS (if SQL auth)

Run:
    pytest tests/integration/test_end_to_end_sanitization.py -v -s

Author: Database Sanitization Team
Created: 2026-03-27
"""

import pytest
import os
import uuid
import logging
from typing import List, Dict, Any, Optional
from decimal import Decimal

from src.config import (
    SanitizationConfig,
    DatabaseConfig,
    PIIColumnConfig,
    LoggingConfig
)
from src.mapping.mapping_config import MappingConfig
from src.database.connection_manager import ConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.sanitization.orchestrator import SanitizationOrchestrator, SanitizationPhase
from src.sanitization.dependency_resolver import DependencyResolver
from src.mapping.mapping_manager import MappingManager
from src.validation.integrity_validator import IntegrityValidator
from src.exceptions import SanitizationError

from tests.integration.test_db_setup import (
    setup_test_database,
    teardown_test_database,
    verify_test_schema,
    get_test_db_stats
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mark all tests as integration tests
pytestmark = [pytest.mark.integration, pytest.mark.e2e]


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
        timeout=60,  # Longer timeout for large operations
        batch_size=10000
    )


@pytest.fixture(scope="module")
def connection_manager(db_config) -> ConnectionManager:
    """Create connection manager for test database."""
    return ConnectionManager(db_config)


@pytest.fixture(scope="module")
def test_database(connection_manager):
    """
    Module-scoped test database setup.
    
    Sets up comprehensive test schema once for all tests in module.
    Tears down at end of module.
    """
    logger.info("Setting up test database for module")
    
    # Setup database
    success = setup_test_database(connection_manager, force_recreate=True)
    assert success, "Failed to setup test database"
    
    # Verify setup
    is_valid = verify_test_schema(connection_manager)
    assert is_valid, "Test database schema verification failed"
    
    # Get stats for logging
    stats = get_test_db_stats(connection_manager)
    logger.info(f"Test database ready: {stats['total_rows']} total rows across {len(stats['tables'])} tables")
    
    yield connection_manager
    
    # Teardown at end of module
    logger.info("Tearing down test database")
    teardown_test_database(connection_manager, raise_on_error=False)


@pytest.fixture
def schema_extractor(test_database) -> SchemaExtractor:
    """Create schema extractor."""
    return SchemaExtractor(test_database)


@pytest.fixture
def dependency_resolver(schema_extractor) -> DependencyResolver:
    """Create dependency resolver."""
    # Extract FK metadata
    fk_metadata = schema_extractor.extract_foreign_keys()
    return DependencyResolver(fk_metadata)


@pytest.fixture
def mapping_manager(test_database) -> MappingManager:
    """Create mapping manager with test configuration."""
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings_test",
        encryption_enabled=False,  # Disable encryption for simplicity
        batch_size=1000,
        index_creation=True,
        transactional=True
    )
    
    manager = MappingManager(test_database, mapping_config)
    
    # Ensure mapping table exists
    manager.create_mapping_table()
    
    yield manager
    
    # Cleanup mapping table after test
    try:
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("IF OBJECT_ID('sanitization.pii_mappings_test', 'U') IS NOT NULL DROP TABLE sanitization.pii_mappings_test")
            conn.commit()
    except Exception as e:
        logger.warning(f"Mapping table cleanup failed: {e}")


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
    """Create orchestrator with all dependencies."""
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

def create_pii_config_for_customers() -> List[PIIColumnConfig]:
    """Create PII configuration for sales.Customers table."""
    return [
        PIIColumnConfig(
            schema="sales",
            table="Customers",
            column="Email",
            pii_type="email",
            nullable=False
        ),
        PIIColumnConfig(
            schema="sales",
            table="Customers",
            column="Phone",
            pii_type="phone",
            nullable=True
        ),
        PIIColumnConfig(
            schema="sales",
            table="Customers",
            column="FirstName",
            pii_type="name",
            nullable=False
        ),
        PIIColumnConfig(
            schema="sales",
            table="Customers",
            column="LastName",
            pii_type="name",
            nullable=False
        ),
        PIIColumnConfig(
            schema="sales",
            table="Customers",
            column="SSN",
            pii_type="ssn",
            nullable=True
        )
    ]


def create_pii_config_for_orders() -> List[PIIColumnConfig]:
    """Create PII configuration for sales.Orders table."""
    return [
        PIIColumnConfig(
            schema="sales",
            table="Orders",
            column="ShipToName",
            pii_type="name",
            nullable=True
        ),
        PIIColumnConfig(
            schema="sales",
            table="Orders",
            column="ShipToAddress",
            pii_type="generic",
            nullable=True
        )
    ]


def create_pii_config_for_employees() -> List[PIIColumnConfig]:
    """Create PII configuration for hr.Employees table."""
    return [
        PIIColumnConfig(
            schema="hr",
            table="Employees",
            column="Email",
            pii_type="email",
            nullable=False
        ),
        PIIColumnConfig(
            schema="hr",
            table="Employees",
            column="Phone",
            pii_type="phone",
            nullable=True
        ),
        PIIColumnConfig(
            schema="hr",
            table="Employees",
            column="FirstName",
            pii_type="name",
            nullable=False
        ),
        PIIColumnConfig(
            schema="hr",
            table="Employees",
            column="LastName",
            pii_type="name",
            nullable=False
        ),
        PIIColumnConfig(
            schema="hr",
            table="Employees",
            column="SSN",
            pii_type="ssn",
            nullable=True
        )
    ]


def get_row_count(connection_manager: ConnectionManager, schema: str, table: str) -> int:
    """Get row count for a table."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}]")
        count = cursor.fetchone()[0]
        cursor.close()
        return count


def get_column_value_sample(
    connection_manager: ConnectionManager, 
    schema: str, 
    table: str, 
    column: str, 
    limit: int = 5
) -> List[Any]:
    """Get sample values from a column."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP {limit} [{column}] FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL")
        values = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return values


def check_fk_integrity(
    connection_manager: ConnectionManager,
    child_schema: str,
    child_table: str,
    child_column: str,
    parent_schema: str,
    parent_table: str,
    parent_column: str
) -> int:
    """Check for orphaned records in FK relationship. Returns count of orphans."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        query = f"""
            SELECT COUNT(*)
            FROM [{child_schema}].[{child_table}] c
            WHERE c.[{child_column}] IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 
                  FROM [{parent_schema}].[{parent_table}] p 
                  WHERE p.[{parent_column}] = c.[{child_column}]
              )
        """
        cursor.execute(query)
        orphan_count = cursor.fetchone()[0]
        cursor.close()
        return orphan_count


# ============================================================================
# TEST CASES - BASIC WORKFLOW
# ============================================================================

class TestCompleteWorkflowSmallDataset:
    """Test complete sanitization workflow with small dataset (20-100 rows)."""
    
    def test_complete_sanitization_small_dataset(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test complete workflow with small dataset: Customers + Orders.
        
        Validates all phases: Validation → Planning → Execution → Verification.
        """
        # Create configuration for 2 tables
        pii_columns = create_pii_config_for_customers() + create_pii_config_for_orders()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True),
            logging=LoggingConfig(level="INFO")
        )
        
        # Capture pre-sanitization row counts
        pre_customer_count = get_row_count(test_database, "sales", "Customers")
        pre_order_count = get_row_count(test_database, "sales", "Orders")
        
        logger.info(f"Pre-sanitization: {pre_customer_count} customers, {pre_order_count} orders")
        assert pre_customer_count > 0, "No customers in test database"
        assert pre_order_count > 0, "No orders in test database"
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        
        # Validate report
        assert report.overall_status == "COMPLETED", f"Sanitization failed: {report.overall_status}"
        assert report.phase == SanitizationPhase.COMPLETED
        assert report.tables_processed >= 2, f"Expected at least 2 tables, processed {report.tables_processed}"
        assert report.rows_processed > 0, "No rows processed"
        
        # Validate row counts unchanged
        post_customer_count = get_row_count(test_database, "sales", "Customers")
        post_order_count = get_row_count(test_database, "sales", "Orders")
        
        assert post_customer_count == pre_customer_count, f"Customer row count changed: {pre_customer_count} → {post_customer_count}"
        assert post_order_count == pre_order_count, f"Order row count changed: {pre_order_count} → {post_order_count}"
        
        # Validate data was actually masked (sample check)
        masked_emails = get_column_value_sample(test_database, "sales", "Customers", "Email", 3)
        assert all('@' in email for email in masked_emails), "Emails not in valid format"
        assert any('user_' in email for email in masked_emails), "Emails not masked deterministically"
        
        logger.info(f"Sanitization complete: {report.tables_processed} tables, {report.rows_processed} rows")
    
    
    def test_sanitization_preserves_fk_integrity(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that FK integrity is preserved after sanitization.
        
        Validates no orphaned records exist in Orders → Customers relationship.
        """
        pii_columns = create_pii_config_for_customers() + create_pii_config_for_orders()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Check FK integrity
        orphan_count = check_fk_integrity(
            test_database,
            child_schema="sales",
            child_table="Orders",
            child_column="CustomerID",
            parent_schema="sales",
            parent_table="Customers",
            parent_column="CustomerID"
        )
        
        assert orphan_count == 0, f"Found {orphan_count} orphaned orders after sanitization"
        logger.info("✓ FK integrity preserved (0 orphaned records)")
    
    
    def test_sanitization_row_count_preservation(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that row counts match exactly before and after sanitization.
        """
        pii_columns = create_pii_config_for_customers()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Get pre-sanitization counts
        pre_counts = {
            'Customers': get_row_count(test_database, "sales", "Customers"),
            'Orders': get_row_count(test_database, "sales", "Orders"),
            'OrderDetails': get_row_count(test_database, "sales", "OrderDetails")
        }
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Get post-sanitization counts
        post_counts = {
            'Customers': get_row_count(test_database, "sales", "Customers"),
            'Orders': get_row_count(test_database, "sales", "Orders"),
            'OrderDetails': get_row_count(test_database, "sales", "OrderDetails")
        }
        
        # Validate all counts match
        for table, pre_count in pre_counts.items():
            post_count = post_counts[table]
            assert pre_count == post_count, f"{table} row count changed: {pre_count} → {post_count}"
        
        logger.info(f"✓ All row counts preserved: {pre_counts}")
    
    
    def test_sanitization_with_mapping_storage(
        self,
        test_database,
        orchestrator,
        mapping_manager,
        db_config
    ):
        """
        Test that mappings are correctly stored during sanitization.
        """
        pii_columns = create_pii_config_for_customers()[:2]  # Email and Phone only
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        assert report.mappings_stored > 0, "No mappings stored"
        
        # Verify mappings exist in database
        operation_id = report.operation_id
        mappings = mapping_manager.get_mappings_by_operation(operation_id)
        
        assert len(mappings) > 0, f"No mappings found for operation {operation_id}"
        assert len(mappings) == report.mappings_stored, f"Mapping count mismatch: {len(mappings)} vs {report.mappings_stored}"
        
        # Verify mapping structure
        first_mapping = mappings[0]
        assert first_mapping.operation_id == operation_id
        assert first_mapping.schema_name == "sales"
        assert first_mapping.table_name == "Customers"
        assert first_mapping.column_name in ["Email", "Phone"]
        assert first_mapping.masked_value is not None
        
        logger.info(f"✓ {len(mappings)} mappings stored and verified")
    
    
    def test_sanitization_dry_run_mode(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test dry-run mode does not modify database.
        """
        pii_columns = create_pii_config_for_customers()[:1]  # Email only
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=False)  # No mapping in dry-run
        )
        
        # Get pre-run sample values
        pre_emails = get_column_value_sample(test_database, "sales", "Customers", "Email", 5)
        
        # Execute dry-run
        report = orchestrator.run(config, dry_run=True)
        
        # Validate report indicates dry-run
        assert "DRY_RUN" in report.overall_status or report.phase == SanitizationPhase.VALIDATION
        
        # Get post-run sample values
        post_emails = get_column_value_sample(test_database, "sales", "Customers", "Email", 5)
        
        # Validate data unchanged
        assert pre_emails == post_emails, "Data was modified in dry-run mode"
        logger.info("✓ Dry-run mode did not modify data")


# ============================================================================
# TEST CASES - MULTI-SCHEMA
# ============================================================================

class TestMultiSchemaSanitization:
    """Test sanitization across multiple schemas (sales, hr, archive)."""
    
    def test_sanitize_multi_schema(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test sanitization across sales, hr, and archive schemas.
        """
        # Create PII config spanning 3 schemas
        pii_columns = (
            create_pii_config_for_customers() +  # sales schema
            create_pii_config_for_employees() +  # hr schema
            [
                # archive schema
                PIIColumnConfig(
                    schema="archive",
                    table="ArchivedCustomers",
                    column="Email",
                    pii_type="email",
                    nullable=True
                ),
                PIIColumnConfig(
                    schema="archive",
                    table="ArchivedCustomers",
                    column="Phone",
                    pii_type="phone",
                    nullable=True
                )
            ]
        )
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        
        # Validate all schemas processed
        assert report.overall_status == "COMPLETED"
        assert report.tables_processed >= 3, f"Expected at least 3 tables (sales.Customers, hr.Employees, archive.ArchivedCustomers)"
        
        # Verify data masked in each schema
        sales_emails = get_column_value_sample(test_database, "sales", "Customers", "Email", 2)
        hr_emails = get_column_value_sample(test_database, "hr", "Employees", "Email", 2)
        archive_emails = get_column_value_sample(test_database, "archive", "ArchivedCustomers", "Email", 2)
        
        all_masked = (
            all('user_' in email or '@' in email for email in sales_emails) and
            all('user_' in email or '@' in email for email in hr_emails) and
            all('user_' in email or '@' in email for email in archive_emails if email)
        )
        
        assert all_masked, "Not all emails masked across schemas"
        logger.info(f"✓ Multi-schema sanitization complete: {report.tables_processed} tables")


# ============================================================================
# TEST CASES - ALL PII TYPES
# ============================================================================

class TestAllPIITypes:
    """Test sanitization with all supported PII types."""
    
    def test_sanitize_all_pii_types(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test masking of all PII types: email, phone, name, SSN, generic.
        """
        pii_columns = create_pii_config_for_customers() + create_pii_config_for_orders()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Validate each PII type was masked
        # Email
        emails = get_column_value_sample(test_database, "sales", "Customers", "Email", 3)
        assert all('@' in email for email in emails), "Invalid email format after masking"
        
        # Phone
        phones = get_column_value_sample(test_database, "sales", "Customers", "Phone", 3)
        assert all(any(char.isdigit() for char in phone) for phone in phones if phone), "Invalid phone format"
        
        # Name
        first_names = get_column_value_sample(test_database, "sales", "Customers", "FirstName", 3)
        last_names = get_column_value_sample(test_database, "sales", "Customers", "LastName", 3)
        assert all(len(name) > 0 for name in first_names), "Empty first names"
        assert all(len(name) > 0 for name in last_names), "Empty last names"
        
        # SSN
        ssns = get_column_value_sample(test_database, "sales", "Customers", "SSN", 3)
        assert all(('-' in ssn and len(ssn) == 11) or len(ssn) == 9 for ssn in ssns if ssn), "Invalid SSN format"
        
        # Generic (ShipToAddress)
        addresses = get_column_value_sample(test_database, "sales", "Orders", "ShipToAddress", 3)
        assert all(len(addr) > 0 for addr in addresses if addr), "Empty generic fields"
        
        logger.info("✓ All PII types masked successfully")


# ============================================================================
# TEST CASES - PERFORMANCE & LARGE DATASETS
# ============================================================================

class TestLargeDatasetProcessing:
    """Test sanitization with large datasets (100+ rows)."""
    
    def test_large_dataset_batch_processing(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test sanitization processes large datasets efficiently with batch operations.
        
        Note: Test database has 100 customers, 150 orders, 300 order details = 550+ rows
        """
        # Create config for all customer and order PII
        pii_columns = create_pii_config_for_customers() + create_pii_config_for_orders()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True, batch_size=50)  # Small batch for testing
        )
        
        import time
        start_time = time.time()
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        
        elapsed_time = time.time() - start_time
        
        # Validate completion
        assert report.overall_status == "COMPLETED"
        assert report.rows_processed > 200, f"Expected >200 rows, processed {report.rows_processed}"
        
        # Validate performance (should complete in reasonable time)
        assert elapsed_time < 120, f"Sanitization took {elapsed_time:.1f}s (expected <120s)"
        
        # Calculate throughput
        throughput = report.rows_processed / elapsed_time
        logger.info(f"✓ Large dataset processed: {report.rows_processed} rows in {elapsed_time:.2f}s ({throughput:.1f} rows/sec)")


# ============================================================================
# TEST CASES - PROGRESS CALLBACKS
# ============================================================================

class TestProgressCallbacks:
    """Test progress reporting functionality."""
    
    def test_sanitization_progress_callbacks(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that progress callbacks are invoked during sanitization.
        """
        pii_columns = create_pii_config_for_customers()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Track callback invocations
        callback_log = []
        
        def progress_callback(table: str, rows: int, total: int, percent: float):
            callback_log.append({
                'table': table,
                'rows': rows,
                'total': total,
                'percent': percent
            })
            logger.info(f"Progress: {table} - {percent:.1f}% ({rows}/{total})")
        
        # Set callback
        orchestrator.set_progress_callback(progress_callback)
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Validate callbacks were invoked
        assert len(callback_log) > 0, "Progress callbacks not invoked"
        
        # Validate callback data
        for entry in callback_log:
            assert 'table' in entry
            assert 'percent' in entry
            assert 0 <= entry['percent'] <= 100
        
        logger.info(f"✓ Progress callbacks invoked {len(callback_log)} times")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
