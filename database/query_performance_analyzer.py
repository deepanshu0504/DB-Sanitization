"""
Query Performance Analyzer for mapping table optimization.

This module provides tools for analyzing query performance, index usage,
and fragmentation to optimize mapping lookups.

Story 5.3: Optimized Mapping Lookups
"""

import json
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any

import pyodbc


@dataclass
class QueryPlanAnalysis:
    """Analysis results for a specific query."""
    query_text: str
    execution_count: int
    total_logical_reads: int
    total_elapsed_time_ms: float
    avg_elapsed_time_ms: float
    total_worker_time_ms: float
    plan_xml: Optional[str] = None
    estimated_rows: Optional[int] = None
    actual_rows: Optional[int] = None
    index_usage: List[str] = None
    warnings: List[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class IndexFragmentation:
    """Fragmentation statistics for an index."""
    index_name: str
    table_name: str
    schema_name: str
    fragmentation_percent: float
    page_count: int
    avg_fragmentation_percent: float
    index_type_desc: str
    alloc_unit_type_desc: str
    recommendation: str  # REORGANIZE, REBUILD, or OK
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class IndexUsageStats:
    """Usage statistics for an index."""
    index_name: str
    table_name: str
    schema_name: str
    user_seeks: int
    user_scans: int
    user_lookups: int
    user_updates: int
    last_user_seek: Optional[datetime]
    last_user_scan: Optional[datetime]
    last_user_lookup: Optional[datetime]
    total_reads: int  # seeks + scans + lookups
    read_write_ratio: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to string
        for key in ['last_user_seek', 'last_user_scan', 'last_user_lookup']:
            if data[key]:
                data[key] = data[key].isoformat()
        return data


class QueryPerformanceAnalyzer:
    """
    Analyze query performance and index health for mapping table.
    
    Features:
    - Query execution plan analysis
    - Index fragmentation detection
    - Index usage statistics
    - Performance recommendations
    
    Usage:
        analyzer = QueryPerformanceAnalyzer(connection_string, "token_mappings")
        
        # Check index fragmentation
        fragmentation = analyzer.get_index_fragmentation()
        for idx in fragmentation:
            if idx.fragmentation_percent > 30:
                print(f"REBUILD {idx.index_name}")
        
        # Analyze index usage
        usage = analyzer.get_index_usage_stats()
        for idx in usage:
            if idx.total_reads == 0:
                print(f"Unused index: {idx.index_name}")
    """
    
    def __init__(
        self,
        connection_string: str,
        table_name: str = "token_mappings",
        schema: str = "dbo"
    ):
        """
        Initialize QueryPerformanceAnalyzer.
        
        Args:
            connection_string: SQL Server connection string
            table_name: Name of mapping table (default: token_mappings)
            schema: Database schema (default: dbo)
        """
        self.connection_string = connection_string
        self.table_name = table_name
        self.schema = schema
        self.fully_qualified_table = f"[{schema}].[{table_name}]"
    
    def get_index_fragmentation(
        self,
        fragmentation_threshold: float = 5.0
    ) -> List[IndexFragmentation]:
        """
        Analyze index fragmentation for mapping table.
        
        Args:
            fragmentation_threshold: Minimum fragmentation % to report (default: 5.0)
            
        Returns:
            List of IndexFragmentation objects with recommendations
            
        Raises:
            pyodbc.Error: If query fails
            
        Notes:
            - Fragmentation < 10%: OK, no action needed
            - Fragmentation 10-30%: REORGANIZE recommended
            - Fragmentation > 30%: REBUILD recommended
        """
        query = """
            SELECT 
                i.name AS index_name,
                OBJECT_NAME(ps.object_id) AS table_name,
                OBJECT_SCHEMA_NAME(ps.object_id) AS schema_name,
                ps.avg_fragmentation_in_percent,
                ps.page_count,
                i.type_desc AS index_type_desc,
                ps.alloc_unit_type_desc
            FROM sys.dm_db_index_physical_stats(
                DB_ID(), 
                OBJECT_ID(?), 
                NULL, 
                NULL, 
                'LIMITED'
            ) AS ps
            INNER JOIN sys.indexes AS i 
                ON ps.object_id = i.object_id 
                AND ps.index_id = i.index_id
            WHERE ps.avg_fragmentation_in_percent >= ?
                AND ps.page_count > 100  -- Skip small indexes
            ORDER BY ps.avg_fragmentation_in_percent DESC;
        """
        
        results = []
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (self.fully_qualified_table, fragmentation_threshold))
                
                for row in cursor.fetchall():
                    fragmentation_pct = row.avg_fragmentation_in_percent
                    
                    # Determine recommendation
                    if fragmentation_pct < 10:
                        recommendation = "OK"
                    elif fragmentation_pct < 30:
                        recommendation = "REORGANIZE"
                    else:
                        recommendation = "REBUILD"
                    
                    results.append(IndexFragmentation(
                        index_name=row.index_name,
                        table_name=row.table_name,
                        schema_name=row.schema_name,
                        fragmentation_percent=round(fragmentation_pct, 2),
                        page_count=row.page_count,
                        avg_fragmentation_percent=round(fragmentation_pct, 2),
                        index_type_desc=row.index_type_desc,
                        alloc_unit_type_desc=row.alloc_unit_type_desc,
                        recommendation=recommendation
                    ))
                
        except pyodbc.Error:
            raise
        
        return results
    
    def get_index_usage_stats(self) -> List[IndexUsageStats]:
        """
        Get index usage statistics for mapping table.
        
        Returns:
            List of IndexUsageStats objects showing read/write patterns
            
        Notes:
            - High reads + low writes = Good index
            - Low reads + high writes = Consider removing
            - Zero reads = Unused index (maintenance overhead)
        """
        query = """
            SELECT 
                i.name AS index_name,
                OBJECT_NAME(ius.object_id) AS table_name,
                OBJECT_SCHEMA_NAME(ius.object_id) AS schema_name,
                ISNULL(ius.user_seeks, 0) AS user_seeks,
                ISNULL(ius.user_scans, 0) AS user_scans,
                ISNULL(ius.user_lookups, 0) AS user_lookups,
                ISNULL(ius.user_updates, 0) AS user_updates,
                ius.last_user_seek,
                ius.last_user_scan,
                ius.last_user_lookup
            FROM sys.indexes AS i
            LEFT JOIN sys.dm_db_index_usage_stats AS ius
                ON i.object_id = ius.object_id
                AND i.index_id = ius.index_id
                AND ius.database_id = DB_ID()
            WHERE i.object_id = OBJECT_ID(?)
                AND i.name IS NOT NULL  -- Skip heap
            ORDER BY i.name;
        """
        
        results = []
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (self.fully_qualified_table,))
                
                for row in cursor.fetchall():
                    total_reads = row.user_seeks + row.user_scans + row.user_lookups
                    writes = row.user_updates
                    
                    # Calculate read/write ratio
                    if writes > 0:
                        ratio = total_reads / writes
                    else:
                        ratio = float('inf') if total_reads > 0 else 0.0
                    
                    results.append(IndexUsageStats(
                        index_name=row.index_name,
                        table_name=row.table_name,
                        schema_name=row.schema_name,
                        user_seeks=row.user_seeks,
                        user_scans=row.user_scans,
                        user_lookups=row.user_lookups,
                        user_updates=row.user_updates,
                        last_user_seek=row.last_user_seek,
                        last_user_scan=row.last_user_scan,
                        last_user_lookup=row.last_user_lookup,
                        total_reads=total_reads,
                        read_write_ratio=ratio
                    ))
                
        except pyodbc.Error:
            raise
        
        return results
    
    def get_missing_indexes(self) -> List[Dict[str, Any]]:
        """
        Get missing index recommendations from SQL Server query optimizer.
        
        Returns:
            List of dictionaries with missing index details
            
        Notes:
            - SQL Server tracks potential indexes that could improve performance
            - These are suggestions based on query patterns since last restart
        """
        query = """
            SELECT 
                mid.statement AS table_name,
                migs.avg_total_user_cost * (migs.avg_user_impact / 100.0) * 
                    (migs.user_seeks + migs.user_scans) AS improvement_measure,
                'CREATE INDEX [IX_' + OBJECT_NAME(mid.object_id) + '_' + 
                    REPLACE(REPLACE(REPLACE(ISNULL(mid.equality_columns,''),', ','_'),']',''),'[','') + ']' +
                    ' ON ' + mid.statement + 
                    ' (' + ISNULL(mid.equality_columns,'') + 
                    CASE WHEN mid.inequality_columns IS NOT NULL 
                         THEN CASE WHEN mid.equality_columns IS NOT NULL THEN ',' ELSE '' END + mid.inequality_columns 
                         ELSE '' 
                    END + ')' +
                    CASE WHEN mid.included_columns IS NOT NULL 
                         THEN ' INCLUDE (' + mid.included_columns + ')' 
                         ELSE '' 
                    END AS create_index_statement,
                migs.user_seeks,
                migs.user_scans,
                migs.last_user_seek,
                migs.last_user_scan
            FROM sys.dm_db_missing_index_group_stats AS migs
            INNER JOIN sys.dm_db_missing_index_groups AS mig
                ON migs.group_handle = mig.index_group_handle
            INNER JOIN sys.dm_db_missing_index_details AS mid
                ON mig.index_handle = mid.index_handle
            WHERE mid.database_id = DB_ID()
                AND mid.object_id = OBJECT_ID(?)
            ORDER BY improvement_measure DESC;
        """
        
        results = []
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (self.fully_qualified_table,))
                
                columns = [col[0] for col in cursor.description]
                for row in cursor.fetchall():
                    result_dict = dict(zip(columns, row))
                    # Convert datetime to string for JSON serialization
                    if result_dict.get('last_user_seek'):
                        result_dict['last_user_seek'] = result_dict['last_user_seek'].isoformat()
                    if result_dict.get('last_user_scan'):
                        result_dict['last_user_scan'] = result_dict['last_user_scan'].isoformat()
                    results.append(result_dict)
                
        except pyodbc.Error:
            raise
        
        return results
    
    def analyze_query_performance(
        self,
        sample_query: Optional[str] = None
    ) -> QueryPlanAnalysis:
        """
        Analyze performance of a specific query or sample mapping lookup.
        
        Args:
            sample_query: Optional SQL query to analyze (default: sample mapping lookup)
            
        Returns:
            QueryPlanAnalysis with execution plan and metrics
        """
        if sample_query is None:
            # Default to analyzing a typical mapping lookup query
            sample_query = f"""
                SELECT original_value, masked_value, record_id
                FROM {self.fully_qualified_table}
                WHERE table_name = 'Customers'
                    AND column_name = 'Email'
                    AND batch_id = 'BATCH-001'
            """
        
        # Enable actual execution plan
        enable_plan_sql = "SET SHOWPLAN_XML ON;"
        disable_plan_sql = "SET SHOWPLAN_XML OFF;"
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                
                # Get execution plan
                try:
                    cursor.execute(enable_plan_sql)
                    cursor.execute(sample_query)
                    plan_row = cursor.fetchone()
                    plan_xml = plan_row[0] if plan_row else None
                    cursor.execute(disable_plan_sql)
                except:
                    plan_xml = None
                
                # Get query stats from DMV
                stats_query = """
                    SELECT TOP 1
                        execution_count,
                        total_logical_reads,
                        total_elapsed_time / 1000.0 AS total_elapsed_time_ms,
                        (total_elapsed_time / execution_count) / 1000.0 AS avg_elapsed_time_ms,
                        total_worker_time / 1000.0 AS total_worker_time_ms
                    FROM sys.dm_exec_query_stats AS qs
                    CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
                    WHERE st.text LIKE ?
                    ORDER BY last_execution_time DESC;
                """
                
                cursor.execute(stats_query, (f'%{sample_query[:50]}%',))
                stats_row = cursor.fetchone()
                
                if stats_row:
                    return QueryPlanAnalysis(
                        query_text=sample_query,
                        execution_count=stats_row[0],
                        total_logical_reads=stats_row[1],
                        total_elapsed_time_ms=round(stats_row[2], 2),
                        avg_elapsed_time_ms=round(stats_row[3], 2),
                        total_worker_time_ms=round(stats_row[4], 2),
                        plan_xml=plan_xml,
                        warnings=[]
                    )
                else:
                    # Query not in cache - return basic analysis
                    return QueryPlanAnalysis(
                        query_text=sample_query,
                        execution_count=0,
                        total_logical_reads=0,
                        total_elapsed_time_ms=0.0,
                        avg_elapsed_time_ms=0.0,
                        total_worker_time_ms=0.0,
                        plan_xml=plan_xml,
                        warnings=["Query not found in plan cache - may not have been executed recently"]
                    )
                
        except pyodbc.Error:
            raise
    
    def export_analysis_report(
        self,
        output_file: str,
        include_plan_xml: bool = False
    ) -> None:
        """
        Generate comprehensive performance analysis report.
        
        Args:
            output_file: Path to output JSON file
            include_plan_xml: Include XML execution plans (can be large)
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "table": self.fully_qualified_table,
            "index_fragmentation": [
                idx.to_dict() for idx in self.get_index_fragmentation(fragmentation_threshold=0)
            ],
            "index_usage": [
                idx.to_dict() for idx in self.get_index_usage_stats()
            ],
            "missing_indexes": self.get_missing_indexes()
        }
        
        # Add query analysis if requested
        if include_plan_xml:
            analysis = self.analyze_query_performance()
            report["sample_query_analysis"] = analysis.to_dict()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
    
    def get_table_size_stats(self) -> Dict[str, Any]:
        """
        Get size statistics for mapping table.
        
        Returns:
            Dictionary with row count, size in MB, index sizes
        """
        query = """
            SELECT 
                p.rows AS row_count,
                SUM(a.total_pages) * 8 / 1024.0 AS total_size_mb,
                SUM(a.used_pages) * 8 / 1024.0 AS data_size_mb,
                (SUM(a.total_pages) - SUM(a.used_pages)) * 8 / 1024.0 AS unused_size_mb
            FROM sys.partitions p
            INNER JOIN sys.allocation_units a 
                ON p.partition_id = a.container_id
            WHERE p.object_id = OBJECT_ID(?)
                AND p.index_id IN (0, 1)  -- Heap or clustered index
            GROUP BY p.rows;
        """
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (self.fully_qualified_table,))
                row = cursor.fetchone()
                
                if row:
                    return {
                        "row_count": row.row_count,
                        "total_size_mb": round(row.total_size_mb, 2),
                        "data_size_mb": round(row.data_size_mb, 2),
                        "unused_size_mb": round(row.unused_size_mb, 2)
                    }
                else:
                    return {
                        "row_count": 0,
                        "total_size_mb": 0.0,
                        "data_size_mb": 0.0,
                        "unused_size_mb": 0.0
                    }
                
        except pyodbc.Error:
            raise
