/*
================================================================================
DATABASE SANITIZATION FRAMEWORK - MAPPING TABLE
================================================================================

Purpose: Store sanitized-to-original value mappings for reversible sanitization
Version: 1.0
Created: April 9, 2026

Table: token_mappings (configurable via environment)
Stores: Bidirectional mapping between original and masked values

Usage:
    sqlcmd -S localhost -d YourDatabase -i create_mapping_table.sql
    
    OR from Python:
    from mapping.mapping_table_manager import MappingTableManager
    manager = MappingTableManager(connection_string)
    manager.create_table()

================================================================================
*/

SET NOCOUNT ON;
GO

PRINT '==================================================================';
PRINT 'Creating Mapping Table for Reversible Sanitization';
PRINT 'Database: ' + DB_NAME();
PRINT 'Time: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '==================================================================';
GO

-- Drop existing table (idempotency)
IF OBJECT_ID('dbo.token_mappings', 'U') IS NOT NULL
BEGIN
    PRINT 'Dropping existing token_mappings table...';
    DROP TABLE dbo.token_mappings;
    PRINT '  ✓ Dropped existing table';
END
GO

-- Create mapping table
PRINT '';
PRINT 'Creating token_mappings table...';
GO

CREATE TABLE dbo.token_mappings (
    -- Primary key
    mapping_id BIGINT IDENTITY(1,1) NOT NULL,
    
    -- Table/Column identification
    table_name NVARCHAR(255) NOT NULL,
    column_name NVARCHAR(255) NOT NULL,
    
    -- Record identification (supports composite PKs via JSON)
    -- Examples: 
    --   Simple PK: "123"
    --   Composite PK: "{\"CustomerID\":123,\"OrderID\":456}"
    record_id NVARCHAR(MAX) NOT NULL,
    
    -- Mapping data (NVARCHAR(MAX) supports long text, unicode)
    original_value NVARCHAR(MAX) NULL,  -- NULL represents database NULL
    masked_value NVARCHAR(MAX) NOT NULL,
    
    -- Metadata for traceability
    created_at DATETIME2(7) NOT NULL DEFAULT GETDATE(),
    batch_id NVARCHAR(100) NOT NULL,  -- UUID for sanitization batch
    sanitization_run_id NVARCHAR(100) NOT NULL,  -- UUID for run session
    
    -- Version tracking (future use)
    schema_version INT NOT NULL DEFAULT 1,
    
    -- Constraints
    CONSTRAINT PK_token_mappings PRIMARY KEY CLUSTERED (mapping_id)
);
GO

PRINT '  ✓ Created token_mappings table';
GO

-- Create indexes for efficient lookups
PRINT '';
PRINT 'Creating indexes...';
GO

-- Index 1: Record-level desanitization (most common query)
CREATE NONCLUSTERED INDEX IX_token_mappings_record_id 
ON dbo.token_mappings (table_name, column_name, batch_id)
INCLUDE (record_id, original_value, masked_value);
PRINT '  ✓ Created IX_token_mappings_record_id';
GO

-- Index 2: Table-level queries
CREATE NONCLUSTERED INDEX IX_token_mappings_table_name 
ON dbo.token_mappings (table_name, batch_id)
INCLUDE (column_name, record_id);
PRINT '  ✓ Created IX_token_mappings_table_name';
GO

-- Index 3: Batch filtering
CREATE NONCLUSTERED INDEX IX_token_mappings_batch_id 
ON dbo.token_mappings (batch_id, created_at)
INCLUDE (table_name, column_name);
PRINT '  ✓ Created IX_token_mappings_batch_id';
GO

-- Index 4: Run session tracking
CREATE NONCLUSTERED INDEX IX_token_mappings_run_id 
ON dbo.token_mappings (sanitization_run_id, created_at);
PRINT '  ✓ Created IX_token_mappings_run_id';
GO

-- Verify table creation
PRINT '';
PRINT 'Verifying table structure...';
GO

IF OBJECT_ID('dbo.token_mappings', 'U') IS NOT NULL
BEGIN
    DECLARE @col_count INT;
    SELECT @col_count = COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_NAME = 'token_mappings' AND TABLE_SCHEMA = 'dbo';
    
    PRINT '  ✓ Table exists with ' + CAST(@col_count AS VARCHAR) + ' columns';
    
    DECLARE @idx_count INT;
    SELECT @idx_count = COUNT(*) 
    FROM sys.indexes 
    WHERE object_id = OBJECT_ID('dbo.token_mappings') AND index_id > 0;
    
    PRINT '  ✓ Created ' + CAST(@idx_count AS VARCHAR) + ' indexes (including PK)';
END
ELSE
BEGIN
    RAISERROR('ERROR: Table creation failed!', 16, 1);
END
GO

PRINT '';
PRINT '==================================================================';
PRINT 'Mapping Table Setup Complete';
PRINT '==================================================================';
GO
