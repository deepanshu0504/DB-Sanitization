/*
================================================================================
DATABASE SANITIZATION FRAMEWORK - INTEGRATION TEST DATABASE TEARDOWN
================================================================================

Purpose: Clean up test database schema and data
Version: 1.0
Created: 2026-03-27

Features:
- Drops all FK constraints first (handles circular dependencies)
- Drops all tables in reverse dependency order
- Drops custom schemas (preserves dbo)
- Verifies cleanup completion

Usage:
    sqlcmd -S localhost -d SanitizationTest -i teardown_test_db.sql
    
    OR from Python:
    from tests.integration.test_db_setup import teardown_test_database
    teardown_test_database(connection_manager)

================================================================================
*/

SET NOCOUNT ON;
GO

PRINT '==================================================================';
PRINT 'Starting Test Database Teardown';
PRINT 'Database: ' + DB_NAME();
PRINT 'Time: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '==================================================================';
GO

-- ============================================================================
-- PHASE 1: DROP ALL FOREIGN KEY CONSTRAINTS
-- ============================================================================
PRINT '';
PRINT 'PHASE 1: Dropping Foreign Key Constraints...';
GO

-- Drop FKs in all test schemas
DECLARE @sql NVARCHAR(MAX) = '';

SELECT @sql = @sql + 
    'ALTER TABLE [' + s.name + '].[' + t.name + '] ' +
    'DROP CONSTRAINT [' + fk.name + ']; ' + CHAR(13)
FROM sys.foreign_keys fk
INNER JOIN sys.tables t ON fk.parent_object_id = t.object_id
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name IN ('dbo', 'sales', 'hr', 'archive')
ORDER BY s.name, t.name;

IF LEN(@sql) > 0
BEGIN
    EXEC sp_executesql @sql;
    PRINT '  ✓ Dropped all FK constraints';
END
ELSE
    PRINT '  - No FK constraints to drop';
GO

-- ============================================================================
-- PHASE 2: DROP ALL TABLES
-- ============================================================================
PRINT '';
PRINT 'PHASE 2: Dropping Tables...';
GO

-- Drop tables in explicit order (handles any dependency issues)
IF OBJECT_ID('sales.OrderLineItems', 'U') IS NOT NULL 
BEGIN
    DROP TABLE sales.OrderLineItems;
    PRINT '  ✓ Dropped table: sales.OrderLineItems';
END

IF OBJECT_ID('sales.OrderDetails', 'U') IS NOT NULL 
BEGIN
    DROP TABLE sales.OrderDetails;
    PRINT '  ✓ Dropped table: sales.OrderDetails';
END

IF OBJECT_ID('sales.Orders', 'U') IS NOT NULL 
BEGIN
    DROP TABLE sales.Orders;
    PRINT '  ✓ Dropped table: sales.Orders';
END

IF OBJECT_ID('sales.Customers', 'U') IS NOT NULL 
BEGIN
    DROP TABLE sales.Customers;
    PRINT '  ✓ Dropped table: sales.Customers';
END

IF OBJECT_ID('hr.Employees', 'U') IS NOT NULL 
BEGIN
    DROP TABLE hr.Employees;
    PRINT '  ✓ Dropped table: hr.Employees';
END

IF OBJECT_ID('dbo.Products', 'U') IS NOT NULL 
BEGIN
    DROP TABLE dbo.Products;
    PRINT '  ✓ Dropped table: dbo.Products';
END

IF OBJECT_ID('dbo.Categories', 'U') IS NOT NULL 
BEGIN
    DROP TABLE dbo.Categories;
    PRINT '  ✓ Dropped table: dbo.Categories';
END

IF OBJECT_ID('dbo.Suppliers', 'U') IS NOT NULL 
BEGIN
    DROP TABLE dbo.Suppliers;
    PRINT '  ✓ Dropped table: dbo.Suppliers';
END

IF OBJECT_ID('archive.ArchivedCustomers', 'U') IS NOT NULL 
BEGIN
    DROP TABLE archive.ArchivedCustomers;
    PRINT '  ✓ Dropped table: archive.ArchivedCustomers';
END

-- Drop any remaining tables in test schemas
DECLARE @dropSql NVARCHAR(MAX) = '';

SELECT @dropSql = @dropSql + 
    'DROP TABLE [' + s.name + '].[' + t.name + ']; ' + CHAR(13)
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name IN ('dbo', 'sales', 'hr', 'archive')
  AND t.type = 'U'
ORDER BY s.name, t.name;

IF LEN(@dropSql) > 0
BEGIN
    EXEC sp_executesql @dropSql;
    PRINT '  ✓ Dropped any remaining tables';
END
GO

-- ============================================================================
-- PHASE 3: DROP CUSTOM SCHEMAS
-- ============================================================================
PRINT '';
PRINT 'PHASE 3: Dropping Custom Schemas...';
GO

IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'sales')
BEGIN
    DROP SCHEMA sales;
    PRINT '  ✓ Dropped schema: sales';
END
ELSE
    PRINT '  - Schema does not exist: sales';
GO

IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'hr')
BEGIN
    DROP SCHEMA hr;
    PRINT '  ✓ Dropped schema: hr';
END
ELSE
    PRINT '  - Schema does not exist: hr';
GO

IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'archive')
BEGIN
    DROP SCHEMA archive;
    PRINT '  ✓ Dropped schema: archive';
END
ELSE
    PRINT '  - Schema does not exist: archive';
GO

-- ============================================================================
-- PHASE 4: VERIFY CLEANUP
-- ============================================================================
PRINT '';
PRINT 'PHASE 4: Verifying Cleanup...';
GO

-- Count remaining tables in test schemas
DECLARE @remainingTables INT;
SELECT @remainingTables = COUNT(*) 
FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_TYPE = 'BASE TABLE' 
  AND TABLE_SCHEMA IN ('sales', 'hr', 'archive');

IF @remainingTables = 0
    PRINT '  ✓ All test tables removed';
ELSE
    PRINT '  ⚠ Warning: ' + CAST(@remainingTables AS VARCHAR) + ' tables remain';

-- Count remaining FK constraints
DECLARE @remainingFKs INT;
SELECT @remainingFKs = COUNT(*) 
FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS 
WHERE CONSTRAINT_SCHEMA IN ('sales', 'hr', 'archive');

IF @remainingFKs = 0
    PRINT '  ✓ All test FK constraints removed';
ELSE
    PRINT '  ⚠ Warning: ' + CAST(@remainingFKs AS VARCHAR) + ' FK constraints remain';

-- Count remaining schemas
DECLARE @remainingSchemas INT;
SELECT @remainingSchemas = COUNT(*) 
FROM sys.schemas 
WHERE name IN ('sales', 'hr', 'archive');

IF @remainingSchemas = 0
    PRINT '  ✓ All test schemas removed';
ELSE
    PRINT '  ⚠ Warning: ' + CAST(@remainingSchemas AS VARCHAR) + ' schemas remain';

-- List any remaining test objects
IF EXISTS (
    SELECT 1 FROM sys.objects o
    INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
    WHERE s.name IN ('sales', 'hr', 'archive')
)
BEGIN
    PRINT '';
    PRINT 'Remaining test objects:';
    SELECT 
        s.name AS [Schema],
        o.name AS [Object],
        o.type_desc AS [Type]
    FROM sys.objects o
    INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
    WHERE s.name IN ('sales', 'hr', 'archive')
    ORDER BY s.name, o.name;
END

PRINT '';
PRINT '==================================================================';
PRINT 'Test Database Teardown Complete!';
PRINT 'Database: ' + DB_NAME();
PRINT 'Time: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '==================================================================';
GO
