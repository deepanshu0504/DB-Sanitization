"""
End-to-End Integration Tests for Desensitization (Restore) Workflow

Tests the complete desensitization workflow: sanitize data, store mappings,
then restore original values. Validates mapping retrieval, decryption,
FK-aware ordering, and integrity verification.

Test Coverage:
    - Full roundtrip: sanitize → store mappings → restore → verify
    - Partial restoration (specific tables only)
    - Encryption/decryption roundtrip
    - FK dependency order (child → parent restore)
    - Large mapping sets (100+ entries)
    - Dry-run validation
    - Error handling (missing operation ID, missing encryption key)
    - Post-restore integrity verification

Prerequisites:
    - SQL Server instance running
    - Test database created (run test_db_setup.py setup)
    - Environment variables set for database connection

Run:
    pytest tests/integration/test_end_to_end_desensitization.py -v -s

Author: Database Sanitization Team
Created: 2026-03-27
"""

import pytest
import os
import uuid
import logging
from typing import List, Dict, Any

from src.config import SanitizationConfig, DatabaseConfig, PIIColumnConfig, LoggingConfig
from src.mapping.mapping_config import MappingConfig
from src.database.connection_manager import ConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.sanitization.orchestrator import SanitizationOrchestrator
from src.sanitization.desensitizer import Desensitizer, RestorePhase
from src.sanitization.dependency_resolver import DependencyResolver
from src.mapping.mapping_manager import MappingManager
from src.mapping.encryption_utils import EncryptionManager
from src.validation.integrity_validator import IntegrityValidator
from src.exceptions import DesensitizationError

from tests.integration.test_db_setup import (
    setup_test_database,
    teardown_test_database,
    verify_test_schema
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
    logger.info("Setting up test database for desensitization tests")
    
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
    """Create mapping manager with test configuration."""
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings_desentization_test",
        encryption_enabled=False,
        batch_size=1000,
        index_creation=True,
        transactional=True
    )
    
    manager = MappingManager(test_database, mapping_config)
    manager.create_mapping_table()
    
    yield manager
    
    # Cleanup
    try:
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("IF OBJECT_ID('sanitization.pii_mappings_desentization_test', 'U') IS NOT NULL DROP TABLE sanitization.pii_mappings_desentization_test")
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
    """Create orchestrator for sanitization."""
    return SanitizationOrchestrator(
        connection_manager=test_database,
        schema_extractor=schema_extractor,
        dependency_resolver=dependency_resolver,
        mapping_manager=mapping_manager,
        integrity_validator=integrity_validator
    )


@pytest.fixture
def desensitizer(test_database, mapping_manager) -> Desensitizer:
    """Create desensitizer for restoration."""
    return Desensitizer(
        connection_manager=test_database,
        mapping_manager=mapping_manager
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_sample_values(
    connection_manager: ConnectionManager,
    schema: str,
    table: str,
    column: str,
    limit: int = 5
) -> List[Any]:
    """Get sample values from a column."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT TOP {limit} [{column}] FROM [{schema}].[{table}] WHERE [{column}] IS NOT NULL ORDER BY 1"
        )
        values = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return values


def create_basic_pii_config() -> List[PIIColumnConfig]:
    """Create basic PII configuration for Customers table."""
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
        )
    ]


# ============================================================================
# TEST CASES - BASIC ROUNDTRIP
# ============================================================================

class TestFullRoundtripWorkflow:
    """Test complete sanitize → restore roundtrip."""
    
    def test_full_desensitization_roundtrip(
        self,
        test_database,
        orchestrator,
        desensitizer,
        db_config
    ):
        """
        Test full roundtrip: sanitize data, store mappings, restore original values.
        
        Validates that restored data exactly matches pre-sanitization values.
        """
        pii_columns = create_basic_pii_config()
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Capture original values before sanitization
        original_emails = get_sample_values(test_database, "sales", "Customers", "Email", 10)
        original_phones = get_sample_values(test_database, "sales", "Customers", "Phone", 10)
        original_first_names = get_sample_values(test_database, "sales", "Customers", "FirstName", 10)
        
        logger.info(f"Original samples: {len(original_emails)} emails, {len(original_phones)} phones, {len(original_first_names)} names")
        
        # Execute sanitization
        sanitize_report = orchestrator.run(config, dry_run=False)
        assert sanitize_report.overall_status == "COMPLETED"
        assert sanitize_report.mappings_stored > 0
        
        operation_id = sanitize_report.operation_id
        logger.info(f"Sanitization complete: operation_id={operation_id}, mappings={sanitize_report.mappings_stored}")
        
        # Verify data was masked
        masked_emails = get_sample_values(test_database, "sales", "Customers", "Email", 10)
        assert masked_emails != original_emails, "Data was not masked"
        
        # Execute desensitization (restore)
        restore_report = desensitizer.restore(operation_id, dry_run=False)
        
        # Validate restore report
        assert restore_report.phase == RestorePhase.COMPLETED
        assert restore_report.tables_restored > 0
        assert restore_report.rows_restored > 0
        
        logger.info(f"Restoration complete: {restore_report.tables_restored} tables, {restore_report.rows_restored} rows")
        
        # Verify original values restored
        restored_emails = get_sample_values(test_database, "sales", "Customers", "Email", 10)
        restored_phones = get_sample_values(test_database, "sales", "Customers", "Phone", 10)
        restored_first_names = get_sample_values(test_database, "sales", "Customers", "FirstName", 10)
        
        assert restored_emails == original_emails, f"Emails not restored correctly: {original_emails[:3]} vs {restored_emails[:3]}"
        assert restored_phones == original_phones, "Phones not restored correctly"
        assert restored_first_names == original_first_names, "First names not restored correctly"
        
        logger.info("✓ Full roundtrip successful: all original values restored")
    
    
    def test_desensitization_fk_dependency_order(
        self,
        test_database,
        orchestrator,
        desensitizer,
        db_config
    ):
        """
        Test that desensitization respects FK dependencies (child → parent order).
        
        Restores Orders before Customers to avoid FK violations.
        """
        # Create config for both parent (Customers) and child (Orders)
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
        sanitize_report = orchestrator.run(config, dry_run=False)
        assert sanitize_report.overall_status == "COMPLETED"
        
        # Restore
        restore_report = desensitizer.restore(sanitize_report.operation_id, dry_run=False)
        
        # Validate restoration completed (implicit FK order validation)
        assert restore_report.phase == RestorePhase.COMPLETED
        assert restore_report.tables_restored == 2  # Both tables
        
        # Verify no FK violations (query would fail if orphans exist)
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) 
                FROM sales.Orders o
                WHERE o.CustomerID IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM sales.Customers c WHERE c.CustomerID = o.CustomerID)
            """)
            orphan_count = cursor.fetchone()[0]
        
        assert orphan_count == 0, f"FK violations after restore: {orphan_count} orphaned orders"
        logger.info("✓ FK dependency order preserved during restoration")


# ============================================================================
# TEST CASES - PARTIAL RESTORATION
# ============================================================================

class TestPartialRestoration:
    """Test selective restoration of specific tables."""
    
    def test_partial_desensitization_specific_tables(
        self,
        test_database,
        orchestrator,
        desensitizer,
        db_config
    ):
        """
        Test restoring only specific tables (not all tables in operation).
        """
        # Create config for 2 tables
        pii_columns = [
            PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="sales", table="Customers", column="Phone", pii_type="phone", nullable=True),
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Capture original values for both tables
        original_customer_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
        original_employee_emails = get_sample_values(test_database, "hr", "Employees", "Email", 5)
        
        # Sanitize both tables
        sanitize_report = orchestrator.run(config, dry_run=False)
        assert sanitize_report.overall_status == "COMPLETED"
        
        # Verify both tables masked
        masked_customer_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
        masked_employee_emails = get_sample_values(test_database, "hr", "Employees", "Email", 5)
        assert masked_customer_emails != original_customer_emails
        assert masked_employee_emails != original_employee_emails
        
        # Restore ONLY Customers table
        restore_report = desensitizer.restore(
            sanitize_report.operation_id,
            tables=["sales.Customers"],
            dry_run=False
        )
        
        # Validate only 1 table restored
        assert restore_report.tables_restored == 1
        assert "sales.Customers" in str(restore_report.tables_processed)
        
        # Verify Customers restored but Employees still masked
        restored_customer_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
        still_masked_employee_emails = get_sample_values(test_database, "hr", "Employees", "Email", 5)
        
        assert restored_customer_emails == original_customer_emails, "Customers not restored"
        assert still_masked_employee_emails == masked_employee_emails, "Employees should still be masked"
        
        logger.info("✓ Partial restoration successful: only specified table restored")


# ============================================================================
# TEST CASES - ENCRYPTION
# ============================================================================

class TestEncryptionRoundtrip:
    """Test desensitization with encrypted mappings."""
    
    def test_desensitization_with_encryption(
        self,
        test_database,
        db_config,
        schema_extractor,
        dependency_resolver,
        integrity_validator
    ):
        """
        Test encryption/decryption roundtrip during sanitization and restoration.
        """
        # Generate encryption key
        encryption_key = EncryptionManager.generate_key()
        os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = encryption_key
        
        try:
            # Create mapping manager with encryption enabled
            mapping_config = MappingConfig(
                enabled=True,
                schema_name="sanitization",
                table_name="pii_mappings_encrypted_test",
                encryption_enabled=True,  # Enable encryption
                batch_size=1000
            )
            
            mapping_manager = MappingManager(test_database, mapping_config)
            mapping_manager.create_mapping_table()
            
            # Create orchestrator with encrypted mapping
            orchestrator = SanitizationOrchestrator(
                connection_manager=test_database,
                schema_extractor=schema_extractor,
                dependency_resolver=dependency_resolver,
                mapping_manager=mapping_manager,
                integrity_validator=integrity_validator
            )
            
            # Create desensitizer
            desensitizer = Desensitizer(
                connection_manager=test_database,
                mapping_manager=mapping_manager
            )
            
            # Capture original values
            original_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
            
            # Sanitize with encryption
            pii_columns = [
                PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False)
            ]
            config = SanitizationConfig(
                database=db_config,
                pii_columns=pii_columns,
                mapping=mapping_config
            )
            
            sanitize_report = orchestrator.run(config, dry_run=False)
            assert sanitize_report.overall_status == "COMPLETED"
            
            # Verify mappings are encrypted in database
            with test_database.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT TOP 1 original_value_encrypted 
                    FROM sanitization.pii_mappings_encrypted_test
                    WHERE original_value_encrypted IS NOT NULL
                """)
                encrypted_value = cursor.fetchone()
                assert encrypted_value is not None, "No encrypted values found"
            
            # Restore (decrypt)
            restore_report = desensitizer.restore(sanitize_report.operation_id, dry_run=False)
            assert restore_report.phase == RestorePhase.COMPLETED
            
            # Verify original values restored
            restored_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
            assert restored_emails == original_emails, "Decryption failed"
            
            logger.info("✓ Encryption/decryption roundtrip successful")
            
        finally:
            # Cleanup
            del os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY']
            try:
                with test_database.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("IF OBJECT_ID('sanitization.pii_mappings_encrypted_test', 'U') IS NOT NULL DROP TABLE sanitization.pii_mappings_encrypted_test")
                    conn.commit()
            except:
                pass


# ============================================================================
# TEST CASES - VALIDATION & ERROR HANDLING
# ============================================================================

class TestValidationAndErrors:
    """Test validation and error handling in desensitization."""
    
    def test_desensitization_dry_run_validation(
        self,
        test_database,
        orchestrator,
        desensitizer,
        db_config
    ):
        """
        Test dry-run mode validates without actually restoring data.
        """
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Sanitize
        sanitize_report = orchestrator.run(config, dry_run=False)
        assert sanitize_report.overall_status == "COMPLETED"
        
        # Get masked values
        masked_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
        
        # Dry-run restore
        restore_report = desensitizer.restore(sanitize_report.operation_id, dry_run=True)
        
        # Validate report shows validation phase
        assert restore_report.phase in [RestorePhase.VALIDATION, RestorePhase.PLANNING]
        
        # Verify data NOT restored (still masked)
        still_masked_emails = get_sample_values(test_database, "sales", "Customers", "Email", 5)
        assert still_masked_emails == masked_emails, "Data was modified in dry-run mode"
        
        logger.info("✓ Dry-run mode validated without modifying data")
    
    
    def test_desensitization_missing_operation_id(
        self,
        desensitizer
    ):
        """
        Test error handling for invalid operation ID.
        """
        fake_operation_id = uuid.uuid4()
        
        with pytest.raises(DesensitizationError) as exc_info:
            desensitizer.restore(fake_operation_id, dry_run=False)
        
        assert "operation" in str(exc_info.value).lower() or "not found" in str(exc_info.value).lower()
        logger.info("✓ Missing operation ID handled correctly")
    
    
    def test_post_restore_integrity_verification(
        self,
        test_database,
        orchestrator,
        desensitizer,
        db_config
    ):
        """
        Test that integrity checks pass after restoration.
        """
        pii_columns = create_basic_pii_config()
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Capture pre-sanitization row count
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sales.Customers")
            pre_count = cursor.fetchone()[0]
        
        # Sanitize and restore
        sanitize_report = orchestrator.run(config, dry_run=False)
        restore_report = desensitizer.restore(sanitize_report.operation_id, dry_run=False)
        
        # Verify row count unchanged
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sales.Customers")
            post_count = cursor.fetchone()[0]
        
        assert pre_count == post_count, f"Row count changed: {pre_count} → {post_count}"
        
        # Verify FK integrity
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) 
                FROM sales.Orders o
                WHERE o.CustomerID IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM sales.Customers c WHERE c.CustomerID = o.CustomerID)
            """)
            orphan_count = cursor.fetchone()[0]
        
        assert orphan_count == 0, f"FK violations after restore: {orphan_count} orphans"
        logger.info("✓ Post-restore integrity checks passed")


# ============================================================================
# TEST CASES - LARGE DATASETS
# ============================================================================

class TestLargeDatasetRestoration:
    """Test desensitization with large mapping sets."""
    
    def test_large_mapping_set_restoration(
        self,
        test_database,
        orchestrator,
        desensitizer,
        db_config
    ):
        """
        Test restoration from large mapping sets (100+ entries).
        """
        # Create config for multiple columns across multiple tables
        pii_columns = [
            PIIColumnConfig(schema="sales", table="Customers", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="sales", table="Customers", column="Phone", pii_type="phone", nullable=True),
            PIIColumnConfig(schema="sales", table="Customers", column="FirstName", pii_type="name", nullable=False),
            PIIColumnConfig(schema="sales", table="Customers", column="LastName", pii_type="name", nullable=False),
            PIIColumnConfig(schema="sales", table="Orders", column="ShipToName", pii_type="name", nullable=True),
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True, batch_size=50)  # Small batches
        )
        
        # Sanitize (creates many mappings)
        sanitize_report = orchestrator.run(config, dry_run=False)
        assert sanitize_report.overall_status == "COMPLETED"
        assert sanitize_report.mappings_stored > 100, f"Expected >100 mappings, got {sanitize_report.mappings_stored}"
        
        logger.info(f"Created {sanitize_report.mappings_stored} mappings")
        
        import time
        start_time = time.time()
        
        # Restore
        restore_report = desensitizer.restore(sanitize_report.operation_id, dry_run=False)
        
        elapsed_time = time.time() - start_time
        
        # Validate
        assert restore_report.phase == RestorePhase.COMPLETED
        assert restore_report.rows_restored > 100
        
        # Performance check (should complete in reasonable time)
        assert elapsed_time < 60, f"Restoration took {elapsed_time:.1f}s (expected <60s)"
        
        throughput = restore_report.rows_restored / elapsed_time
        logger.info(f"✓ Large dataset restored: {restore_report.rows_restored} rows in {elapsed_time:.2f}s ({throughput:.1f} rows/sec)")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
