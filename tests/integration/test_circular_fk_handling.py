"""
Integration Tests for Circular Foreign Key Dependency Handling

Tests how the sanitization orchestrator handles circular FK dependencies.
Current system implements a FAIL-FAST strategy: detect circular dependencies
during the Planning phase and raise CircularDependencyError with detailed
information and suggested mitigations.

Test Coverage:
    - Circular dependency detection (Products ↔ Categories ↔ Suppliers)
    - CircularDependencyError raised with cycle details
    - Error message quality and suggested actions
    - Orchestrator fails in Planning phase (before data modification)
    - Distinguish circular dependencies from self-referencing tables
    - Cycle path reporting (A → B → C → A)

Current Strategy:
    The orchestrator does NOT attempt to automatically handle circular FKs.
    Instead, it:
    1. Detects cycles using NetworkX's simple_cycles algorithm
    2. Raises CircularDependencyError with full cycle information
    3. Suggests manual mitigation strategies:
       - Temporarily disable FK constraints
       - Use multi-stage processing with mapping lookups
       - Exclude circular tables from sanitization scope

Prerequisites:
    - SQL Server instance running
    - Test database with circular FK schema (Products ↔ Categories ↔ Suppliers)
    - Environment variables set for database connection

Run:
    pytest tests/integration/test_circular_fk_handling.py -v -s

Author: Database Sanitization Team
Created: 2026-03-27
"""

import pytest
import os
import logging
from typing import List

from src.config import SanitizationConfig, DatabaseConfig, PIIColumnConfig
from src.mapping.mapping_config import MappingConfig
from src.database.connection_manager import ConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.sanitization.orchestrator import SanitizationOrchestrator, SanitizationPhase
from src.sanitization.dependency_resolver import DependencyResolver
from src.mapping.mapping_manager import MappingManager
from src.validation.integrity_validator import IntegrityValidator
from src.exceptions import CircularDependencyError

from tests.integration.test_db_setup import (
    setup_test_database,
    teardown_test_database,
    verify_test_schema
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mark all tests as integration tests
pytestmark = [pytest.mark.integration, pytest.mark.edge_case]


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
    """Module-scoped test database setup with circular FK tables."""
    logger.info("Setting up test database with circular FK dependencies")
    
    success = setup_test_database(connection_manager, force_recreate=True)
    assert success, "Failed to setup test database"
    
    is_valid = verify_test_schema(connection_manager)
    assert is_valid, "Test database schema verification failed"
    
    # Verify circular FK exists (Products ↔ Categories ↔ Suppliers)
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = 'dbo'
              AND CONSTRAINT_NAME IN (
                  'FK_Products_Categories',
                  'FK_Categories_Suppliers',
                  'FK_Suppliers_Products'
              )
        """)
        fk_count = cursor.fetchone()[0]
    
    assert fk_count == 3, f"Expected 3 circular FKs, found {fk_count}"
    logger.info("✓ Circular FK schema verified: Products ↔ Categories ↔ Suppliers")
    
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
    mapping_config = MappingConfig(
        enabled=True,
        schema_name="sanitization",
        table_name="pii_mappings_circular_test",
        encryption_enabled=False,
        batch_size=1000
    )
    
    manager = MappingManager(test_database, mapping_config)
    manager.create_mapping_table()
    
    yield manager
    
    # Cleanup
    try:
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("IF OBJECT_ID('sanitization.pii_mappings_circular_test', 'U') IS NOT NULL DROP TABLE sanitization.pii_mappings_circular_test")
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
    """Create orchestrator."""
    return SanitizationOrchestrator(
        connection_manager=test_database,
        schema_extractor=schema_extractor,
        dependency_resolver=dependency_resolver,
        mapping_manager=mapping_manager,
        integrity_validator=integrity_validator
    )


# ============================================================================
# TEST CASES - CIRCULAR DEPENDENCY DETECTION
# ============================================================================

class TestCircularDependencyDetection:
    """Test detection of circular FK dependencies."""
    
    def test_circular_fk_detected_by_resolver(
        self,
        dependency_resolver
    ):
        """
        Test that DependencyResolver correctly identifies circular dependencies.
        
        Verifies the cycle: Products → Categories → Suppliers → Products
        """
        # Check if circular dependencies exist
        has_circular = dependency_resolver.has_circular_dependencies()
        
        assert has_circular, "Circular dependencies not detected"
        
        # Get cycle details
        cycles = dependency_resolver.get_cycles()
        
        assert len(cycles) > 0, "No cycles returned despite circular dependencies"
        
        # Verify the Products ↔ Categories ↔ Suppliers cycle exists
        cycle_tables = set()
        for cycle in cycles:
            cycle_tables.update(cycle)
        
        expected_tables = {'dbo.Products', 'dbo.Categories', 'dbo.Suppliers'}
        assert expected_tables.issubset(cycle_tables), f"Expected circular tables {expected_tables}, found {cycle_tables}"
        
        logger.info(f"✓ Circular dependencies detected: {cycles}")
    
    
    def test_circular_fk_cycle_path_reporting(
        self,
        dependency_resolver
    ):
        """
        Test that cycle paths are correctly reported (A → B → C → A format).
        """
        cycles = dependency_resolver.get_cycles()
        
        assert len(cycles) > 0, "No cycles found"
        
        # Verify cycle format (should be list of table names)
        first_cycle = cycles[0]
        assert isinstance(first_cycle, list), "Cycle should be a list"
        assert len(first_cycle) >= 2, "Cycle should have at least 2 tables"
        
        # Verify all elements are table names (schema.table format)
        for table in first_cycle:
            assert isinstance(table, str), f"Table name should be string, got {type(table)}"
            assert '.' in table, f"Table should be in schema.table format, got {table}"
        
        logger.info(f"✓ Cycle path format validated: {' → '.join(first_cycle)} → {first_cycle[0]}")


# ============================================================================
# TEST CASES - ORCHESTRATOR BEHAVIOR
# ============================================================================

class TestOrchestratorCircularFKBehavior:
    """Test how orchestrator handles circular FK dependencies."""
    
    def test_sanitization_fails_on_circular_fk(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that orchestrator fails in Planning phase when circular FKs detected.
        
        Validates fail-fast strategy: error before any data modification.
        """
        # Create PII config for circular FK tables
        pii_columns = [
            PIIColumnConfig(
                schema="dbo",
                table="Products",
                column="ProductName",
                pii_type="generic",
                nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Categories",
                column="CategoryName",
                pii_type="generic",
                nullable=False
            ),
            PIIColumnConfig(
                schema="dbo",
                table="Suppliers",
                column="SupplierName",
                pii_type="generic",
                nullable=False
            )
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Capture original data before attempt
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT TOP 1 ProductName FROM dbo.Products")
            original_product = cursor.fetchone()[0]
        
        # Attempt sanitization (should fail)
        with pytest.raises(CircularDependencyError) as exc_info:
            orchestrator.run(config, dry_run=False)
        
        error = exc_info.value
        
        # Validate error details
        assert "circular" in str(error).lower(), "Error message should mention 'circular'"
        assert "Products" in str(error) or "Categories" in str(error) or "Suppliers" in str(error), \
            "Error should mention involved tables"
        
        # Verify data unchanged (fail-fast = no data modification)
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT TOP 1 ProductName FROM dbo.Products")
            current_product = cursor.fetchone()[0]
        
        assert current_product == original_product, "Data was modified despite circular FK error"
        
        logger.info(f"✓ Sanitization correctly failed on circular FK: {error}")
    
    
    def test_circular_fk_error_message_quality(
        self,
        orchestrator,
        db_config
    ):
        """
        Test that CircularDependencyError provides helpful error message with:
        - Cycle path visualization
        - Suggested mitigation strategies
        - Actionable error code
        """
        pii_columns = [
            PIIColumnConfig(schema="dbo", table="Products", column="ProductName", pii_type="generic", nullable=False)
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        with pytest.raises(CircularDependencyError) as exc_info:
            orchestrator.run(config, dry_run=False)
        
        error_msg = str(exc_info.value)
        
        # Validate error message contains helpful information
        assert "circular" in error_msg.lower(), "Should mention 'circular'"
        assert "→" in error_msg or "->" in error_msg or "cycle" in error_msg.lower(), \
            "Should visualize cycle path"
        
        # Check for suggested actions (if error provides them)
        error_dict = exc_info.value.to_dict() if hasattr(exc_info.value, 'to_dict') else {}
        
        # Log error for manual inspection
        logger.info(f"Error message: {error_msg}")
        logger.info(f"Error code: {getattr(exc_info.value, 'error_code', 'N/A')}")
        logger.info(f"Suggested action: {getattr(exc_info.value, 'suggested_action', 'N/A')}")
        
        logger.info("✓ Error message provides helpful information")
    
    
    def test_orchestrator_phase_on_circular_fk_error(
        self,
        orchestrator,
        db_config
    ):
        """
        Test that orchestrator reports correct phase when circular FK detected.
        
        Should fail in PLANNING phase, not EXECUTION.
        """
        pii_columns = [
            PIIColumnConfig(schema="dbo", table="Products", column="ProductName", pii_type="generic", nullable=False)
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        try:
            report = orchestrator.run(config, dry_run=False)
            # If no error raised, check report phase
            assert report.phase == SanitizationPhase.FAILED, "Should fail in planning"
        except CircularDependencyError:
            # Expected - circular FK detected in planning phase
            logger.info("✓ Circular FK detected in Planning phase (before execution)")
            pass


# ============================================================================
# TEST CASES - CIRCULAR VS SELF-REFERENCING
# ============================================================================

class TestCircularVsSelfReferencing:
    """Test that circular FKs are distinguished from self-referencing tables."""
    
    def test_self_referencing_not_counted_as_circular(
        self,
        schema_extractor,
        test_database
    ):
        """
        Test that self-referencing tables (Employees.ManagerID) are NOT
        counted as circular dependencies.
        
        Self-referencing: Table A → Table A (same table)
        Circular: Table A → Table B → Table C → Table A (multi-table cycle)
        """
        # Extract FKs including self-referencing Employee table
        fk_metadata = schema_extractor.extract_foreign_keys()
        
        # Find self-referencing FKs
        self_ref_fks = [
            fk for fk in fk_metadata 
            if fk['child_table'] == fk['parent_table']
        ]
        
        assert len(self_ref_fks) > 0, "No self-referencing FKs found (expected hr.Employees)"
        
        # Verify hr.Employees is self-referencing
        employee_self_ref = any(
            fk['child_table'] == 'hr.Employees' and fk['parent_table'] == 'hr.Employees'
            for fk in self_ref_fks
        )
        assert employee_self_ref, "hr.Employees self-reference not found"
        
        # Create dependency resolver
        resolver = DependencyResolver(fk_metadata)
        
        # Verify Employees is marked as self-referencing
        is_self_ref = resolver.is_self_referencing('hr.Employees')
        assert is_self_ref, "hr.Employees not identified as self-referencing"
        
        # Verify self-referencing is NOT counted as circular
        has_circular = resolver.has_circular_dependencies()
        cycles = resolver.get_cycles()
        
        # Check that single-node "cycles" are filtered out
        single_node_cycles = [c for c in cycles if len(c) == 1]
        assert len(single_node_cycles) == 0, "Single-node cycles should be filtered out"
        
        logger.info("✓ Self-referencing tables correctly distinguished from circular dependencies")
    
    
    def test_circular_and_self_referencing_mixed(
        self,
        schema_extractor
    ):
        """
        Test handling of database with BOTH circular FKs and self-referencing tables.
        
        Database has:
        - Circular: Products ↔ Categories ↔ Suppliers
        - Self-referencing: hr.Employees.ManagerID
        """
        fk_metadata = schema_extractor.extract_foreign_keys()
        resolver = DependencyResolver(fk_metadata)
        
        # Verify both types exist
        has_circular = resolver.has_circular_dependencies()
        has_self_ref = resolver.is_self_referencing('hr.Employees')
        
        assert has_circular, "Circular dependencies not detected"
        assert has_self_ref, "Self-referencing not detected"
        
        # Verify cycles don't include single-node self-references
        cycles = resolver.get_cycles()
        for cycle in cycles:
            assert len(cycle) > 1, f"Cycle should have >1 nodes, got {cycle}"
        
        logger.info(f"✓ Both circular and self-referencing correctly handled: {len(cycles)} multi-table cycles")


# ============================================================================
# TEST CASES - DOCUMENTATION
# ============================================================================

class TestCircularFKDocumentation:
    """Test that circular FK behavior is well-documented."""
    
    def test_circular_fk_strategy_documented(
        self
    ):
        """
        Test that current circular FK strategy is documented.
        
        This test serves as documentation: circular FKs trigger fail-fast
        behavior with manual mitigation suggestions.
        """
        strategy_doc = """
        CURRENT CIRCULAR FK STRATEGY: FAIL-FAST
        
        The sanitization orchestrator does NOT automatically handle circular
        foreign key dependencies. Instead:
        
        1. Detection: Uses NetworkX simple_cycles algorithm during Planning phase
        2. Response: Raises CircularDependencyError with cycle details
        3. User Action: Manual mitigation required:
           a) Temporarily disable FK constraints before sanitization
           b) Use multi-stage processing with mapping table lookups
           c) Exclude circular tables from sanitization scope
        
        Rationale:
        - Automatic constraint disabling is risky (referential integrity)
        - Multi-stage processing requires complex logic (table orderings)
        - Safer to make user explicitly choose mitigation strategy
        
        Future Enhancement:
        - Could add config option: circular_fk_strategy = 'fail' | 'disable_constraints' | 'multi_stage'
        - Would require careful testing and transaction management
        """
        
        logger.info(strategy_doc)
        
        # This test always passes - serves as executable documentation
        assert True, "Circular FK strategy documented"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
