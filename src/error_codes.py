"""
Centralized error code constants for database sanitization framework.

This module defines all error codes used throughout the application for consistent
error identification, logging, and handling. Error codes are organized by domain
for better maintainability.

Author: Database Sanitization Team
Date: 2026-03-26
"""

from typing import Final


class ErrorCodes:
    """Centralized error code constants grouped by domain."""

    # ==================== Configuration Errors ====================
    
    # File-related errors
    FILE_NOT_FOUND: Final[str] = "FILE_NOT_FOUND"
    FILE_NOT_READABLE: Final[str] = "FILE_NOT_READABLE"
    INVALID_JSON: Final[str] = "INVALID_JSON"
    
    # Validation errors
    INVALID_VALUE: Final[str] = "INVALID_VALUE"
    MISSING_FIELD: Final[str] = "MISSING_FIELD"
    TYPE_MISMATCH: Final[str] = "TYPE_MISMATCH"
    INVALID_AUTH_CREDENTIALS: Final[str] = "INVALID_AUTH_CREDENTIALS"
    
    # Override errors
    ENV_VAR_INVALID: Final[str] = "ENV_VAR_INVALID"
    OVERRIDE_CONFLICT: Final[str] = "OVERRIDE_CONFLICT"

    # ==================== Database Errors ====================
    
    # Connection errors
    CONN_FAILED: Final[str] = "CONN_FAILED"
    CONN_TIMEOUT: Final[str] = "CONN_TIMEOUT"
    AUTH_FAILED: Final[str] = "AUTH_FAILED"
    SERVER_UNREACHABLE: Final[str] = "SERVER_UNREACHABLE"
    
    # Query errors
    QUERY_FAILED: Final[str] = "QUERY_FAILED"
    INVALID_SYNTAX: Final[str] = "INVALID_SYNTAX"
    PERMISSION_DENIED: Final[str] = "PERMISSION_DENIED"
    
    # Connection pool errors
    POOL_EXHAUSTED: Final[str] = "POOL_EXHAUSTED"
    POOL_INVALID_STATE: Final[str] = "POOL_INVALID_STATE"
    
    # Health check errors
    CONN_DEAD: Final[str] = "CONN_DEAD"
    CONN_UNRESPONSIVE: Final[str] = "CONN_UNRESPONSIVE"
    
    # Schema extraction errors
    DB_NOT_FOUND: Final[str] = "DB_NOT_FOUND"
    NO_TABLES_FOUND: Final[str] = "NO_TABLES_FOUND"
    SCHEMA_EXTRACTION_FAILED: Final[str] = "SCHEMA_EXTRACTION_FAILED"
    INVALID_METADATA: Final[str] = "INVALID_METADATA"
    
    # Data extraction errors
    DATA_EXTRACTION_FAILED: Final[str] = "DATA_EXTRACTION_FAILED"
    TABLE_NOT_FOUND: Final[str] = "TABLE_NOT_FOUND"
    COLUMN_NOT_FOUND: Final[str] = "COLUMN_NOT_FOUND"
    
    # Data update errors
    DATA_UPDATE_FAILED: Final[str] = "DATA_UPDATE_FAILED"
    UPDATE_BATCH_FAILED: Final[str] = "UPDATE_BATCH_FAILED"
    INVALID_UPDATE_DATA: Final[str] = "INVALID_UPDATE_DATA"
    DEADLOCK_DETECTED: Final[str] = "DEADLOCK_DETECTED"
    DEADLOCK_RETRY_EXHAUSTED: Final[str] = "DEADLOCK_RETRY_EXHAUSTED"
    
    # Transaction errors
    TRANSACTION_BEGIN_FAILED: Final[str] = "TRANSACTION_BEGIN_FAILED"
    TRANSACTION_COMMIT_FAILED: Final[str] = "TRANSACTION_COMMIT_FAILED"
    TRANSACTION_ROLLBACK_FAILED: Final[str] = "TRANSACTION_ROLLBACK_FAILED"
    NESTED_TRANSACTION_ERROR: Final[str] = "NESTED_TRANSACTION_ERROR"
    TRANSACTION_TIMEOUT: Final[str] = "TRANSACTION_TIMEOUT"
    
    # Savepoint errors
    SAVEPOINT_NOT_FOUND: Final[str] = "SAVEPOINT_NOT_FOUND"
    SAVEPOINT_CREATE_FAILED: Final[str] = "SAVEPOINT_CREATE_FAILED"
    SAVEPOINT_ROLLBACK_FAILED: Final[str] = "SAVEPOINT_ROLLBACK_FAILED"
    MAX_NESTING_EXCEEDED: Final[str] = "MAX_NESTING_EXCEEDED"
    INVALID_SAVEPOINT_NAME: Final[str] = "INVALID_SAVEPOINT_NAME"
    
    # Isolation level errors
    INVALID_ISOLATION_LEVEL: Final[str] = "INVALID_ISOLATION_LEVEL"
    ISOLATION_LEVEL_NOT_SUPPORTED: Final[str] = "ISOLATION_LEVEL_NOT_SUPPORTED"
    
    # Dependency resolution errors
    CIRCULAR_DEPENDENCY: Final[str] = "CIRCULAR_DEPENDENCY"
    INVALID_DEPENDENCY_GRAPH: Final[str] = "INVALID_DEPENDENCY_GRAPH"
    TOPOLOGICAL_SORT_FAILED: Final[str] = "TOPOLOGICAL_SORT_FAILED"

    # ==================== AI Service Errors ====================
    
    # API request errors
    AI_API_REQUEST_FAILED: Final[str] = "AI_API_REQUEST_FAILED"
    AI_API_TIMEOUT: Final[str] = "AI_API_TIMEOUT"
    AI_API_QUOTA_EXCEEDED: Final[str] = "AI_API_QUOTA_EXCEEDED"
    AI_AUTH_FAILED: Final[str] = "AI_AUTH_FAILED"
    AI_NETWORK_ERROR: Final[str] = "AI_NETWORK_ERROR"
    
    # Response validation errors
    AI_INVALID_RESPONSE: Final[str] = "AI_INVALID_RESPONSE"
    AI_RESPONSE_PARSING_FAILED: Final[str] = "AI_RESPONSE_PARSING_FAILED"
    AI_SCHEMA_TOO_LARGE: Final[str] = "AI_SCHEMA_TOO_LARGE"

    # ==================== Validation Errors ====================
    
    # Schema validation errors
    SCHEMA_NOT_FOUND: Final[str] = "SCHEMA_NOT_FOUND"
    TABLE_NOT_FOUND_IN_SCHEMA: Final[str] = "TABLE_NOT_FOUND_IN_SCHEMA"
    COLUMN_NOT_FOUND_IN_TABLE: Final[str] = "COLUMN_NOT_FOUND_IN_TABLE"
    
    # Data type validation errors
    INCOMPATIBLE_DATA_TYPE: Final[str] = "INCOMPATIBLE_DATA_TYPE"
    INSUFFICIENT_COLUMN_LENGTH: Final[str] = "INSUFFICIENT_COLUMN_LENGTH"
    UNSUPPORTED_DATA_TYPE: Final[str] = "UNSUPPORTED_DATA_TYPE"
    
    # Constraint validation errors
    NULLABLE_MISMATCH: Final[str] = "NULLABLE_MISMATCH"
    PK_COLUMN_WARNING: Final[str] = "PK_COLUMN_WARNING"
    FK_COLUMN_WARNING: Final[str] = "FK_COLUMN_WARNING"
    UNIQUE_CONSTRAINT_WARNING: Final[str] = "UNIQUE_CONSTRAINT_WARNING"
    
    # Special column warnings
    IDENTITY_COLUMN_ERROR: Final[str] = "IDENTITY_COLUMN_ERROR"
    COMPUTED_COLUMN_WARNING: Final[str] = "COMPUTED_COLUMN_WARNING"
    SYSTEM_TABLE_WARNING: Final[str] = "SYSTEM_TABLE_WARNING"
    VIEW_SANITIZATION_WARNING: Final[str] = "VIEW_SANITIZATION_WARNING"
    TEMP_TABLE_ERROR: Final[str] = "TEMP_TABLE_ERROR"

    # ==================== Masking Errors ====================
    
    # Masking execution errors
    MASKING_FAILED: Final[str] = "MASKING_FAILED"
    MASKING_TYPE_MISMATCH: Final[str] = "MASKING_TYPE_MISMATCH"
    MASKING_LENGTH_EXCEEDED: Final[str] = "MASKING_LENGTH_EXCEEDED"
    MASKING_NULL_CONSTRAINT_VIOLATION: Final[str] = "MASKING_NULL_CONSTRAINT_VIOLATION"
    MASKING_STRATEGY_NOT_IMPLEMENTED: Final[str] = "MASKING_STRATEGY_NOT_IMPLEMENTED"
    MASKING_INVALID_FORMAT: Final[str] = "MASKING_INVALID_FORMAT"
    MASKING_COLLISION_DETECTED: Final[str] = "MASKING_COLLISION_DETECTED"
    
    # Masker configuration errors
    INVALID_MASKING_STRATEGY: Final[str] = "INVALID_MASKING_STRATEGY"
    UNSUPPORTED_PII_TYPE: Final[str] = "UNSUPPORTED_PII_TYPE"
    MASKER_NOT_FOUND: Final[str] = "MASKER_NOT_FOUND"

    # ==================== Mapping Errors ====================
    
    # Mapping storage errors
    MAPPING_STORAGE_FAILED: Final[str] = "MAPPING_STORAGE_FAILED"
    MAPPING_SCHEMA_CREATION_FAILED: Final[str] = "MAPPING_SCHEMA_CREATION_FAILED"
    MAPPING_TABLE_CREATION_FAILED: Final[str] = "MAPPING_TABLE_CREATION_FAILED"
    MAPPING_INDEX_CREATION_FAILED: Final[str] = "MAPPING_INDEX_CREATION_FAILED"
    MAPPING_DUPLICATE_ENTRY: Final[str] = "MAPPING_DUPLICATE_ENTRY"
    
    # Mapping retrieval errors
    MAPPING_NOT_FOUND: Final[str] = "MAPPING_NOT_FOUND"
    MAPPING_LOOKUP_FAILED: Final[str] = "MAPPING_LOOKUP_FAILED"
    MAPPING_TABLE_NOT_FOUND: Final[str] = "MAPPING_TABLE_NOT_FOUND"
    
    # Mapping encryption errors
    MAPPING_ENCRYPTION_FAILED: Final[str] = "MAPPING_ENCRYPTION_FAILED"
    MAPPING_DECRYPTION_FAILED: Final[str] = "MAPPING_DECRYPTION_FAILED"
    MAPPING_ENCRYPTION_KEY_MISSING: Final[str] = "MAPPING_ENCRYPTION_KEY_MISSING"

    # ==================== Desensitization Errors ====================
    
    # Desensitization operation errors
    DESENSITIZATION_MAPPING_NOT_FOUND: Final[str] = "DESENSITIZATION_MAPPING_NOT_FOUND"
    DESENSITIZATION_DECRYPTION_FAILED: Final[str] = "DESENSITIZATION_DECRYPTION_FAILED"
    DESENSITIZATION_VALUE_MISMATCH: Final[str] = "DESENSITIZATION_VALUE_MISMATCH"
    DESENSITIZATION_RESTORE_FAILED: Final[str] = "DESENSITIZATION_RESTORE_FAILED"
    DESENSITIZATION_VALIDATION_FAILED: Final[str] = "DESENSITIZATION_VALIDATION_FAILED"
    DESENSITIZATION_INCOMPLETE_MAPPINGS: Final[str] = "DESENSITIZATION_INCOMPLETE_MAPPINGS"
    DESENSITIZATION_OPERATION_NOT_FOUND: Final[str] = "DESENSITIZATION_OPERATION_NOT_FOUND"

    # ==================== Logging Errors ====================
    
    # Logger configuration errors
    INVALID_HANDLER: Final[str] = "INVALID_HANDLER"
    INVALID_FORMATTER: Final[str] = "INVALID_FORMATTER"
    INVALID_LOG_LEVEL: Final[str] = "INVALID_LOG_LEVEL"

    @classmethod
    def is_valid_code(cls, code: str) -> bool:
        """
        Check if a given string is a valid error code.
        
        Args:
            code: The error code string to validate
            
        Returns:
            True if the code is valid, False otherwise
        """
        return code in cls.get_all_codes()
    
    @classmethod
    def get_all_codes(cls) -> set[str]:
        """
        Get all defined error codes.
        
        Returns:
            Set of all error code strings
        """
        return {
            value for name, value in vars(cls).items()
            if isinstance(value, str) and not name.startswith('_')
        }
    
    @classmethod
    def get_config_codes(cls) -> set[str]:
        """Get all configuration-related error codes."""
        return {
            cls.FILE_NOT_FOUND, cls.FILE_NOT_READABLE, cls.INVALID_JSON,
            cls.INVALID_VALUE, cls.MISSING_FIELD, cls.TYPE_MISMATCH,
            cls.INVALID_AUTH_CREDENTIALS, cls.ENV_VAR_INVALID, cls.OVERRIDE_CONFLICT
        }
    
    @classmethod
    def get_database_codes(cls) -> set[str]:
        """Get all database-related error codes."""
        return {
            cls.CONN_FAILED, cls.CONN_TIMEOUT, cls.AUTH_FAILED, cls.SERVER_UNREACHABLE,
            cls.QUERY_FAILED, cls.INVALID_SYNTAX, cls.PERMISSION_DENIED,
            cls.POOL_EXHAUSTED, cls.POOL_INVALID_STATE,
            cls.CONN_DEAD, cls.CONN_UNRESPONSIVE,
            cls.DB_NOT_FOUND, cls.NO_TABLES_FOUND, cls.SCHEMA_EXTRACTION_FAILED, cls.INVALID_METADATA,
            cls.DATA_EXTRACTION_FAILED, cls.TABLE_NOT_FOUND, cls.COLUMN_NOT_FOUND,
            cls.DATA_UPDATE_FAILED, cls.UPDATE_BATCH_FAILED, cls.INVALID_UPDATE_DATA,
            cls.DEADLOCK_DETECTED, cls.DEADLOCK_RETRY_EXHAUSTED,
            cls.TRANSACTION_BEGIN_FAILED, cls.TRANSACTION_COMMIT_FAILED, cls.TRANSACTION_ROLLBACK_FAILED,
            cls.NESTED_TRANSACTION_ERROR, cls.TRANSACTION_TIMEOUT,
            cls.SAVEPOINT_NOT_FOUND, cls.SAVEPOINT_CREATE_FAILED, cls.SAVEPOINT_ROLLBACK_FAILED,
            cls.MAX_NESTING_EXCEEDED, cls.INVALID_SAVEPOINT_NAME,
            cls.INVALID_ISOLATION_LEVEL, cls.ISOLATION_LEVEL_NOT_SUPPORTED,
            cls.CIRCULAR_DEPENDENCY, cls.INVALID_DEPENDENCY_GRAPH, cls.TOPOLOGICAL_SORT_FAILED
        }
    
    @classmethod
    def get_ai_codes(cls) -> set[str]:
        """Get all AI service-related error codes."""
        return {
            cls.AI_API_REQUEST_FAILED, cls.AI_API_TIMEOUT, cls.AI_API_QUOTA_EXCEEDED,
            cls.AI_AUTH_FAILED, cls.AI_NETWORK_ERROR,
            cls.AI_INVALID_RESPONSE, cls.AI_RESPONSE_PARSING_FAILED, cls.AI_SCHEMA_TOO_LARGE
        }
    
    @classmethod
    def get_logging_codes(cls) -> set[str]:
        """Get all logging-related error codes."""
        return {
            cls.INVALID_HANDLER, cls.INVALID_FORMATTER, cls.INVALID_LOG_LEVEL
        }
