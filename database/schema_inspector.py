"""
Schema inspection utilities for database metadata extraction.

Focuses on primary key detection, composite key handling, and schema validation
for mapping capture support in the sanitization framework.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import pyodbc
import logging

logger = logging.getLogger(__name__)


@dataclass
class PrimaryKeyInfo:
    """Primary key metadata for a table."""
    
    table_name: str
    schema_name: str
    pk_columns: List[str]  # Ordered by ORDINAL_POSITION
    is_composite: bool
    
    @property
    def has_pk(self) -> bool:
        """Check if table has primary key."""
        return len(self.pk_columns) > 0
    
    @property
    def qualified_name(self) -> str:
        """Get fully qualified table name."""
        return f"[{self.schema_name}].[{self.table_name}]"


class SchemaInspector:
    """
    Inspect database schema for metadata extraction.
    
    Provides utilities for extracting primary key information, building SQL
    expressions for PK serialization, and validating table structures.
    
    Thread-safe with internal caching for performance.
    """
    
    def __init__(self, connection_string: str):
        """
        Initialize inspector with database connection.
        
        Args:
            connection_string: SQL Server connection string
        """
        self.connection_string = connection_string
        self._pk_cache: Dict[str, PrimaryKeyInfo] = {}
    
    def get_primary_key_columns(
        self, 
        table_name: str, 
        schema_name: str = "dbo"
    ) -> PrimaryKeyInfo:
        """
        Extract primary key column names for a table.
        
        Args:
            table_name: Name of the table
            schema_name: Schema name (default: dbo)
            
        Returns:
            PrimaryKeyInfo with column names ordered by position
            
        Raises:
            SchemaInspectionError: If query fails
            
        Examples:
            >>> inspector = SchemaInspector(conn_str)
            >>> pk_info = inspector.get_primary_key_columns("Customers")
            >>> print(pk_info.pk_columns)
            ['CustomerID']
        """
        cache_key = f"{schema_name}.{table_name}"
        
        if cache_key in self._pk_cache:
            logger.debug(f"Using cached PK info for {cache_key}")
            return self._pk_cache[cache_key]
        
        query = """
        SELECT 
            c.COLUMN_NAME,
            c.ORDINAL_POSITION
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        INNER JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE c
            ON tc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
            AND tc.TABLE_SCHEMA = c.TABLE_SCHEMA
            AND tc.TABLE_NAME = c.TABLE_NAME
        WHERE 
            tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            AND tc.TABLE_NAME = ?
            AND tc.TABLE_SCHEMA = ?
        ORDER BY c.ORDINAL_POSITION
        """
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (table_name, schema_name))
                
                pk_columns = [row.COLUMN_NAME for row in cursor.fetchall()]
                
                pk_info = PrimaryKeyInfo(
                    table_name=table_name,
                    schema_name=schema_name,
                    pk_columns=pk_columns,
                    is_composite=len(pk_columns) > 1
                )
                
                self._pk_cache[cache_key] = pk_info
                
                if not pk_info.has_pk:
                    logger.warning(
                        f"Table {pk_info.qualified_name} has no primary key. "
                        f"Mapping capture will use ROW_NUMBER() as fallback. "
                        f"This limits record-level desanitization capabilities."
                    )
                
                return pk_info
                
        except pyodbc.Error as e:
            raise SchemaInspectionError(
                f"Failed to extract primary key for [{schema_name}].[{table_name}]: {e}"
            ) from e
    
    def build_pk_select_expression(self, pk_info: PrimaryKeyInfo) -> str:
        """
        Build SQL SELECT expression for primary key serialization.
        
        Returns SQL that creates JSON for composite PKs or string for single PK.
        For tables without PKs, returns ROW_NUMBER() fallback.
        
        Args:
            pk_info: Primary key metadata
            
        Returns:
            SQL expression for SELECT clause
            
        Examples:
            Single PK:
                "CAST([CustomerID] AS NVARCHAR(MAX))"
            
            Composite PK:
                "JSON_OBJECT('CustomerID', [CustomerID], 'OrderID', [OrderID])"
            
            No PK:
                "CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS NVARCHAR(MAX))"
        """
        if not pk_info.has_pk:
            # No PK - use ROW_NUMBER as fallback
            logger.debug(f"Using ROW_NUMBER fallback for {pk_info.qualified_name}")
            return "CAST(ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS NVARCHAR(MAX))"
        
        if not pk_info.is_composite:
            # Single PK - simple CAST to NVARCHAR
            return f"CAST([{pk_info.pk_columns[0]}] AS NVARCHAR(MAX))"
        
        # Composite PK - use JSON serialization with FOR JSON PATH
        # Compatible with SQL Server 2016+ (broader compatibility than JSON_OBJECT from SQL Server 2022+)
        # 
        # FOR JSON PATH produces: {"col1": value1, "col2": value2}
        # WITHOUT_ARRAY_WRAPPER removes the outer array brackets for clean JSON object
        column_list = ", ".join(f"[{col}]" for col in pk_info.pk_columns)
        
        return f"(SELECT {column_list} FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)"
    
    def build_pk_where_clause(
        self, 
        pk_info: PrimaryKeyInfo, 
        record_id_column: str = "r.record_id"
    ) -> str:
        """
        Build WHERE clause for matching records by primary key.
        
        Used in desanitization UPDATE-JOIN queries to match records
        from the mapping table back to the original table.
        
        Args:
            pk_info: Primary key metadata
            record_id_column: Column reference containing record_id (default: r.record_id)
            
        Returns:
            SQL WHERE clause for PK matching
            
        Raises:
            SchemaInspectionError: If table has no PK (cannot build reliable WHERE clause)
            
        Examples:
            Single PK:
                "[CustomerID] = CAST(r.record_id AS INT)"
            
            Composite PK:
                "[CustomerID] = JSON_VALUE(r.record_id, '$.CustomerID') 
                 AND [OrderID] = JSON_VALUE(r.record_id, '$.OrderID')"
        """
        if not pk_info.has_pk:
            raise SchemaInspectionError(
                f"Cannot build WHERE clause for table without PK: {pk_info.qualified_name}. "
                f"Tables without primary keys support column-level restore only, not record-level."
            )
        
        if not pk_info.is_composite:
            # Single PK - direct comparison
            # Note: May need type casting based on actual column type
            # For simplicity, assuming record_id is already correct type or castable
            return f"[{pk_info.pk_columns[0]}] = {record_id_column}"
        
        # Composite PK - JSON extraction
        conditions = []
        for col in pk_info.pk_columns:
            json_path = f"$.{col}"
            conditions.append(
                f"[{col}] = JSON_VALUE({record_id_column}, '{json_path}')"
            )
        
        return " AND ".join(conditions)
    
    def validate_table_exists(
        self, 
        table_name: str, 
        schema_name: str = "dbo"
    ) -> bool:
        """
        Check if table exists in schema.
        
        Args:
            table_name: Name of the table
            schema_name: Schema name (default: dbo)
            
        Returns:
            True if table exists, False otherwise
        """
        query = """
        SELECT COUNT(*) 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_NAME = ? AND TABLE_SCHEMA = ?
        """
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (table_name, schema_name))
                count = cursor.fetchone()[0]
                return count > 0
        except pyodbc.Error as e:
            logger.error(f"Error checking table existence: {e}")
            return False
    
    def get_column_info(
        self,
        table_name: str,
        column_name: str,
        schema_name: str = "dbo"
    ) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a specific column.
        
        Args:
            table_name: Name of the table
            column_name: Name of the column
            schema_name: Schema name (default: dbo)
            
        Returns:
            Dictionary with column metadata or None if not found
        """
        query = """
        SELECT 
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ? 
          AND COLUMN_NAME = ?
          AND TABLE_SCHEMA = ?
        """
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (table_name, column_name, schema_name))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                return {
                    "data_type": row.DATA_TYPE,
                    "max_length": row.CHARACTER_MAXIMUM_LENGTH,
                    "is_nullable": row.IS_NULLABLE == "YES"
                }
        except pyodbc.Error as e:
            logger.error(f"Error fetching column info: {e}")
            return None
    
    def clear_cache(self):
        """Clear the internal PK cache. Useful for testing or schema changes."""
        self._pk_cache.clear()
        logger.debug("PK cache cleared")


class SchemaInspectionError(Exception):
    """Raised when schema inspection fails."""
    
    def __init__(self, message: str, suggested_action: Optional[str] = None):
        """
        Initialize error with optional suggested action.
        
        Args:
            message: Error description
            suggested_action: Optional remediation guidance
        """
        self.suggested_action = suggested_action
        super().__init__(message)
    
    def __str__(self):
        """Format error message with suggested action if available."""
        msg = super().__str__()
        if self.suggested_action:
            msg += f"\n\nSuggested action: {self.suggested_action}"
        return msg
