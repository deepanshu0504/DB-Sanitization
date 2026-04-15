-- =====================================================================
-- Index Maintenance Script for token_mappings Table
-- =====================================================================
-- Purpose: Maintain optimal index performance for mapping table
-- Usage: Execute manually or schedule during maintenance windows
--
-- Story 5.3: Optimized Mapping Lookups
-- =====================================================================

SET NOCOUNT ON;

DECLARE @TableName NVARCHAR(256) = N'[dbo].[token_mappings]';
DECLARE @FragmentationThreshold FLOAT = 10.0;  -- Minimum fragmentation % to address
DECLARE @RebuildThreshold FLOAT = 30.0;         -- Threshold for REBUILD vs REORGANIZE
DECLARE @MinPageCount INT = 100;                -- Skip small indexes
DECLARE @OnlineRebuild BIT = 1;                 -- Use ONLINE=ON (requires Enterprise Edition)

-- Results table
DECLARE @Results TABLE (
    IndexName NVARCHAR(128),
    Action VARCHAR(20),
    FragmentationBefore FLOAT,
    PageCount INT,
    StartTime DATETIME,
    EndTime DATETIME,
    DurationSeconds INT,
    Status VARCHAR(50)
);

PRINT '=====================================================================';
PRINT 'Index Maintenance for ' + @TableName;
PRINT 'Started at: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '=====================================================================';
PRINT '';

-- Get fragmentation information
DECLARE @IndexFragmentation TABLE (
    IndexID INT,
    IndexName NVARCHAR(128),
    FragmentationPercent FLOAT,
    PageCount INT
);

INSERT INTO @IndexFragmentation
SELECT 
    i.index_id,
    i.name AS IndexName,
    ps.avg_fragmentation_in_percent AS FragmentationPercent,
    ps.page_count AS PageCount
FROM sys.dm_db_index_physical_stats(
    DB_ID(), 
    OBJECT_ID(@TableName), 
    NULL, 
    NULL, 
    'LIMITED'  -- Use LIMITED mode for faster execution
) AS ps
INNER JOIN sys.indexes AS i 
    ON ps.object_id = i.object_id 
    AND ps.index_id = i.index_id
WHERE ps.avg_fragmentation_in_percent >= @FragmentationThreshold
    AND ps.page_count > @MinPageCount  -- Skip small indexes
    AND i.name IS NOT NULL  -- Skip heap
ORDER BY ps.avg_fragmentation_in_percent DESC;

-- Display fragmentation status
PRINT '--- Current Index Fragmentation ---';
PRINT '';
SELECT 
    IndexName,
    FragmentationPercent AS [Fragmentation %],
    PageCount,
    CASE 
        WHEN FragmentationPercent < @RebuildThreshold THEN 'REORGANIZE'
        ELSE 'REBUILD'
    END AS RecommendedAction
FROM @IndexFragmentation
ORDER BY FragmentationPercent DESC;

PRINT '';
PRINT '--- Executing Maintenance ---';
PRINT '';

-- Cursor for processing each index
DECLARE @IndexID INT;
DECLARE @IndexName NVARCHAR(128);
DECLARE @Fragmentation FLOAT;
DECLARE @PageCount INT;
DECLARE @SQL NVARCHAR(MAX);
DECLARE @Action VARCHAR(20);
DECLARE @StartTime DATETIME;
DECLARE @EndTime DATETIME;
DECLARE @ErrorMessage NVARCHAR(4000);

DECLARE index_cursor CURSOR FOR 
    SELECT IndexID, IndexName, FragmentationPercent, PageCount
    FROM @IndexFragmentation
    ORDER BY FragmentationPercent DESC;

OPEN index_cursor;

FETCH NEXT FROM index_cursor INTO @IndexID, @IndexName, @Fragmentation, @PageCount;

WHILE @@FETCH_STATUS = 0
BEGIN
    SET @StartTime = GETDATE();
    
    -- Determine action: REORGANIZE or REBUILD
    IF @Fragmentation < @RebuildThreshold
    BEGIN
        SET @Action = 'REORGANIZE';
        SET @SQL = N'ALTER INDEX [' + @IndexName + N'] ON ' + @TableName + N' REORGANIZE;';
    END
    ELSE
    BEGIN
        SET @Action = 'REBUILD';
        
        -- Check if ONLINE option is available (Enterprise Edition)
        IF @OnlineRebuild = 1
        BEGIN
            SET @SQL = N'ALTER INDEX [' + @IndexName + N'] ON ' + @TableName + 
                      N' REBUILD WITH (ONLINE = ON, MAXDOP = 0, SORT_IN_TEMPDB = ON);';
        END
        ELSE
        BEGIN
            SET @SQL = N'ALTER INDEX [' + @IndexName + N'] ON ' + @TableName + 
                      N' REBUILD WITH (MAXDOP = 0, SORT_IN_TEMPDB = ON);';
        END
    END
    
    -- Execute maintenance
    BEGIN TRY
        PRINT 'Processing: ' + @IndexName + ' (' + @Action + ') - Fragmentation: ' + CAST(@Fragmentation AS VARCHAR(10)) + '%';
        
        EXEC sp_executesql @SQL;
        
        SET @EndTime = GETDATE();
        
        INSERT INTO @Results (IndexName, Action, FragmentationBefore, PageCount, StartTime, EndTime, DurationSeconds, Status)
        VALUES (
            @IndexName, 
            @Action, 
            @Fragmentation, 
            @PageCount, 
            @StartTime, 
            @EndTime, 
            DATEDIFF(SECOND, @StartTime, @EndTime),
            'SUCCESS'
        );
        
        PRINT '  ✓ Completed in ' + CAST(DATEDIFF(SECOND, @StartTime, @EndTime) AS VARCHAR) + ' seconds';
        PRINT '';
        
    END TRY
    BEGIN CATCH
        SET @ErrorMessage = ERROR_MESSAGE();
        
        INSERT INTO @Results (IndexName, Action, FragmentationBefore, PageCount, StartTime, EndTime, DurationSeconds, Status)
        VALUES (
            @IndexName, 
            @Action, 
            @Fragmentation, 
            @PageCount, 
            @StartTime, 
            GETDATE(), 
            DATEDIFF(SECOND, @StartTime, GETDATE()),
            'FAILED: ' + @ErrorMessage
        );
        
        PRINT '  ✗ FAILED: ' + @ErrorMessage;
        PRINT '';
    END CATCH
    
    FETCH NEXT FROM index_cursor INTO @IndexID, @IndexName, @Fragmentation, @PageCount;
END

CLOSE index_cursor;
DEALLOCATE index_cursor;

-- Update statistics with FULLSCAN for better query plans
PRINT '--- Updating Statistics ---';
PRINT '';

BEGIN TRY
    UPDATE STATISTICS dbo.token_mappings WITH FULLSCAN;
    PRINT '  ✓ Statistics updated successfully';
    PRINT '';
END TRY
BEGIN CATCH
    PRINT '  ✗ Statistics update FAILED: ' + ERROR_MESSAGE();
    PRINT '';
END CATCH

-- Display results summary
PRINT '=====================================================================';
PRINT 'Maintenance Summary';
PRINT '=====================================================================';
PRINT '';

SELECT 
    IndexName,
    Action,
    FragmentationBefore AS [Fragmentation Before %],
    PageCount AS [Page Count],
    DurationSeconds AS [Duration (sec)],
    Status
FROM @Results
ORDER BY StartTime;

PRINT '';

-- Display final statistics
DECLARE @TotalIndexes INT = (SELECT COUNT(*) FROM @Results);
DECLARE @SuccessCount INT = (SELECT COUNT(*) FROM @Results WHERE Status = 'SUCCESS');
DECLARE @FailCount INT = (SELECT COUNT(*) FROM @Results WHERE Status LIKE 'FAILED%');
DECLARE @TotalDuration INT = (SELECT SUM(DurationSeconds) FROM @Results);

PRINT 'Total Indexes Processed: ' + CAST(@TotalIndexes AS VARCHAR);
PRINT 'Successful: ' + CAST(@SuccessCount AS VARCHAR);
PRINT 'Failed: ' + CAST(@FailCount AS VARCHAR);
PRINT 'Total Duration: ' + CAST(@TotalDuration AS VARCHAR) + ' seconds';
PRINT '';
PRINT 'Completed at: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '=====================================================================';

-- Check fragmentation after maintenance
PRINT '';
PRINT '--- Fragmentation After Maintenance ---';
PRINT '';

SELECT 
    i.name AS IndexName,
    ps.avg_fragmentation_in_percent AS [Fragmentation %],
    ps.page_count AS PageCount,
    CASE 
        WHEN ps.avg_fragmentation_in_percent < 10 THEN 'Excellent'
        WHEN ps.avg_fragmentation_in_percent < 30 THEN 'Good'
        ELSE 'Needs Attention'
    END AS Status
FROM sys.dm_db_index_physical_stats(
    DB_ID(), 
    OBJECT_ID(@TableName), 
    NULL, 
    NULL, 
    'LIMITED'
) AS ps
INNER JOIN sys.indexes AS i 
    ON ps.object_id = i.object_id 
    AND ps.index_id = i.index_id
WHERE i.name IS NOT NULL
ORDER BY ps.avg_fragmentation_in_percent DESC;

-- Recommendations
PRINT '';
PRINT '--- Recommendations ---';
PRINT '';

IF EXISTS (SELECT 1 FROM @Results WHERE Status LIKE 'FAILED%')
BEGIN
    PRINT '⚠ Some indexes failed to maintain. Review error messages above.';
    PRINT '  Consider:';
    PRINT '  - Checking database permissions (ALTER permission required)';
    PRINT '  - Disabling ONLINE option if not using Enterprise Edition';
    PRINT '  - Increasing transaction log space';
    PRINT '';
END

IF EXISTS (
    SELECT 1 
    FROM sys.dm_db_index_physical_stats(DB_ID(), OBJECT_ID(@TableName), NULL, NULL, 'LIMITED') 
    WHERE avg_fragmentation_in_percent >= 30 AND page_count > @MinPageCount
)
BEGIN
    PRINT '⚠ High fragmentation still detected. Consider:';
    PRINT '  - Running this script again';
    PRINT '  - Rebuilding with FILLFACTOR lower than 100 to reduce future fragmentation';
    PRINT '  - Scheduling regular maintenance (weekly or monthly)';
    PRINT '';
END
ELSE
BEGIN
    PRINT '✓ All indexes are optimally maintained';
    PRINT '  Schedule next maintenance based on insert frequency:';
    PRINT '  - High activity (>10K inserts/day): Weekly';
    PRINT '  - Medium activity (1K-10K inserts/day): Bi-weekly';
    PRINT '  - Low activity (<1K inserts/day): Monthly';
    PRINT '';
END

PRINT '=====================================================================';

SET NOCOUNT OFF;
