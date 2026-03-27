"""Database connection configuration models.

This module provides type-safe configuration models for SQL Server connections
with support for both Windows and SQL Server authentication.
"""

from dataclasses import dataclass
from typing import Optional
from enum import Enum

from ..exceptions import ConfigValidationError


class AuthType(Enum):
    """Authentication type for SQL Server connection.
    
    Attributes:
        WINDOWS: Use Windows Integrated Authentication (Trusted Connection)
        SQL: Use SQL Server Authentication (username/password)
    """
    
    WINDOWS = "windows"
    SQL = "sql"


@dataclass
class ConnectionConfig:
    """Configuration for SQL Server connection.
    
    This class provides a type-safe way to manage database connection settings
    with automatic validation and secure connection string generation.
    
    Attributes:
        server: SQL Server hostname or IP address (e.g., 'localhost', '192.168.1.100')
        database: Database name to connect to
        auth_type: Authentication method (AuthType.WINDOWS or AuthType.SQL)
        username: Username for SQL authentication (required if auth_type=SQL)
        password: Password for SQL authentication (required if auth_type=SQL)
        port: SQL Server port (default: 1433)
        timeout: Connection timeout in seconds (default: 30)
        driver: ODBC driver name (default: 'ODBC Driver 17 for SQL Server')
        trust_server_certificate: Trust server certificate without validation (default: True)
        encrypt: Encrypt connection (default: True)
    
    Example:
        >>> # Windows Authentication
        >>> config = ConnectionConfig(
        ...     server="localhost",
        ...     database="TestDB",
        ...     auth_type=AuthType.WINDOWS
        ... )
        
        >>> # SQL Server Authentication
        >>> config = ConnectionConfig(
        ...     server="localhost",
        ...     database="TestDB",
        ...     auth_type=AuthType.SQL,
        ...     username="sa",
        ...     password="P@ssw0rd"
        ... )
    
    Security:
        - Passwords are never logged or exposed in __repr__
        - Connection strings use parameterized format
        - Supports TLS/SSL encryption
    """
    
    server: str
    database: str
    auth_type: AuthType
    username: Optional[str] = None
    password: Optional[str] = None
    port: int = 1433
    timeout: int = 30
    driver: str = "ODBC Driver 17 for SQL Server"
    trust_server_certificate: bool = True
    encrypt: bool = True
    
    def __post_init__(self):
        """Validate configuration after initialization.
        
        Raises:
            ValueError: If configuration is invalid (missing credentials, invalid port, etc.)
        """
        # Validate SQL authentication credentials
        if self.auth_type == AuthType.SQL:
            if not self.username or not self.password:
                raise ConfigValidationError.invalid_auth_credentials(
                    auth_type="sql",
                    has_username=bool(self.username),
                    has_password=bool(self.password)
                )
        
        # Validate timeout
        if self.timeout <= 0:
            raise ConfigValidationError.invalid_value(
                field="timeout",
                value=self.timeout,
                expected="positive integer"
            )
        
        # Validate port range
        if self.port <= 0 or self.port > 65535:
            raise ConfigValidationError.invalid_value(
                field="port",
                value=self.port,
                expected="1-65535"
            )
        
        # Validate server and database are not empty
        if not self.server or not self.server.strip():
            raise ConfigValidationError.missing_field("server")
        
        if not self.database or not self.database.strip():
            raise ConfigValidationError.missing_field("database")
    
    def get_connection_string(self) -> str:
        """Build ODBC connection string for pyodbc.
        
        Returns:
            Formatted connection string ready for pyodbc.connect()
        
        Security:
            - Password is included but never logged separately
            - Uses trusted connection for Windows auth (no credentials)
            - Supports encryption and certificate validation
        
        Example:
            >>> config = ConnectionConfig(server="localhost", database="TestDB", auth_type=AuthType.WINDOWS)
            >>> conn_str = config.get_connection_string()
            >>> # Returns: "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost,1433;..."
        """
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server},{self.port}",
            f"DATABASE={self.database}",
            f"Timeout={self.timeout}",
        ]
        
        # Add authentication-specific parameters
        if self.auth_type == AuthType.WINDOWS:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={self.username}")
            parts.append(f"PWD={self.password}")
        
        # Add encryption settings
        if self.encrypt:
            parts.append("Encrypt=yes")
        
        if self.trust_server_certificate:
            parts.append("TrustServerCertificate=yes")
        
        return ";".join(parts)
    
    def __repr__(self) -> str:
        """Safe string representation without credentials.
        
        Returns:
            String representation with sensitive data redacted
        
        Security:
            - Password is never included
            - Username is only shown for SQL auth (not sensitive)
        """
        auth_info = (
            f"auth_type={self.auth_type.value}"
            if self.auth_type == AuthType.WINDOWS
            else f"auth_type={self.auth_type.value}, username={self.username}"
        )
        
        return (
            f"ConnectionConfig("
            f"server={self.server}, "
            f"database={self.database}, "
            f"{auth_info}, "
            f"port={self.port})"
        )
