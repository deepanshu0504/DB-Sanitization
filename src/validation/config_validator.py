"""
Configuration validator for PII sanitization schema validation.

This module provides comprehensive validation of PII configuration files against
actual database schema, checking for column existence, data type compatibility,
nullable constraints, and foreign key/primary key dependencies.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from typing import Dict, List, Optional, Set, Tuple, Any

from ..config.config_models import SanitizationConfig, PIIColumnConfig
from ..database.schema_extractor import SchemaExtractor
from ..database.name_normalizer import (
    normalize_identifier,
    build_qualified_name,
    CaseInsensitiveDict,
    identifiers_match
)
from ..error_codes import ErrorCodes
from ..logging.logger import get_logger
from .validation_result import ValidationResult, IssueSeverity

logger = get_logger(__name__)


class ConfigValidator:
    """
    Validates PII configuration against actual database schema.
    
    Performs comprehensive validation including:
    - Column existence (schema, table, column must exist)
    - Data type compatibility (SQL type must support PII masking strategy)
    - Nullable constraint validation (config must match schema)
    - Foreign key dependency warnings
    - Primary key column warnings
    - Special column checks (identity, computed, system tables)
    
    Attributes:
        schema_extractor: SchemaExtractor instance for metadata retrieval
        strict_mode: If True, warnings also block validation (default: False)
    
    Example:
        >>> validator = ConfigValidator(schema_extractor)
        >>> result = validator.validate_config(config)
        >>> if not result.is_valid:
        ...     print(result.format_summary())
        ...     raise ValueError("Configuration validation failed")
    """
    
    # PII type to compatible SQL Server data types mapping
    PII_DATA_TYPE_COMPATIBILITY = {
        "email": {"VARCHAR", "NVARCHAR", "TEXT", "NTEXT", "CHAR", "NCHAR"},
        "phone": {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR"},
        "name": {"VARCHAR", "NVARCHAR", "TEXT", "NTEXT"},
        "ssn": {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR"},
        "generic": {"VARCHAR", "NVARCHAR", "TEXT", "NTEXT", "CHAR", "NCHAR"},
        "address": {"VARCHAR", "NVARCHAR", "TEXT", "NTEXT", "CHAR", "NCHAR"},
        "credit_card": {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR"},
        "date_of_birth": {"DATE", "DATETIME", "DATETIME2", "SMALLDATETIME", "VARCHAR", "NVARCHAR"},
        "ip_address": {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR"},
        "account_number": {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "BIGINT", "INT"}
    }
    
    # Minimum length requirements for specific PII types
    MIN_LENGTH_REQUIREMENTS = {
        "email": 7,  # user@x.c
        "phone": 10,  # US: (555)123-4567 or 5551234567
        "ssn": 11,  # XXX-XX-XXXX format
        "credit_card": 13,  # Minimum credit card length
        "address": 10,  # 123 Oak St (minimum viable address)
        "date_of_birth": 4,  # YYYY (year only format)
        "ip_address": 7,  # 0.0.0.0
        "name": 2,  # Minimum 2 chars for single letter names (e.g., "Li", "Wu")
    }
    
    # System schemas to warn about
    SYSTEM_SCHEMAS = {"sys", "INFORMATION_SCHEMA", "guest", "db_owner", "db_accessadmin"}
    
    def __init__(
        self,
        schema_extractor: SchemaExtractor,
        strict_mode: bool = False
    ):
        """
        Initialize configuration validator.
        
        Args:
            schema_extractor: SchemaExtractor instance for database metadata
            strict_mode: If True, warnings also block validation (default: False)
        """
        self.schema_extractor = schema_extractor
        self.strict_mode = strict_mode
        logger.info(f"ConfigValidator initialized (strict_mode={strict_mode})")
    
    def validate_config(self, config: SanitizationConfig) -> ValidationResult:
        """
        Validate complete PII configuration against database schema.
        
        Performs all validation checks:
        - Column existence
        - Data type compatibility
        - Nullable constraints
        - Foreign key dependencies
        - Primary key warnings
        
        Args:
            config: Sanitization configuration to validate
        
        Returns:
            ValidationResult with errors, warnings, and info messages
        
        Example:
            >>> result = validator.validate_config(config)
            >>> print(result.is_valid)
            True
            >>> print(result.warning_count)
            2
        """
        result = ValidationResult()
        
        logger.info(f"Validating configuration with {len(config.pii_columns)} PII columns")
        
        # Early return if no columns to validate
        if not config.pii_columns:
            result.add_info("No PII columns configured for validation")
            return result
        
        # Extract schema metadata once for all validations
        try:
            schema_metadata = self._extract_schema_metadata(config)
        except Exception as e:
            result.add_error(
                f"Failed to extract database schema metadata: {str(e)}",
                code=ErrorCodes.SCHEMA_EXTRACTION_FAILED,
                suggested_action="Verify database connection and permissions"
            )
            return result
        
        # Validate each PII column
        for pii_col in config.pii_columns:
            self._validate_single_column(pii_col, schema_metadata, result)
        
        # Log validation summary
        logger.info(
            f"Validation completed: {result.error_count} errors, "
            f"{result.warning_count} warnings, {result.info_count} infos"
        )
        
        return result
    
    def validate_single_column(
        self,
        pii_col: PIIColumnConfig,
        schema_metadata: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate a single PII column configuration.
        
        Useful for interactive validation when user adds a new column.
        
        Args:
            pii_col: Single PII column configuration to validate
            schema_metadata: Pre-extracted schema metadata (optional, will extract if None)
        
        Returns:
            ValidationResult for the single column
        
        Example:
            >>> new_col = PIIColumnConfig(
            ...     schema="dbo", table="Users", column="Email",
            ...     pii_type="email", nullable=True
            ... )
            >>> result = validator.validate_single_column(new_col)
        """
        result = ValidationResult()
        
        # Extract metadata if not provided
        if schema_metadata is None:
            try:
                # Create minimal config for single column
                from ..config.config_models import SanitizationConfig, DatabaseConfig
                temp_config = SanitizationConfig(
                    database=DatabaseConfig(
                        server="",  # Placeholder, schema_extractor already has connection
                        database="",
                        auth_type="windows"
                    ),
                    pii_columns=[pii_col]
                )
                schema_metadata = self._extract_schema_metadata(temp_config)
            except Exception as e:
                result.add_error(
                    f"Failed to extract schema metadata: {str(e)}",
                    column=pii_col.fully_qualified_name,
                    code=ErrorCodes.SCHEMA_EXTRACTION_FAILED
                )
                return result
        
        self._validate_single_column(pii_col, schema_metadata, result)
        return result
    
    def _extract_schema_metadata(self, config: SanitizationConfig) -> Dict[str, Any]:
        """
        Extract necessary schema metadata for validation.
        
        Args:
            config: Configuration with PII columns to extract metadata for
        
        Returns:
            Dictionary with schemas, tables, columns, PKs, FKs metadata using
            case-insensitive lookups for all database object names
        
        Raises:
            Exception: If schema extraction fails
        """
        # Get unique schemas and tables from config
        schemas_to_check = set(col.schema for col in config.pii_columns)
        
        # Use CaseInsensitiveDict for all object name lookups
        metadata = {
            "schemas": CaseInsensitiveDict(),
            "tables": CaseInsensitiveDict(),
            "columns": CaseInsensitiveDict(),
            "primary_keys": CaseInsensitiveDict(),
            "foreign_keys": []
        }
        
        # Extract schemas
        all_schemas = self.schema_extractor.get_schemas()
        for schema_info in all_schemas:
            metadata["schemas"][schema_info["schema_name"]] = schema_info
        
        # Extract tables and columns for each schema
        for schema in schemas_to_check:
            if schema not in metadata["schemas"]:
                continue
            
            tables = self.schema_extractor.get_tables(schema)
            for table_info in tables:
                table_name = table_info["table_name"]
                # Use normalized qualified name for case-insensitive lookup
                qualified_name = build_qualified_name(schema, table_name, normalize=True)
                metadata["tables"][qualified_name] = table_info
                
                # Get columns for this table - use CaseInsensitiveDict
                columns = self.schema_extractor.get_columns(schema, table_name)
                metadata["columns"][qualified_name] = CaseInsensitiveDict(
                    {col["column_name"]: col for col in columns}
                )
        
        # Extract primary keys
        for schema in schemas_to_check:
            if schema not in metadata["schemas"]:
                continue
            
            pks = self.schema_extractor.get_primary_keys(schema)
            for pk in pks:
                qualified_name = build_qualified_name(pk['schema'], pk['table'], normalize=True)
                if qualified_name not in metadata["primary_keys"]:
                    metadata["primary_keys"][qualified_name] = []
                metadata["primary_keys"][qualified_name].append(pk["column"])
        
        # Extract foreign keys
        for schema in schemas_to_check:
            if schema not in metadata["schemas"]:
                continue
            
            fks = self.schema_extractor.get_foreign_keys(schema)
            metadata["foreign_keys"].extend(fks)
        
        return metadata
    
    def _validate_single_column(
        self,
        pii_col: PIIColumnConfig,
        schema_metadata: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """
        Perform all validations for a single PII column.
        
        Args:
            pii_col: PII column configuration to validate
            schema_metadata: Extracted schema metadata
            result: ValidationResult to accumulate issues
        """
        qualified_name = pii_col.fully_qualified_name
        # Use normalized qualified name for case-insensitive lookups
        qualified_table = build_qualified_name(pii_col.schema, pii_col.table, normalize=True)
        
        # 1. Validate column existence
        column_info = self._validate_column_existence(
            pii_col, schema_metadata, result
        )
        
        # If column doesn't exist, skip further validations
        if column_info is None:
            return
        
        # 2. Validate data type compatibility
        self._validate_data_type_compatibility(
            pii_col, column_info, result
        )
        
        # 3. Validate nullable constraints
        self._validate_nullable_constraints(
            pii_col, column_info, result
        )
        
        # 4. Check for identity columns (error)
        if column_info.get("is_identity"):
            result.add_error(
                f"Column is an IDENTITY column and cannot be sanitized",
                column=qualified_name,
                code=ErrorCodes.IDENTITY_COLUMN_ERROR,
                suggested_action="Remove identity column from PII configuration"
            )
        
        # 5. Check for computed columns (warning)
        if column_info.get("is_computed"):
            result.add_warning(
                f"Column is a computed column - sanitization may fail",
                column=qualified_name,
                code=ErrorCodes.COMPUTED_COLUMN_WARNING,
                suggested_action="Verify that computed column can be updated"
            )
        
        # 6. Validate primary key columns
        self._validate_pk_columns(pii_col, qualified_table, schema_metadata, result)
        
        # 7. Validate foreign key columns
        self._validate_fk_columns(pii_col, schema_metadata, result)
    
    def _validate_column_existence(
        self,
        pii_col: PIIColumnConfig,
        schema_metadata: Dict[str, Any],
        result: ValidationResult
    ) -> Optional[Dict[str, Any]]:
        """
        Validate that schema, table, and column exist in database.
        
        Uses case-insensitive comparison for all database object names to ensure
        compatibility with any SQL Server collation or naming convention.
        
        Args:
            pii_col: PII column configuration
            schema_metadata: Extracted schema metadata with CaseInsensitiveDicts
            result: ValidationResult to accumulate issues
        
        Returns:
            Column metadata dictionary if exists, None otherwise
        """
        qualified_name = pii_col.fully_qualified_name
        # Use normalized qualified name for lookups (case-insensitive)
        qualified_table = build_qualified_name(pii_col.schema, pii_col.table, normalize=True)
        
        # Check schema exists (case-insensitive via CaseInsensitiveDict)
        if pii_col.schema not in schema_metadata["schemas"]:
            result.add_error(
                f"Schema '{pii_col.schema}' does not exist in database",
                column=qualified_name,
                code=ErrorCodes.SCHEMA_NOT_FOUND,
                suggested_action=f"Verify schema name or create schema '{pii_col.schema}'"
            )
            return None
        
        # Warn about system schemas
        if pii_col.schema.lower() in [s.lower() for s in self.SYSTEM_SCHEMAS]:
            result.add_warning(
                f"Schema '{pii_col.schema}' is a system schema",
                column=qualified_name,
                code=ErrorCodes.SYSTEM_TABLE_WARNING,
                suggested_action="Sanitizing system tables is not recommended"
            )
        
        # Warn about temporary tables
        if pii_col.table.startswith("#"):
            result.add_error(
                f"Table '{pii_col.table}' appears to be a temporary table",
                column=qualified_name,
                code=ErrorCodes.TEMP_TABLE_ERROR,
                suggested_action="Temporary tables cannot be sanitized"
            )
            return None
        
        # Check table exists (case-insensitive via CaseInsensitiveDict)
        if qualified_table not in schema_metadata["tables"]:
            result.add_error(
                f"Table '{pii_col.table}' does not exist in schema '{pii_col.schema}'",
                column=qualified_name,
                code=ErrorCodes.TABLE_NOT_FOUND_IN_SCHEMA,
                suggested_action=f"Verify table name or check schema '{pii_col.schema}'"
            )
            return None
        
        # Check if it's a view (warning)
        table_info = schema_metadata["tables"][qualified_table]
        if table_info.get("table_type") == "VIEW":
            result.add_warning(
                f"'{pii_col.table}' is a VIEW, not a base table",
                column=qualified_name,
                code=ErrorCodes.VIEW_SANITIZATION_WARNING,
                suggested_action="Sanitizing views may not work as expected - sanitize base tables instead"
            )
        
        # Check column exists (case-insensitive via CaseInsensitiveDict)
        if qualified_table not in schema_metadata["columns"]:
            result.add_error(
                f"No column metadata found for table '{qualified_table}'",
                column=qualified_name,
                code=ErrorCodes.INVALID_METADATA
            )
            return None
        
        table_columns = schema_metadata["columns"][qualified_table]
        if pii_col.column not in table_columns:
            result.add_error(
                f"Column '{pii_col.column}' does not exist in table '{qualified_table}'",
                column=qualified_name,
                code=ErrorCodes.COLUMN_NOT_FOUND_IN_TABLE,
                suggested_action=f"Verify column name in table '{qualified_table}'"
            )
            return None
        
        return table_columns[pii_col.column]
    
    def _validate_data_type_compatibility(
        self,
        pii_col: PIIColumnConfig,
        column_info: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """
        Validate that column data type is compatible with PII masking strategy.
        
        Args:
            pii_col: PII column configuration
            column_info: Column metadata from schema
            result: ValidationResult to accumulate issues
        """
        qualified_name = pii_col.fully_qualified_name
        data_type = column_info["data_type"].upper()
        pii_type = pii_col.pii_type.lower()
        
        # Check if PII type is known
        if pii_type not in self.PII_DATA_TYPE_COMPATIBILITY:
            result.add_warning(
                f"Unknown PII type '{pii_type}' - cannot verify data type compatibility",
                column=qualified_name,
                suggested_action="Use standard PII types or verify custom masking strategy"
            )
            return
        
        # Get compatible types for this PII type
        compatible_types = self.PII_DATA_TYPE_COMPATIBILITY[pii_type]
        
        # Check compatibility
        if data_type not in compatible_types:
            result.add_error(
                f"Data type '{data_type}' is incompatible with PII type '{pii_type}'",
                column=qualified_name,
                code=ErrorCodes.INCOMPATIBLE_DATA_TYPE,
                suggested_action=f"Change column to one of: {', '.join(compatible_types)}"
            )
            return
        
        # Check minimum length requirements for string types
        if pii_type in self.MIN_LENGTH_REQUIREMENTS:
            min_length = self.MIN_LENGTH_REQUIREMENTS[pii_type]
            
            # Get actual column length
            max_length = column_info.get("max_length")
            if max_length and max_length != -1:  # -1 means VARCHAR(MAX)
                # For NVARCHAR, max_length is in bytes (2 bytes per char)
                if data_type.startswith("N"):
                    actual_length = max_length // 2
                else:
                    actual_length = max_length
                
                if actual_length < min_length:
                    result.add_error(
                        f"Column length ({actual_length}) is insufficient for PII type '{pii_type}' (minimum: {min_length})",
                        column=qualified_name,
                        code=ErrorCodes.INSUFFICIENT_COLUMN_LENGTH,
                        suggested_action=f"Increase column length to at least {min_length} characters"
                    )
        
        # Info note for MAX types
        if column_info.get("is_max_type"):
            result.add_info(
                f"Column uses MAX length - sufficient for any masked data",
                column=qualified_name
            )
        
        # Warning for CHAR (fixed length with trailing spaces)
        if data_type in {"CHAR", "NCHAR"}:
            result.add_warning(
                f"Column is fixed-length ({data_type}) - masked data will be padded with spaces",
                column=qualified_name,
                suggested_action="Consider using VARCHAR/NVARCHAR for variable-length data"
            )
    
    def _validate_nullable_constraints(
        self,
        pii_col: PIIColumnConfig,
        column_info: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """
        Validate that nullable configuration matches schema definition.
        
        Args:
            pii_col: PII column configuration
            column_info: Column metadata from schema
            result: ValidationResult to accumulate issues
        """
        qualified_name = pii_col.fully_qualified_name
        schema_nullable = column_info.get("is_nullable", True)
        config_nullable = pii_col.nullable
        
        # Error if config says nullable but schema is NOT NULL
        if config_nullable and not schema_nullable:
            result.add_error(
                f"Configuration marks column as nullable, but schema defines NOT NULL constraint",
                column=qualified_name,
                code=ErrorCodes.NULLABLE_MISMATCH,
                suggested_action="Change configuration nullable=False to match schema"
            )
        
        # Warning if config says not nullable but schema allows NULL
        elif not config_nullable and schema_nullable:
            result.add_warning(
                f"Configuration marks column as non-nullable, but schema allows NULL values",
                column=qualified_name,
                code=ErrorCodes.NULLABLE_MISMATCH,
                suggested_action="Verify NULL values don't exist or set nullable=True in configuration"
            )
    
    def _validate_pk_columns(
        self,
        pii_col: PIIColumnConfig,
        qualified_table: str,
        schema_metadata: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """
        Validate primary key column sanitization risks.
        
        Args:
            pii_col: PII column configuration
            qualified_table: Fully qualified table name
            schema_metadata: Extracted schema metadata
            result: ValidationResult to accumulate issues
        """
        qualified_name = pii_col.fully_qualified_name
        
        # Check if column is part of primary key
        if qualified_table in schema_metadata["primary_keys"]:
            pk_columns = schema_metadata["primary_keys"][qualified_table]
            
            if pii_col.column in pk_columns:
                # Check if this PK is referenced by foreign keys
                is_referenced = any(
                    fk["parent_schema"] == pii_col.schema and
                    fk["parent_table"] == pii_col.table and
                    fk["parent_column"] == pii_col.column
                    for fk in schema_metadata["foreign_keys"]
                )
                
                if is_referenced:
                    result.add_warning(
                        f"Column is a PRIMARY KEY referenced by foreign keys - sanitizing will break referential integrity",
                        column=qualified_name,
                        code=ErrorCodes.PK_COLUMN_WARNING,
                        suggested_action="Use mapping tables to preserve relationships or sanitize all dependent columns"
                    )
                else:
                    result.add_warning(
                        f"Column is a PRIMARY KEY - sanitizing will change unique identifier",
                        column=qualified_name,
                        code=ErrorCodes.PK_COLUMN_WARNING,
                        suggested_action="Ensure mapping tables are maintained for data restoration"
                    )
                
                # Additional warning for composite keys
                if len(pk_columns) > 1:
                    result.add_info(
                        f"Column is part of composite PRIMARY KEY ({', '.join(pk_columns)})",
                        column=qualified_name
                    )
    
    def _validate_fk_columns(
        self,
        pii_col: PIIColumnConfig,
        schema_metadata: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """
        Validate foreign key column sanitization risks.
        
        Uses case-insensitive comparison for schema/table/column names.
        
        Args:
            pii_col: PII column configuration
            schema_metadata: Extracted schema metadata
            result: ValidationResult to accumulate issues
        """
        qualified_name = pii_col.fully_qualified_name
        
        # Check if column is a foreign key (child) - case-insensitive comparison
        fk_references = [
            fk for fk in schema_metadata["foreign_keys"]
            if (identifiers_match(fk["child_schema"], pii_col.schema) and
                identifiers_match(fk["child_table"], pii_col.table) and
                identifiers_match(fk["child_column"], pii_col.column))
        ]
        
        if fk_references:
            for fk in fk_references:
                parent_ref = f"[{fk['parent_schema']}].[{fk['parent_table']}].[{fk['parent_column']}]"
                
                if fk.get("is_self_referencing"):
                    result.add_warning(
                        f"Column is a self-referencing foreign key (hierarchical data)",
                        column=qualified_name,
                        code=ErrorCodes.FK_COLUMN_WARNING,
                        suggested_action="Ensure hierarchy is maintained during sanitization"
                    )
                else:
                    result.add_warning(
                        f"Column is a foreign key referencing {parent_ref}",
                        column=qualified_name,
                        code=ErrorCodes.FK_COLUMN_WARNING,
                        suggested_action=f"Ensure parent column is also sanitized or use consistent mapping"
                    )
        
        # Check if column is referenced by foreign keys (parent)
        fk_dependents = [
            fk for fk in schema_metadata["foreign_keys"]
            if (fk["parent_schema"] == pii_col.schema and
                fk["parent_table"] == pii_col.table and
                fk["parent_column"] == pii_col.column)
        ]
        
        if fk_dependents:
            dependent_tables = set(f"[{fk['child_schema']}].[{fk['child_table']}]" for fk in fk_dependents)
            result.add_warning(
                f"Column is referenced by foreign keys in {len(dependent_tables)} table(s): {', '.join(list(dependent_tables)[:3])}{'...' if len(dependent_tables) > 3 else ''}",
                column=qualified_name,
                code=ErrorCodes.FK_COLUMN_WARNING,
                suggested_action="Ensure dependent columns are also sanitized with consistent mapping"
            )
