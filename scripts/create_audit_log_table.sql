-- =============================================================================
-- Database Desanitization Audit Log Table Creation Script
-- =============================================================================
-- Purpose: Create immutable audit log table for tracking all desanitization 
--          operations for compliance (GDPR, HIPAA) and security monitoring
--
-- Features:
--   - Append-only design (no UPDATE/DELETE operations)
--   - Tracks who, what, when, why for every desanitization operation
--   - Supports all operation types: RECORD, COLUMN, TABLE, DATABASE
--   - Optimized indexes for common query patterns
--   - JSON storage for flexible array fields (columns, record IDs)
--
-- Related: User Story 4.1 - Audit Logging for Desanitization
-- Created: April 13, 2026
-- =============================================================================

USE [YourDatabaseName];  -- Replace with actual database name
GO

-- Drop table if exists (for development/testing only - be careful in production!)
-- Uncomment the following lines if you need to recreate the table
/*
IF OBJECT_ID('dbo.desanitization_audit_log', 'U') IS NOT NULL
BEGIN
    DROP TABLE dbo.desanitization_audit_log;
    PRINT 'Dropped existing desanitization_audit_log table';
END
GO
*/

-- =============================================================================
-- Create Audit Log Table
-- =============================================================================

CREATE TABLE dbo.desanitization_audit_log (
    -- Primary Key
    audit_id BIGINT IDENTITY(1,1) NOT NULL,
    
    -- Operation Identification
    operation_id NVARCHAR(100) NOT NULL,  -- Format: DESAN-YYYYMMDDHHMMSS-{uuid8}
    operation_type NVARCHAR(20) NOT NULL, -- RECORD, COLUMN, TABLE, DATABASE
    
    -- Target Identification
    target_schema NVARCHAR(128) NULL,     -- Schema name (e.g., 'dbo')
    target_table NVARCHAR(128) NULL,      -- Table name for RECORD/COLUMN/TABLE operations
    target_columns NVARCHAR(MAX) NULL,    -- JSON array: ["Email", "Phone", ...] for COLUMN operations
    target_record_ids NVARCHAR(MAX) NULL, -- JSON array: ["123", "456"] or composite key JSON for RECORD operations
    
    -- User & Authorization
    initiated_by NVARCHAR(256) NOT NULL,  -- Database user (SYSTEM_USER or SUSER_SNAME())
    command_line NVARCHAR(MAX) NULL,      -- CLI command for traceability
    
    -- Batch Correlation
    batch_id NVARCHAR(100) NULL,          -- Links to original sanitization batch (optional filter)
    sanitization_run_id NVARCHAR(100) NULL, -- Links to original sanitization run (optional)
    
    -- Operation Mode
    dry_run BIT NOT NULL DEFAULT 0,       -- 1 = dry-run (preview only), 0 = executed
    
    -- Timing
    started_at DATETIME2(3) NOT NULL,     -- Operation start timestamp
    completed_at DATETIME2(3) NULL,       -- Operation completion timestamp (NULL if in-progress or failed)
    duration_seconds AS DATEDIFF(SECOND, started_at, completed_at) PERSISTED, -- Computed column
    
    -- Status & Results
    status NVARCHAR(20) NOT NULL,         -- PENDING, COMPLETED, FAILED, ROLLED_BACK
    rows_restored INT NULL DEFAULT 0,     -- Total rows affected (0 for dry-run)
    mappings_applied INT NULL DEFAULT 0,  -- Total mappings used from token_mappings table
    columns_affected INT NULL DEFAULT 0,  -- Number of columns restored
    tables_affected INT NULL DEFAULT 0,   -- Number of tables restored (DATABASE operations)
    
    -- Validation Results
    validation_passed BIT NULL,           -- NULL = not validated, 0 = failed validation, 1 = passed validation
    validation_warnings_count INT NULL DEFAULT 0, -- Number of non-critical warnings
    validation_errors_count INT NULL DEFAULT 0,   -- Number of critical errors
    
    -- Error Details
    error_message NVARCHAR(MAX) NULL,     -- Error details if status = FAILED
    error_type NVARCHAR(128) NULL,        -- Exception class name (e.g., 'MappingNotFoundError')
    
    -- Security & Authorization (Story 7.1: RBAC)
    required_roles NVARCHAR(MAX) NULL,    -- JSON array of required roles for operation (for PERMISSION_DENIED events)
    user_roles NVARCHAR(MAX) NULL,        -- JSON array of user's actual roles (for PERMISSION_DENIED events)
    
    -- Metadata
    created_at DATETIME2(3) NOT NULL DEFAULT GETDATE(), -- Immutable creation timestamp
    
    -- Constraints
    CONSTRAINT PK_desanitization_audit_log PRIMARY KEY CLUSTERED (audit_id),
    CONSTRAINT CK_audit_operation_type CHECK (operation_type IN ('RECORD', 'COLUMN', 'TABLE', 'DATABASE')),
    CONSTRAINT CK_audit_status CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED', 'ROLLED_BACK', 'PERMISSION_DENIED')),
    CONSTRAINT CK_audit_dry_run CHECK (dry_run IN (0, 1)),
    CONSTRAINT CK_audit_validation_passed CHECK (validation_passed IS NULL OR validation_passed IN (0, 1)),
    CONSTRAINT CK_audit_timing CHECK (completed_at IS NULL OR completed_at >= started_at)
);
GO

-- =============================================================================
-- Create Indexes for Query Performance
-- =============================================================================

-- Index 1: Query by operation_id (unique lookup for specific operations)
CREATE UNIQUE NONCLUSTERED INDEX IX_audit_operation_id
ON dbo.desanitization_audit_log (operation_id)
INCLUDE (status, started_at, completed_at, initiated_by);
GO

-- Index 2: Query by user and time range (compliance queries: "who did what when")
CREATE NONCLUSTERED INDEX IX_audit_user_time
ON dbo.desanitization_audit_log (initiated_by, started_at DESC)
INCLUDE (operation_id, operation_type, target_table, target_schema, status, rows_restored);
GO

-- Index 3: Query by target table and time (table-specific audit trail)
CREATE NONCLUSTERED INDEX IX_audit_target_table_time
ON dbo.desanitization_audit_log (target_table, started_at DESC)
WHERE target_table IS NOT NULL
INCLUDE (operation_id, operation_type, initiated_by, status, rows_restored);
GO

-- Index 4: Query by batch_id (trace all operations for a sanitization batch)
CREATE NONCLUSTERED INDEX IX_audit_batch_id
ON dbo.desanitization_audit_log (batch_id, started_at DESC)
WHERE batch_id IS NOT NULL
INCLUDE (operation_id, operation_type, target_table, status, rows_restored);
GO

-- Index 5: Query by status and started_at (monitor failed operations)
CREATE NONCLUSTERED INDEX IX_audit_status_time
ON dbo.desanitization_audit_log (status, started_at DESC)
INCLUDE (operation_id, operation_type, target_table, initiated_by, error_message);
GO

-- =============================================================================
-- Create Statistics for Query Optimization
-- =============================================================================

-- Statistics on operation_type distribution for better query plans
CREATE STATISTICS STAT_audit_operation_type
ON dbo.desanitization_audit_log (operation_type);
GO

-- Statistics on status distribution
CREATE STATISTICS STAT_audit_status
ON dbo.desanitization_audit_log (status);
GO

-- =============================================================================
-- Add Extended Properties (Documentation)
-- =============================================================================

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Immutable audit log for all desanitization operations. Tracks who restored what data and when for compliance (GDPR, HIPAA). Append-only design - no UPDATE/DELETE operations allowed.', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log';
GO

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Unique identifier for this audit record. Auto-incrementing for guaranteed ordering.', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log',
    @level2type = N'COLUMN', @level2name = 'audit_id';
GO

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Operation identifier matching DesanitizationEngine.operation_id. Format: DESAN-YYYYMMDDHHMMSS-{uuid8}', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log',
    @level2type = N'COLUMN', @level2name = 'operation_id';
GO

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Type of desanitization operation: RECORD (specific records), COLUMN (all records in columns), TABLE (entire table), DATABASE (all tables)', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log',
    @level2type = N'COLUMN', @level2name = 'operation_type';
GO

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Database user who initiated the operation. Populated via SYSTEM_USER or SUSER_SNAME() SQL function.', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log',
    @level2type = N'COLUMN', @level2name = 'initiated_by';
GO

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Full CLI command executed (e.g., "python desanitize_direct.py --table Customers --execute") for traceability.', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log',
    @level2type = N'COLUMN', @level2name = 'command_line';
GO

EXEC sp_addextendedproperty 
    @name = N'MS_Description', 
    @value = N'Current status: PENDING (started), COMPLETED (success), FAILED (error), ROLLED_BACK (transaction reverted)', 
    @level0type = N'SCHEMA', @level0name = 'dbo',
    @level1type = N'TABLE',  @level1name = 'desanitization_audit_log',
    @level2type = N'COLUMN', @level2name = 'status';
GO

-- =============================================================================
-- Success Message
-- =============================================================================

PRINT '';
PRINT '=============================================================================';
PRINT 'SUCCESS: desanitization_audit_log table created successfully';
PRINT '=============================================================================';
PRINT '';
PRINT 'Table Details:';
PRINT '  - Name: dbo.desanitization_audit_log';
PRINT '  - Primary Key: audit_id (BIGINT IDENTITY)';
PRINT '  - Indexes: 5 nonclustered indexes for query optimization';
PRINT '  - Constraints: 6 check constraints for data integrity';
PRINT '';
PRINT 'Usage:';
PRINT '  - This table is automatically populated by the AuditLogger class';
PRINT '  - Query recent operations:';
PRINT '      SELECT TOP 10 * FROM dbo.desanitization_audit_log ORDER BY started_at DESC;';
PRINT '  - Query by user:';
PRINT '      SELECT * FROM dbo.desanitization_audit_log WHERE initiated_by = ''domain\username'';';
PRINT '  - Query by table:';
PRINT '      SELECT * FROM dbo.desanitization_audit_log WHERE target_table = ''Customers'';';
PRINT '';
PRINT 'Retention Policy:';
PRINT '  - Recommended: Archive records >90 days to separate table';
PRINT '  - Compliance: Retain audit logs for 7 years (GDPR/HIPAA requirement)';
PRINT '=============================================================================';
GO
