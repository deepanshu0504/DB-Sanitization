"""Configuration models for database sanitization framework.

This module provides Pydantic models for configuration management with
comprehensive validation, type safety, and clear error messages.

Models:
    Environment: Enum for deployment environments
    DatabaseConfig: Database connection and operation settings
    PIIColumnConfig: Individual PII column specification
    PIIConfig: Collection of PII column configurations
    SanitizationConfig: Root configuration combining all settings

Example:
    >>> config = SanitizationConfig(
    ...     database=DatabaseConfig(
    ...         server="localhost",
    ...         database="TestDB",
    ...         auth_type="windows",
    ...         batch_size=10000
    ...     ),
    ...     pii_columns=[
    ...         PIIColumnConfig(
    ...             schema="dbo",
    ...             table="Customers",
    ...             column="Email",
    ...             pii_type="email",
    ...             nullable=False
    ...         )
    ...     ]
    ... )
    >>> config.model_dump_json(indent=2)

Security:
    - Never logs passwords or sensitive connection strings
    - Safe __repr__ methods exclude credentials
    - Validates auth_type and credential combinations

Thread Safety:
    - Models are immutable after creation (Pydantic frozen models available)
    - Safe to share across threads
"""

import logging
import warnings
from enum import Enum
from typing import List, Literal, Optional, TYPE_CHECKING, Dict, Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ConfigDict,
)

from ..exceptions import ConfigValidationError

# Suppress Pydantic warning about 'schema' field shadowing BaseModel.schema()
# This is intentional as we need 'schema' for database schema names
warnings.filterwarnings('ignore', message=r'.*Field name "schema" shadows an attribute.*')

if TYPE_CHECKING:
    from src.logging.log_config import LogConfig
    from src.mapping.mapping_config import MappingConfig

logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Deployment environment enumeration.
    
    Attributes:
        DEV: Development environment
        STAGING: Staging/pre-production environment
        PROD: Production environment
    """
    
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class DatabaseConfig(BaseModel):
    """Database connection and operational configuration.
    
    This model extends the basic ConnectionConfig with additional settings
    for batch processing, retry logic, and performance tuning.
    
    Attributes:
        server: SQL Server hostname or IP address
        database: Database name to connect to
        auth_type: Authentication type ("windows" or "sql")
        username: SQL Server username (required if auth_type="sql")
        password: SQL Server password (required if auth_type="sql")
        timeout: Connection timeout in seconds (default: 30)
        batch_size: Number of rows to process per batch (default: 10000)
        max_retries: Maximum retry attempts for transient failures (default: 3)
        retry_delay: Initial retry delay in seconds (default: 1.0)
        pool_size: Connection pool size (default: 5)
        environment: Deployment environment (default: Environment.DEV)
    
    Raises:
        ValueError: If auth_type="sql" but username/password missing
        ValueError: If batch_size or timeout out of valid range
    
    Example:
        >>> config = DatabaseConfig(
        ...     server="localhost",
        ...     database="SanitizationTest",
        ...     auth_type="windows",
        ...     batch_size=5000,
        ...     timeout=60
        ... )
        >>> print(config.server)
        localhost
    
    Security:
        Password is excluded from string representation.
    """
    
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )
    
    server: str = Field(..., min_length=1, description="SQL Server hostname")
    database: str = Field(..., min_length=1, description="Database name")
    auth_type: Literal["windows", "sql"] = Field(
        ..., description="Authentication type"
    )
    username: Optional[str] = Field(
        None, min_length=1, description="SQL Server username"
    )
    password: Optional[str] = Field(
        None, min_length=1, description="SQL Server password"
    )
    timeout: int = Field(
        30, ge=5, le=300, description="Connection timeout in seconds"
    )
    batch_size: int = Field(
        10000, ge=100, le=1000000, description="Batch processing size"
    )
    max_retries: int = Field(
        3, ge=0, le=10, description="Maximum retry attempts"
    )
    retry_delay: float = Field(
        1.0, ge=0.1, le=60.0, description="Initial retry delay in seconds"
    )
    pool_size: int = Field(
        5, ge=1, le=20, description="Connection pool size"
    )
    environment: Environment = Field(
        Environment.DEV, description="Deployment environment"
    )
    
    @model_validator(mode="after")
    def validate_auth_credentials(self) -> "DatabaseConfig":
        """Validate that SQL auth has required credentials.
        
        Returns:
            Self with validated credentials
        
        Raises:
            ConfigValidationError: If auth_type="sql" but username/password missing
        """
        if self.auth_type == "sql":
            if not self.username:
                raise ConfigValidationError.missing_field(
                    "username",
                    auth_type="sql"
                )
            if not self.password:
                raise ConfigValidationError.missing_field(
                    "password",
                    auth_type="sql"
                )
        return self
    
    def __repr__(self) -> str:
        """Safe string representation excluding password.
        
        Returns:
            String representation with password masked
        """
        return (
            f"DatabaseConfig(server={self.server!r}, "
            f"database={self.database!r}, "
            f"auth_type={self.auth_type!r}, "
            f"username={self.username!r}, "
            f"password='***', "
            f"timeout={self.timeout}, "
            f"batch_size={self.batch_size}, "
            f"environment={self.environment!r})"
        )
    
    def get_connection_string(self) -> str:
        """Generate SQL Server connection string.
        
        Returns:
            ADO.NET connection string for SQL Server
        
        Example:
            >>> config = DatabaseConfig(server="localhost", database="TestDB", auth_type="windows")
            >>> conn_str = config.get_connection_string()
            >>> "Trusted_Connection=yes" in conn_str
            True
        """
        if self.auth_type == "windows":
            return (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.server};"
                f"DATABASE={self.database};"
                f"Trusted_Connection=yes;"
                f"Connection Timeout={self.timeout};"
                f"Login Timeout={self.timeout};"
            )
        else:  # SQL authentication
            return (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.server};"
                f"DATABASE={self.database};"
                f"UID={self.username};"
                f"PWD={self.password};"
                f"Connection Timeout={self.timeout};"
                f"Login Timeout={self.timeout};"
            )


class PIIColumnConfig(BaseModel):
    """Configuration for a single PII column.
    
    Specifies which column contains PII data and how it should be masked.
    
    Attributes:
        schema: Database schema name (e.g., "dbo")
        table: Table name containing the PII column
        column: Column name containing PII data
        pii_type: Type of PII data (email, phone, name, ssn, generic)
        nullable: Whether the column allows NULL values
        custom_format: Optional masker-specific parameters (e.g., {"character_class": "alpha"})
    
    Raises:
        ValueError: If pii_type not in allowed values
        ValueError: If schema, table, or column names are empty
    
    Example:
        >>> pii_col = PIIColumnConfig(
        ...     schema="dbo",
        ...     table="Customers",
        ...     column="Email",
        ...     pii_type="email",
        ...     nullable=False
        ... )
        >>> print(pii_col.fully_qualified_name)
        [dbo].[Customers].[Email]
    """
    
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
        protected_namespaces=(),
    )
    
    schema: str = Field(..., min_length=1, description="Database schema name")
    table: str = Field(..., min_length=1, description="Table name")
    column: str = Field(..., min_length=1, description="Column name")
    pii_type: Literal["email", "phone", "name", "ssn", "generic"] = Field(
        ..., description="Type of PII data"
    )
    nullable: bool = Field(
        ..., description="Whether column allows NULL values"
    )
    custom_format: Optional[Dict[str, Any]] = Field(
        None, description="Masker-specific parameters (e.g., character_class for GenericMasker)"
    )
    
    @property
    def fully_qualified_name(self) -> str:
        """Get fully qualified column name with SQL Server escaping.
        
        Returns:
            Fully qualified name in format [schema].[table].[column]
        
        Example:
            >>> config.fully_qualified_name
            '[dbo].[Customers].[Email]'
        """
        return f"[{self.schema}].[{self.table}].[{self.column}]"
    
    @property
    def table_qualified_name(self) -> str:
        """Get table qualified name with SQL Server escaping.
        
        Returns:
            Table qualified name in format [schema].[table]
        
        Example:
            >>> config.table_qualified_name
            '[dbo].[Customers]'
        """
        return f"[{self.schema}].[{self.table}]"


class PIIConfig(BaseModel):
    """Collection of PII column configurations.
    
    Container for all PII columns that need sanitization.
    
    Attributes:
        columns: List of PIIColumnConfig objects
        version: Configuration version for tracking changes (default: "1.0")
        description: Optional description of this configuration
    
    Example:
        >>> pii_config = PIIConfig(
        ...     columns=[
        ...         PIIColumnConfig(
        ...             schema="dbo",
        ...             table="Customers",
        ...             column="Email",
        ...             pii_type="email",
        ...             nullable=False
        ...         )
        ...     ],
        ...     version="1.0",
        ...     description="Production PII sanitization config"
        ... )
        >>> len(pii_config.columns)
        1
    """
    
    model_config = ConfigDict(
        validate_assignment=True,
    )
    
    columns: List[PIIColumnConfig] = Field(
        default_factory=list,
        description="List of PII column configurations"
    )
    version: str = Field(
        "1.0",
        description="Configuration version"
    )
    description: Optional[str] = Field(
        None,
        description="Configuration description"
    )
    
    @field_validator("columns")
    @classmethod
    def validate_unique_columns(
        cls, columns: List[PIIColumnConfig]
    ) -> List[PIIColumnConfig]:
        """Validate that column combinations are unique.
        
        Args:
            columns: List of PII column configurations
        
        Returns:
            Validated list of columns
        
        Raises:
            ValueError: If duplicate schema.table.column combinations found
        """
        seen = set()
        duplicates = []
        
        for col in columns:
            key = (col.schema, col.table, col.column)
            if key in seen:
                duplicates.append(col.fully_qualified_name)
            seen.add(key)
        
        if duplicates:
            raise ValueError(
                f"Duplicate PII column configurations found: {duplicates}"
            )
        
        return columns
    
    def get_columns_for_table(
        self, schema: str, table: str
    ) -> List[PIIColumnConfig]:
        """Get all PII columns for a specific table.
        
        Args:
            schema: Database schema name
            table: Table name
        
        Returns:
            List of PIIColumnConfig for the specified table
        
        Example:
            >>> columns = pii_config.get_columns_for_table("dbo", "Customers")
            >>> [col.column for col in columns]
            ['Email', 'Phone']
        """
        return [
            col for col in self.columns
            if col.schema == schema and col.table == table
        ]
    
    def get_unique_tables(self) -> List[tuple[str, str]]:
        """Get unique (schema, table) combinations.
        
        Returns:
            List of (schema, table) tuples
        
        Example:
            >>> pii_config.get_unique_tables()
            [('dbo', 'Customers'), ('dbo', 'Employees')]
        """
        tables = set()
        for col in self.columns:
            tables.add((col.schema, col.table))
        return sorted(tables)


class AIConfig(BaseModel):
    """Configuration for AI service integration (GitHub Copilot API).
    
    This model defines settings for automated PII detection using AI models,
    including API endpoint, authentication, timeout, retry logic, and caching.
    
    Attributes:
        enabled: Whether AI service is enabled (default: True)
        api_url: GitHub Copilot API endpoint URL
        api_key_env_var: Environment variable name containing API key
        timeout_seconds: Request timeout in seconds (default: 30)
        max_retries: Maximum retry attempts for failed requests (default: 3)
        retry_backoff_factor: Exponential backoff multiplier (default: 1.0)
        cache_enabled: Whether to cache API responses (default: True)
        cache_ttl_hours: Cache time-to-live in hours (default: 24)
        max_tables_per_request: Maximum tables to send in one request (default: 50)
        max_schema_size_chars: Maximum schema size in characters (default: 50000)
    
    Raises:
        ValueError: If timeout or retry settings out of valid range
    
    Example:
        >>> ai_config = AIConfig(
        ...     api_url="https://api.github.com/copilot/model",
        ...     timeout_seconds=60,
        ...     cache_ttl_hours=12
        ... )
        >>> print(ai_config.enabled)
        True
    
    Security:
        API key is stored in environment variable, not in configuration file.
    """
    
    model_config = ConfigDict(
        validate_assignment=True,
        str_strip_whitespace=True,
    )
    
    enabled: bool = Field(
        True,
        description="Whether AI service is enabled"
    )
    api_url: str = Field(
        "https://api.github.com/copilot/model",
        min_length=1,
        description="GitHub Copilot API endpoint URL"
    )
    api_key_env_var: str = Field(
        "GITHUB_COPILOT_API_KEY",
        min_length=1,
        description="Environment variable name containing API key"
    )
    timeout_seconds: int = Field(
        30,
        ge=5,
        le=300,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed requests"
    )
    retry_backoff_factor: float = Field(
        1.0,
        ge=0.1,
        le=10.0,
        description="Exponential backoff multiplier for retries"
    )
    cache_enabled: bool = Field(
        True,
        description="Whether to cache API responses"
    )
    cache_ttl_hours: int = Field(
        24,
        ge=1,
        le=168,  # Max 1 week
        description="Cache time-to-live in hours"
    )
    max_tables_per_request: int = Field(
        50,
        ge=1,
        le=500,
        description="Maximum tables to send in one API request"
    )
    max_schema_size_chars: int = Field(
        50000,
        ge=1000,
        le=500000,
        description="Maximum schema size in characters"
    )
    
    def __repr__(self) -> str:
        """String representation excluding API key reference for security."""
        return (
            f"AIConfig(enabled={self.enabled}, api_url={self.api_url!r}, "
            f"timeout={self.timeout_seconds}s, cache_enabled={self.cache_enabled})"
        )


class SanitizationConfig(BaseModel):
    """Root configuration for database sanitization.
    
    Combines database configuration with PII column specifications
    to provide complete sanitization settings.
    
    Attributes:
        database: Database connection and operational configuration
        pii_columns: List of PII column configurations
        dry_run: Whether to run in dry-run mode (default: False)
        validate_before: Whether to validate data before sanitization (default: True)
        validate_after: Whether to validate data after sanitization (default: True)
    
    Example:
        >>> config = SanitizationConfig(
        ...     database=DatabaseConfig(
        ...         server="localhost",
        ...         database="TestDB",
        ...         auth_type="windows"
        ...     ),
        ...     pii_columns=[
        ...         PIIColumnConfig(
        ...             schema="dbo",
        ...             table="Users",
        ...             column="Email",
        ...             pii_type="email",
        ...             nullable=False
        ...         )
        ...     ],
        ...     dry_run=False
        ... )
        >>> config.database.server
        'localhost'
    
    Thread Safety:
        Safe to share across threads after creation.
    """
    
    model_config = ConfigDict(
        validate_assignment=True,
    )
    
    database: DatabaseConfig = Field(
        ..., description="Database configuration"
    )
    pii_columns: List[PIIColumnConfig] = Field(
        default_factory=list,
        description="PII column configurations"
    )
    logging: Optional["LogConfig"] = Field(
        None,
        description="Logging configuration (optional, uses defaults if not specified)"
    )
    ai: Optional[AIConfig] = Field(
        None,
        description="AI service configuration (optional, uses defaults if not specified)"
    )
    mapping: Optional["MappingConfig"] = Field(
        None,
        description="Mapping table configuration (optional, uses defaults if not specified)"
    )
    dry_run: bool = Field(
        False,
        description="Run in dry-run mode (no actual updates)"
    )
    validate_before: bool = Field(
        True,
        description="Validate data integrity before sanitization"
    )
    validate_after: bool = Field(
        True,
        description="Validate data integrity after sanitization"
    )
    
    @field_validator("pii_columns")
    @classmethod
    def validate_unique_pii_columns(
        cls, columns: List[PIIColumnConfig]
    ) -> List[PIIColumnConfig]:
        """Validate PII columns are unique.
        
        Args:
            columns: List of PII column configurations
        
        Returns:
            Validated list of columns
        
        Raises:
            ValueError: If duplicate columns found
        """
        seen = set()
        duplicates = []
        
        for col in columns:
            key = (col.schema, col.table, col.column)
            if key in seen:
                duplicates.append(col.fully_qualified_name)
            seen.add(key)
        
        if duplicates:
            raise ValueError(
                f"Duplicate PII columns in configuration: {duplicates}"
            )
        
        return columns
    
    def get_pii_config(self) -> PIIConfig:
        """Get PIIConfig object from pii_columns.
        
        Returns:
            PIIConfig containing all PII column configurations
        
        Example:
            >>> pii_config = config.get_pii_config()
            >>> len(pii_config.columns)
            5
        """
        return PIIConfig(columns=self.pii_columns)


# Rebuild models to resolve forward references
# This is needed because LogConfig and MappingConfig are imported under TYPE_CHECKING
try:
    from src.logging.log_config import LogConfig
    from src.mapping.mapping_config import MappingConfig
    SanitizationConfig.model_rebuild()
except ImportError:
    # Models might not be available yet during initial imports
    pass
