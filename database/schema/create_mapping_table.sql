-- ================================================================
-- PII Mappings Table Creation Script
-- ================================================================
-- Purpose: Store original→masked value mappings for desanitization
--          with primary key tracking for accurate row-level restoration
-- Author: Database Sanitization Team
-- Date: 2026-04-16
-- Version: 2.0 (with PK tracking)
-- ================================================================

-- Drop existing table if exists (for development/testing only)
-- Comment out for production deployments
/*
IF OBJECT_ID('dbo.pii_mappings', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.pii_mappings;
    PRINT 'Existing pii_mappings table dropped';
END
GO
*/

-- Create the mapping table
IF OBJECT_ID('dbo.pii_mappings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.pii_mappings (
        -- Primary key
        mapping_id BIGINT IDENTITY(1,1) NOT NULL,
        
        -- Operation tracking
        operation_id UNIQUEIDENTIFIER NOT NULL,
        
        -- Column identification
        schema_name NVARCHAR(128) NOT NULL,
        table_name NVARCHAR(128) NOT NULL,
        column_name NVARCHAR(128) NOT NULL,
        
        -- Value storage
        original_value_hash VARBINARY(32) NOT NULL,  -- SHA-256 hash for indexing
        original_value_encrypted VARBINARY(MAX),     -- AES-256 encrypted original value
        masked_value NVARCHAR(MAX),                  -- Fake value (plaintext)
        
        -- Primary key tracking (for row-specific restoration)
        primary_key_columns NVARCHAR(MAX),           -- JSON array of PK column names
        primary_key_values NVARCHAR(MAX),            -- JSON array of PK values
        
        -- Metadata
        data_type NVARCHAR(128) NOT NULL,            -- SQL Server data type
        is_null BIT NOT NULL DEFAULT 0,              -- TRUE if original was NULL
        created_at DATETIME2(7) NOT NULL DEFAULT GETUTCDATE(),
        
        -- Constraints
        CONSTRAINT PK_pii_mappings PRIMARY KEY CLUSTERED (mapping_id),
        CONSTRAINT CHK_pii_mappings_null_consistency CHECK (
            (is_null = 1 AND original_value_encrypted IS NULL AND masked_value IS NULL)
            OR
            (is_null = 0)
        )
    );
    
    PRINT 'Table dbo.pii_mappings created successfully';
END
ELSE
BEGIN
    PRINT 'Table dbo.pii_mappings already exists - skipping creation';
END
GO

-- ================================================================
-- Index Creation for Optimized Lookups
-- ================================================================

-- Index 1: Hash-based lookup (for desanitization queries)
-- Used when looking up original values by masked value during restoration
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes 
    WHERE object_id = OBJECT_ID('dbo.pii_mappings') 
    AND name = 'IX_pii_mappings_lookup'
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_pii_mappings_lookup
    ON dbo.pii_mappings (
        operation_id,
        schema_name,
        table_name,
        column_name,
        original_value_hash
    )
    INCLUDE (original_value_encrypted, masked_value, is_null);
    
    PRINT 'Index IX_pii_mappings_lookup created successfully';
END
ELSE
BEGIN
    PRINT 'Index IX_pii_mappings_lookup already exists - skipping';
END
GO

-- Index 2: Operation-based queries (for bulk retrieval by operation)
-- Used when retrieving all mappings for a specific sanitization operation
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes 
    WHERE object_id = OBJECT_ID('dbo.pii_mappings') 
    AND name = 'IX_pii_mappings_operation'
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_pii_mappings_operation
    ON dbo.pii_mappings (operation_id, created_at DESC)
    INCLUDE (schema_name, table_name, column_name);
    
    PRINT 'Index IX_pii_mappings_operation created successfully';
END
ELSE
BEGIN
    PRINT 'Index IX_pii_mappings_operation already exists - skipping';
END
GO

-- Index 3: Table-specific queries (for selective restoration)
-- Used when restoring specific tables only
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes 
    WHERE object_id = OBJECT_ID('dbo.pii_mappings') 
    AND name = 'IX_pii_mappings_table'
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_pii_mappings_table
    ON dbo.pii_mappings (
        operation_id,
        schema_name,
        table_name
    )
    INCLUDE (column_name, original_value_hash);
    
    PRINT 'Index IX_pii_mappings_table created successfully';
END
ELSE
BEGIN
    PRINT 'Index IX_pii_mappings_table already exists - skipping';
END
GO

-- Index 4: PK-based restoration (for accurate row matching)
-- Used when restoring specific rows by primary key during desanitization
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes 
    WHERE object_id = OBJECT_ID('dbo.pii_mappings') 
    AND name = 'IX_pii_mappings_pk_restore'
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_pii_mappings_pk_restore
    ON dbo.pii_mappings (
        operation_id,
        schema_name,
        table_name,
        column_name
    )
    INCLUDE (primary_key_columns, primary_key_values, original_value_encrypted, masked_value, is_null);
    
    PRINT 'Index IX_pii_mappings_pk_restore created successfully';
END
ELSE
BEGIN
    PRINT 'Index IX_pii_mappings_pk_restore already exists - skipping';
END
GO

-- ================================================================
-- Verification Query
-- ================================================================
SELECT 
    t.name AS TableName,
    i.name AS IndexName,
    i.type_desc AS IndexType,
    STUFF((
        SELECT ', ' + c.name
        FROM sys.index_columns ic
        JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
        ORDER BY ic.key_ordinal
        FOR XML PATH('')
    ), 1, 2, '') AS IndexColumns
FROM sys.tables t
JOIN sys.indexes i ON t.object_id = i.object_id
WHERE t.name = 'pii_mappings'
ORDER BY i.index_id;
GO

PRINT '================================================================';
PRINT 'PII Mappings Table Setup Complete';
PRINT '================================================================';
PRINT 'Table: dbo.pii_mappings';
PRINT 'Indexes: 4 (PK + 3 nonclustered)';
PRINT 'Features: Value storage + Primary Key tracking for accurate restoration';
PRINT 'Ready for mapping capture during sanitization';
PRINT '================================================================';
GO
