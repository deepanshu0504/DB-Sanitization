/*
================================================================================
DATABASE SANITIZATION FRAMEWORK - CHECKPOINT TABLE
================================================================================

Purpose: Track progress of database-level desanitization for fault tolerance
Version: 1.1
Created: April 9, 2026
Updated: April 13, 2026 (Added audit log integration note)

Table: desanitization_checkpoints (configurable via environment)
Stores: Status of table restorations during database-level operations

Audit Integration:
    - Checkpoint records link to audit log via operation_id column
    - Query audit log: SELECT * FROM desanitization_audit_log WHERE operation_id = 'DESAN-...'
    - Both tables share operation_id as common key for full traceability

Usage:
    sqlcmd -S localhost -d YourDatabase -i create_checkpoint_table.sql
    
    OR from Python:
    from desanitization.checkpoint_manager import CheckpointManager
    manager = CheckpointManager(connection_string)
    manager.create_table()

================================================================================
*/

SET NOCOUNT ON;
GO

PRINT '==================================================================';
PRINT 'Creating Checkpoint Table for Desanitization Resume';
PRINT 'Database: ' + DB_NAME();
PRINT 'Time: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '==================================================================';
GO

-- Drop existing table (idempotency)
IF OBJECT_ID('dbo.desanitization_checkpoints', 'U') IS NOT NULL
BEGIN
    PRINT 'Dropping existing desanitization_checkpoints table...';
    DROP TABLE dbo.desanitization_checkpoints;
    PRINT '  ✓ Dropped existing table';
END
GO

-- Create checkpoint table
PRINT '';
PRINT 'Creating desanitization_checkpoints table...';
GO

CREATE TABLE dbo.desanitization_checkpoints (
    -- Primary key
    checkpoint_id BIGINT IDENTITY(1,1) NOT NULL,
    
    -- Operation identification
    operation_id NVARCHAR(100) NOT NULL,  -- Unique ID for database-level operation
    
    -- Table being processed
    table_name NVARCHAR(255) NOT NULL,
    schema_name NVARCHAR(255) NOT NULL DEFAULT 'dbo',
    
    -- Status tracking
    status NVARCHAR(50) NOT NULL,  -- PENDING, IN_PROGRESS, COMPLETED, FAILED
    
    -- Timing information
    started_at DATETIME2(7) NULL,
    completed_at DATETIME2(7) NULL,
    
    -- Progress metrics
    rows_restored INT NULL,
    columns_affected INT NULL,
    
    -- Error tracking
    error_message NVARCHAR(MAX) NULL,
    retry_count INT NOT NULL DEFAULT 0,
    
    -- Metadata
    created_at DATETIME2(7) NOT NULL DEFAULT GETDATE(),
    updated_at DATETIME2(7) NOT NULL DEFAULT GETDATE(),
    
    -- Batch context (optional)
    batch_id NVARCHAR(100) NULL,
    
    -- Constraints
    CONSTRAINT PK_desanitization_checkpoints PRIMARY KEY CLUSTERED (checkpoint_id),
    
    -- Unique constraint: One checkpoint per (operation_id, table_name)
    CONSTRAINT UQ_desanitization_checkpoints_operation_table 
        UNIQUE (operation_id, table_name, schema_name),
    
    -- Check constraint: Valid status values
    CONSTRAINT CK_desanitization_checkpoints_status 
        CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED'))
);
GO

PRINT '  ✓ Created desanitization_checkpoints table';
GO

-- Create indexes for efficient lookups
PRINT '';
PRINT 'Creating indexes...';
GO

-- Index 1: Operation status queries (most common)
CREATE NONCLUSTERED INDEX IX_checkpoints_operation_status 
ON dbo.desanitization_checkpoints (operation_id, status)
INCLUDE (table_name, schema_name, started_at, completed_at, rows_restored);
PRINT '  ✓ Created IX_checkpoints_operation_status';
GO

-- Index 2: Resume operations (find incomplete)
CREATE NONCLUSTERED INDEX IX_checkpoints_incomplete 
ON dbo.desanitization_checkpoints (status, created_at)
WHERE status IN ('PENDING', 'IN_PROGRESS', 'FAILED')
INCLUDE (operation_id, table_name, error_message);
PRINT '  ✓ Created IX_checkpoints_incomplete';
GO

-- Index 3: Time-based cleanup (stale checkpoints)
CREATE NONCLUSTERED INDEX IX_checkpoints_created_at 
ON dbo.desanitization_checkpoints (created_at)
INCLUDE (operation_id, status);
PRINT '  ✓ Created IX_checkpoints_created_at';
GO

-- Create trigger for automatic updated_at timestamp
PRINT '';
PRINT 'Creating triggers...';
GO

CREATE TRIGGER TR_desanitization_checkpoints_update
ON dbo.desanitization_checkpoints
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    
    UPDATE dbo.desanitization_checkpoints
    SET updated_at = GETDATE()
    WHERE checkpoint_id IN (SELECT checkpoint_id FROM inserted);
END;
GO

PRINT '  ✓ Created TR_desanitization_checkpoints_update trigger';
GO

-- Verify table creation
PRINT '';
PRINT 'Verifying table structure...';
GO

IF OBJECT_ID('dbo.desanitization_checkpoints', 'U') IS NOT NULL
BEGIN
    DECLARE @col_count INT;
    SELECT @col_count = COUNT(*) 
    FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_NAME = 'desanitization_checkpoints' AND TABLE_SCHEMA = 'dbo';
    
    PRINT '  ✓ Table exists with ' + CAST(@col_count AS VARCHAR) + ' columns';
    
    DECLARE @idx_count INT;
    SELECT @idx_count = COUNT(*) 
    FROM sys.indexes 
    WHERE object_id = OBJECT_ID('dbo.desanitization_checkpoints') AND index_id > 0;
    
    PRINT '  ✓ Created ' + CAST(@idx_count AS VARCHAR) + ' indexes (including PK)';
    
    DECLARE @trigger_count INT;
    SELECT @trigger_count = COUNT(*) 
    FROM sys.triggers 
    WHERE parent_id = OBJECT_ID('dbo.desanitization_checkpoints');
    
    PRINT '  ✓ Created ' + CAST(@trigger_count AS VARCHAR) + ' trigger(s)';
END
ELSE
BEGIN
    RAISERROR('ERROR: Table creation failed!', 16, 1);
END
GO

-- Sample queries for checkpoint management
PRINT '';
PRINT 'Sample Queries:';
PRINT '---------------------------------------------------------------';
PRINT '-- List all incomplete operations:';
PRINT 'SELECT operation_id, COUNT(*) AS tables_pending';
PRINT 'FROM dbo.desanitization_checkpoints';
PRINT 'WHERE status IN (''PENDING'', ''IN_PROGRESS'', ''FAILED'')';
PRINT 'GROUP BY operation_id;';
PRINT '';
PRINT '-- Get status of specific operation:';
PRINT 'SELECT table_name, status, rows_restored, error_message';
PRINT 'FROM dbo.desanitization_checkpoints';
PRINT 'WHERE operation_id = ''YOUR_OPERATION_ID''';
PRINT 'ORDER BY created_at;';
PRINT '';
PRINT '-- Clean up stale checkpoints (>24 hours):';
PRINT 'DELETE FROM dbo.desanitization_checkpoints';
PRINT 'WHERE created_at < DATEADD(HOUR, -24, GETDATE())';
PRINT '  AND status IN (''COMPLETED'', ''FAILED'');';
PRINT '---------------------------------------------------------------';
GO

PRINT '';
PRINT '==================================================================';
PRINT 'Checkpoint Table Setup Complete';
PRINT '==================================================================';
GO
