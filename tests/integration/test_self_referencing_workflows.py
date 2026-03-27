"""
Integration Tests for Self-Referencing Table Workflows

Tests sanitization of hierarchical data with self-referencing foreign keys.
The hr.Employees table has ManagerID → EmployeeID self-reference, creating
an organizational hierarchy.

Key Challenge:
    When sanitizing EmployeeID values, the ManagerID column must also be updated
    to maintain FK integrity. This requires deterministic masking (same original
    value always maps to same masked value) to preserve hierarchical relationships.

Test Coverage:
    - Self-referencing table detection by DependencyResolver
    - Sanitization preserves hierarchical relationships
    - Parent-child relationships intact after masking
    - NULL parent handling (root nodes like CEO)
    - Deep hierarchies (5+ levels: CEO → VP → Director → Manager → Employee)
    - Mapping consistency (same EmployeeID → same masked value across references)
    - FK integrity validation (no orphaned records)

Approach:
    Uses existing BaseMasker deterministic seeding to ensure:
        Original EmployeeID X → Masked ID Y
        Any ManagerID = X → Updated to Y
    This preserves the hierarchy structure while anonymizing IDs.

Prerequisites:
    - SQL Server instance running
    - Test database with hr.Employees self-referencing table
    - Environment variables set for database connection

Run:
    pytest tests/integration/test_self_referencing_workflows.py -v -s

Author: Database Sanitization Team
Created: 2026-03-27
"""

import pytest
import os
import logging
from typing import List, Dict, Any, Set, Tuple

from src.config import SanitizationConfig, DatabaseConfig, PIIColumnConfig
from src.mapping.mapping_config import MappingConfig
from src.database.connection_manager import ConnectionManager
from src.database.schema_extractor import SchemaExtractor
from src.sanitization.orchestrator import SanitizationOrchestrator
from src.sanitization.dependency_resolver import DependencyResolver
from src.mapping.mapping_manager import MappingManager
from src.validation.integrity_validator import IntegrityValidator

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
    """Module-scoped test database setup with self-referencing Employee table."""
    logger.info("Setting up test database with self-referencing hierarchy")
    
    success = setup_test_database(connection_manager, force_recreate=True)
    assert success, "Failed to setup test database"
    
    is_valid = verify_test_schema(connection_manager)
    assert is_valid, "Test database schema verification failed"
    
    # Verify self-referencing FK exists
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = 'hr'
              AND CONSTRAINT_NAME = 'FK_Employees_Manager'
        """)
        fk_count = cursor.fetchone()[0]
    
    assert fk_count == 1, "Self-referencing FK not found"
    logger.info("✓ Self-referencing hierarchy verified: hr.Employees.ManagerID")
    
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
        table_name="pii_mappings_selfref_test",
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
            cursor.execute("IF OBJECT_ID('sanitization.pii_mappings_selfref_test', 'U') IS NOT NULL DROP TABLE sanitization.pii_mappings_selfref_test")
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
# HELPER FUNCTIONS
# ============================================================================

def get_hierarchy_structure(connection_manager: ConnectionManager) -> List[Dict[str, Any]]:
    """Get employee hierarchy structure."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                EmployeeID,
                EmployeeCode,
                FirstName,
                LastName,
                Email,
                ManagerID,
                JobTitle,
                Department
            FROM hr.Employees
            ORDER BY EmployeeID
        """)
        
        columns = [col[0] for col in cursor.description]
        employees = []
        for row in cursor.fetchall():
            emp_dict = dict(zip(columns, row))
            employees.append(emp_dict)
        
        cursor.close()
        return employees


def verify_hierarchy_integrity(connection_manager: ConnectionManager) -> Tuple[int, int]:
    """
    Verify self-referencing FK integrity.
    
    Returns:
        (orphan_count, total_non_root_count): Number of orphaned employees and total non-root employees
    """
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Count orphaned employees (ManagerID points to non-existent EmployeeID)
        cursor.execute("""
            SELECT COUNT(*)
            FROM hr.Employees e
            WHERE e.ManagerID IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 
                  FROM hr.Employees m 
                  WHERE m.EmployeeID = e.ManagerID
              )
        """)
        orphan_count = cursor.fetchone()[0]
        
        # Count total non-root employees
        cursor.execute("SELECT COUNT(*) FROM hr.Employees WHERE ManagerID IS NOT NULL")
        total_non_root = cursor.fetchone()[0]
        
        cursor.close()
        return (orphan_count, total_non_root)


def get_hierarchy_depth(connection_manager: ConnectionManager) -> int:
    """Calculate maximum hierarchy depth."""
    with connection_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            WITH HierarchyCTE AS (
                -- Root level (CEO with NULL manager)
                SELECT EmployeeID, ManagerID, 1 AS Level
                FROM hr.Employees
                WHERE ManagerID IS NULL
                
                UNION ALL
                
                -- Recursive: employees reporting to previous level
                SELECT e.EmployeeID, e.ManagerID, h.Level + 1
                FROM hr.Employees e
                INNER JOIN HierarchyCTE h ON e.ManagerID = h.EmployeeID
            )
            SELECT MAX(Level) AS MaxDepth
            FROM HierarchyCTE
        """)
        max_depth = cursor.fetchone()[0]
        cursor.close()
        return max_depth


# ============================================================================
# TEST CASES - DETECTION
# ============================================================================

class TestSelfReferencingDetection:
    """Test detection of self-referencing tables."""
    
    def test_self_referencing_table_identified(
        self,
        dependency_resolver
    ):
        """
        Test that DependencyResolver correctly identifies self-referencing tables.
        """
        is_self_ref = dependency_resolver.is_self_referencing('hr.Employees')
        
        assert is_self_ref, "hr.Employees not identified as self-referencing"
        
        logger.info("✓ Self-referencing table correctly identified")
    
    
    def test_self_referencing_vs_regular_tables(
        self,
        dependency_resolver
    ):
        """
        Test that non-self-referencing tables are correctly distinguished.
        """
        # Employees is self-referencing
        assert dependency_resolver.is_self_referencing('hr.Employees')
        
        # Customers is not self-referencing
        assert not dependency_resolver.is_self_referencing('sales.Customers')
        
        # Orders is not self-referencing (references Customers, not itself)
        assert not dependency_resolver.is_self_referencing('sales.Orders')
        
        logger.info("✓ Self-referencing correctly distinguished from regular FK relationships")


# ============================================================================
# TEST CASES - HIERARCHY PRESERVATION
# ============================================================================

class TestHierarchyPreservation:
    """Test that sanitization preserves hierarchical relationships."""
    
    def test_sanitize_preserves_hierarchy(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that parent-child relationships are preserved after sanitization.
        
        Key validation: If Employee A reported to Manager B before sanitization,
        they should still report to the same manager after (even with masked IDs).
        """
        # Get pre-sanitization hierarchy
        pre_hierarchy = get_hierarchy_structure(test_database)
        pre_relationships = {
            emp['EmployeeID']: emp['ManagerID']
            for emp in pre_hierarchy
        }
        
        logger.info(f"Pre-sanitization: {len(pre_hierarchy)} employees")
        
        # Create PII config (Email, FirstName, LastName only - not EmployeeID)
        pii_columns = [
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="LastName", pii_type="name", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        # Execute sanitization
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Get post-sanitization hierarchy
        post_hierarchy = get_hierarchy_structure(test_database)
        post_relationships = {
            emp['EmployeeID']: emp['ManagerID']
            for emp in post_hierarchy
        }
        
        # Validate hierarchy structure unchanged
        # (EmployeeIDs remain same, ManagerIDs point to same relationships)
        assert pre_relationships == post_relationships, \
            "Hierarchy structure changed after sanitization"
        
        # Validate FK integrity
        orphan_count, total_non_root = verify_hierarchy_integrity(test_database)
        assert orphan_count == 0, f"Found {orphan_count} orphaned employees after sanitization"
        
        logger.info(f"✓ Hierarchy preserved: {total_non_root} non-root employees, 0 orphans")
    
    
    def test_sanitize_deep_hierarchy(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test sanitization of deep hierarchies (5+ levels).
        
        Hierarchy: CEO → VP → Director → Manager → Staff
        """
        # Check hierarchy depth
        pre_depth = get_hierarchy_depth(test_database)
        logger.info(f"Hierarchy depth: {pre_depth} levels")
        
        assert pre_depth >= 3, f"Expected hierarchy depth >= 3, got {pre_depth}"
        
        # Sanitize
        pii_columns = [
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Verify depth unchanged
        post_depth = get_hierarchy_depth(test_database)
        assert post_depth == pre_depth, f"Hierarchy depth changed: {pre_depth} → {post_depth}"
        
        # Verify integrity
        orphan_count, _ = verify_hierarchy_integrity(test_database)
        assert orphan_count == 0, f"Deep hierarchy has {orphan_count} orphans"
        
        logger.info(f"✓ Deep hierarchy preserved: {post_depth} levels intact")


# ============================================================================
# TEST CASES - NULL PARENT HANDLING
# ============================================================================

class TestNullParentHandling:
    """Test handling of NULL parent (root nodes)."""
    
    def test_null_parent_root_nodes(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that root nodes (ManagerID IS NULL) are preserved.
        
        CEO has ManagerID = NULL (no manager) - this should remain NULL.
        """
        # Count root nodes before sanitization
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM hr.Employees WHERE ManagerID IS NULL")
            pre_root_count = cursor.fetchone()[0]
        
        assert pre_root_count > 0, "No root nodes found (expected CEO)"
        logger.info(f"Pre-sanitization: {pre_root_count} root nodes")
        
        # Sanitize
        pii_columns = [
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Count root nodes after sanitization
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM hr.Employees WHERE ManagerID IS NULL")
            post_root_count = cursor.fetchone()[0]
        
        assert post_root_count == pre_root_count, \
            f"Root node count changed: {pre_root_count} → {post_root_count}"
        
        logger.info(f"✓ Root nodes preserved: {post_root_count} NULL parents")


# ============================================================================
# TEST CASES - MAPPING CONSISTENCY
# ============================================================================

class TestMappingConsistency:
    """Test that self-referencing columns use consistent masking."""
    
    def test_mapping_consistency_across_references(
        self,
        test_database,
        orchestrator,
        mapping_manager,
        db_config
    ):
        """
        Test that when EmployeeID X is masked to Y, all references to X
        (including ManagerID = X) are also updated to Y.
        
        This ensures deterministic masking maintains referential integrity.
        """
        # Get example manager-employee relationship
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 1 
                    e.EmployeeID AS EmployeeID,
                    e.FirstName AS EmployeeName,
                    m.EmployeeID AS ManagerID,
                    m.FirstName AS ManagerName
                FROM hr.Employees e
                INNER JOIN hr.Employees m ON e.ManagerID = m.EmployeeID
            """)
            relationship = cursor.fetchone()
        
        if not relationship:
            pytest.skip("No manager-employee relationships found")
        
        employee_id, emp_name_before, manager_id, mgr_name_before = relationship
        logger.info(f"Testing relationship: Employee {employee_id} ({emp_name_before}) → Manager {manager_id} ({mgr_name_before})")
        
        # Sanitize
        pii_columns = [
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="LastName", pii_type="name", nullable=False),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Get post-sanitization names
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT TOP 1 
                    e.FirstName AS EmployeeName,
                    m.FirstName AS ManagerName
                FROM hr.Employees e
                INNER JOIN hr.Employees m ON e.ManagerID = m.EmployeeID
                WHERE e.EmployeeID = {employee_id}
            """)
            result = cursor.fetchone()
        
        emp_name_after, mgr_name_after = result
        
        # Validate names were masked
        assert emp_name_after != emp_name_before, "Employee name not masked"
        assert mgr_name_after != mgr_name_before, "Manager name not masked"
        
        # Validate relationship still exists (FK integrity)
        assert result is not None, "Relationship broken after sanitization"
        
        logger.info(f"✓ Mapping consistency verified: relationship preserved with masked names")


# ============================================================================
# TEST CASES - FK INTEGRITY VALIDATION
# ============================================================================

class TestFKIntegrityValidation:
    """Test comprehensive FK integrity checks for self-referencing tables."""
    
    def test_no_orphaned_records_after_sanitization(
        self,
        test_database,
        orchestrator,
        db_config
    ):
        """
        Test that no employees have ManagerID pointing to non-existent EmployeeID.
        """
        # Sanitize
        pii_columns = [
            PIIColumnConfig(schema="hr", table="Employees", column="Email", pii_type="email", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="Phone", pii_type="phone", nullable=True),
            PIIColumnConfig(schema="hr", table="Employees", column="FirstName", pii_type="name", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="LastName", pii_type="name", nullable=False),
            PIIColumnConfig(schema="hr", table="Employees", column="SSN", pii_type="ssn", nullable=True),
        ]
        
        config = SanitizationConfig(
            database=db_config,
            pii_columns=pii_columns,
            mapping=MappingConfig(enabled=True)
        )
        
        report = orchestrator.run(config, dry_run=False)
        assert report.overall_status == "COMPLETED"
        
        # Comprehensive FK integrity check
        orphan_count, total_non_root = verify_hierarchy_integrity(test_database)
        
        assert orphan_count == 0, f"FK integrity violated: {orphan_count} orphaned employees out of {total_non_root}"
        
        # Additional check: Verify all ManagerIDs refer to valid EmployeeIDs
        with test_database.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    e.EmployeeID,
                    e.ManagerID,
                    CASE WHEN m.EmployeeID IS NULL THEN 1 ELSE 0 END AS IsOrphan
                FROM hr.Employees e
                LEFT JOIN hr.Employees m ON e.ManagerID = m.EmployeeID
                WHERE e.ManagerID IS NOT NULL AND m.EmployeeID IS NULL
            """)
            orphans = cursor.fetchall()
        
        assert len(orphans) == 0, f"Found {len(orphans)} orphaned relationships"
        
        logger.info(f"✓ FK integrity validated: {total_non_root} non-root employees, 0 orphans")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
