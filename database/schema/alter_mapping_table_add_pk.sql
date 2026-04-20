-- ================================================================
-- PII Mappings Table - Add Primary Key Tracking
-- ================================================================
-- Purpose: Add primary key tracking to enable row-specific restoration
-- Author: Database Sanitization Team
-- Date: 2026-04-16
-- ================================================================

-- Add primary key tracking columns
IF NOT EXISTS (
    SELECT 1 FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.pii_mappings') 
    AND name = 'primary_key_columns'
)
BEGIN
    ALTER TABLE dbo.pii_mappings
    ADD primary_key_columns NVARCHAR(MAX) NULL;  -- JSON array of PK column names
    
    PRINT 'Added column: primary_key_columns';
END
ELSE
BEGIN
    PRINT 'Column primary_key_columns already exists';
END
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns 
    WHERE object_id = OBJECT_ID('dbo.pii_mappings') 
    AND name = 'primary_key_values'
)
BEGIN
    ALTER TABLE dbo.pii_mappings
    ADD primary_key_values NVARCHAR(MAX) NULL;  -- JSON array of PK values
    
    PRINT 'Added column: primary_key_values';
END
ELSE
BEGIN
    PRINT 'Column primary_key_values already exists';
END
GO

-- Add index for PK-based restoration lookups
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

-- Verification
SELECT 
    'pii_mappings' AS TableName,
    name AS ColumnName,
    TYPE_NAME(user_type_id) AS DataType,
    max_length AS MaxLength,
    is_nullable AS IsNullable
FROM sys.columns
WHERE object_id = OBJECT_ID('dbo.pii_mappings')
AND name IN ('primary_key_columns', 'primary_key_values')
ORDER BY column_id;

PRINT 'Primary key tracking columns added successfully';
