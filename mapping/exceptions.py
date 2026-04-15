"""Custom exceptions for mapping infrastructure."""


class MappingTableError(Exception):
    """Base exception for mapping table operations."""
    pass


class MappingInsertError(MappingTableError):
    """Raised when batch insert fails."""
    
    def __init__(self, message: str, failed_count: int = 0, total_count: int = 0):
        super().__init__(message)
        self.failed_count = failed_count
        self.total_count = total_count


class SchemaValidationError(MappingTableError):
    """Raised when mapping table schema is invalid."""
    
    def __init__(self, message: str, missing_columns: list = None):
        super().__init__(message)
        self.missing_columns = missing_columns or []


# ============================================================================
# Encryption Exceptions (Story 1.3)
# ============================================================================

class EncryptionError(MappingTableError):
    """Base exception for encryption-related failures."""
    
    def __init__(self, message: str, suggested_action: str = None):
        super().__init__(message)
        self.suggested_action = suggested_action
    
    def __str__(self):
        msg = super().__str__()
        if self.suggested_action:
            msg += f"\n\nSuggested action: {self.suggested_action}"
        return msg


class KeyManagementError(EncryptionError):
    """Raised when encryption key is missing, invalid, or corrupted."""
    
    def __init__(self, message: str, suggested_action: str = None):
        super().__init__(message, suggested_action)


class DecryptionError(EncryptionError):
    """Raised when decryption fails (wrong key, corrupted data, tampering)."""
    
    def __init__(self, message: str, suggested_action: str = None):
        super().__init__(message, suggested_action)
