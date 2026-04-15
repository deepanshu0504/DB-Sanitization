-- =====================================================================================
-- Add Composite Index on created_at for Time-Based Filtering (Story 5.2)
-- =====================================================================================
-- 
-- Purpose:
--   Optimize date range filtering queries in incremental desanitization workflows.
--   Supports queries like: WHERE created_at BETWEEN @start AND @end
--
-- Performance Impact:
--   - Index creation: ~1-2 seconds per 100K rows
--   - Query speedup: 10-100x for date range queries (vs. table scan)
--   - Storage overhead: ~5-10% of table size
--
-- User Story: 5.2 - Incremental Desanitization
-- Created: April 13, 2026
-- =====================================================================================

USE [YourDatabaseName];  -- Replace with actual database name
GO

-- Check if index already exists
IF NOT EXISTS (
    SELECT 1 
    FROM sys.indexes 
    WHERE name = 'IX_token_mappings_created_at' 
    AND object_id = OBJECT_ID('dbo.token_mappings')
)
BEGIN
    PRINT 'Creating index IX_token_mappings_created_at on token_mappings table...';
    
    -- Create composite index optimized for date range + table/batch filtering
    CREATE NONCLUSTERED INDEX IX_token_mappings_created_at
    ON dbo.token_mappings (created_at, table_name, batch_id)
    INCLUDE (column_name, record_id, original_value, masked_value, sanitization_run_id)
    WITH (
        FILLFACTOR = 90,           -- 90% fill to allow for future inserts
        PAD_INDEX = ON,            -- Apply FILLFACTOR to intermediate index pages
        SORT_IN_TEMPDB = ON,       -- Build index in tempdb for better performance
        STATISTICS_NORECOMPUTE = OFF,
        ONLINE = OFF               -- Set to ON for Enterprise Edition (no downtime)
    );
    
    PRINT 'Index created successfully.';
    PRINT 'Index covers query patterns:';
    PRINT '  - WHERE created_at BETWEEN @start AND @end';
    PRINT '  - WHERE created_at >= @start AND table_name = @table';
    PRINT '  - WHERE created_at >= @start AND batch_id = @batch';
    PRINT '';
    PRINT 'INCLUDE columns allow index-only scans (covering index) for common queries.';
END
ELSE
BEGIN
    PRINT 'Index IX_token_mappings_created_at already exists - skipping creation.';
END
GO

-- Verify index creation
PRINT '';
PRINT 'Index Verification:';
SELECT 
    i.name AS IndexName,
    i.type_desc AS IndexType,
    i.fill_factor AS FillFactor,
    STUFF((
        SELECT ', ' + c.name
        FROM sys.index_columns ic
        JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        WHERE ic.object_id = i.object_id 
        AND ic.index_id = i.index_id
        AND ic.is_included_column = 0
        ORDER BY ic.key_ordinal
        FOR XML PATH('')
    ), 1, 2, '') AS KeyColumns,
    STUFF((
        SELECT ', ' + c.name
        FROM sys.index_columns ic
        JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        WHERE ic.object_id = i.object_id 
        AND ic.index_id = i.index_id
        AND ic.is_included_column = 1
        FOR XML PATH('')
    ), 1, 2, '') AS IncludedColumns
FROM sys.indexes i
WHERE i.name = 'IX_token_mappings_created_at'
AND i.object_id = OBJECT_ID('dbo.token_mappings');
GO

-- =====================================================================================
-- Usage Examples (Time-Based Filtering)
-- =====================================================================================
/*

-- Example 1: Get mappings from last 7 days
SELECT table_name, column_name, COUNT(*) AS mapping_count
FROM dbo.token_mappings
WHERE created_at >= DATEADD(DAY, -7, GETDATE())
GROUP BY table_name, column_name;

-- Example 2: Get mappings for specific date range
DECLARE @StartDate DATETIME2 = '2026-04-01 00:00:00';
DECLARE @EndDate DATETIME2 = '2026-04-13 23:59:59';

SELECT *
FROM dbo.token_mappings
WHERE created_at BETWEEN @StartDate AND @EndDate
ORDER BY created_at DESC;

-- Example 3: Date range + table + batch filtering (fully optimized by index)
SELECT *
FROM dbo.token_mappings
WHERE created_at BETWEEN '2026-04-01' AND '2026-04-13'
  AND table_name = 'Customers'
  AND batch_id = 'BATCH-20260409-12345678';

-- Check index usage via execution plan:
-- 1. Enable "Include Actual Execution Plan" in SSMS
-- 2. Run one of the queries above
-- 3. Verify "Index Seek" on IX_token_mappings_created_at (not "Table Scan")

*/
GO

-- =====================================================================================
-- Index Maintenance (Optional)
-- =====================================================================================
/*

-- Rebuild index if fragmentation detected (run periodically)
ALTER INDEX IX_token_mappings_created_at 
    ON dbo.token_mappings 
    REBUILD WITH (FILLFACTOR = 90, ONLINE = OFF);

-- Update statistics for optimal query plans
UPDATE STATISTICS dbo.token_mappings IX_token_mappings_created_at WITH FULLSCAN;

-- Check index fragmentation
SELECT 
    OBJECT_NAME(ips.object_id) AS TableName,
    i.name AS IndexName,
    ips.index_type_desc,
    ips.avg_fragmentation_in_percent,
    ips.page_count
FROM sys.dm_db_index_physical_stats(
    DB_ID(), 
    OBJECT_ID('dbo.token_mappings'), 
    NULL, NULL, 'DETAILED'
) AS ips
JOIN sys.indexes i ON ips.object_id = i.object_id AND ips.index_id = i.index_id
WHERE i.name = 'IX_token_mappings_created_at';

-- Recommendation: Rebuild if fragmentation > 30%, reorganize if 10-30%

*/
GO

PRINT '';
PRINT '✓ Index creation complete.';
PRINT 'Story 5.2 (Incremental Desanitization) - Time-based filtering optimization ready.';
GO
