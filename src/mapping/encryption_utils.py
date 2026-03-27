"""
Encryption utilities for mapping table value encryption.

This module provides encryption and decryption functionality for original PII values
stored in the mapping table. It uses Fernet symmetric encryption (AES-128-CBC + HMAC)
from the cryptography library.

Key Management:
- Keys are loaded from environment variable: SANITIZATION_MAPPING_ENCRYPTION_KEY
- Keys must be valid Fernet keys (44 characters, base64-encoded)
- Generate new keys using: EncryptionManager.generate_key()

Security Considerations:
- Keys should be rotated periodically (requires re-encryption of existing mappings)
- In production, use Azure Key Vault or HashiCorp Vault for key storage
- Never log encryption keys or unencrypted sensitive values
"""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from src.exceptions import MappingError
from src.logging.logger import get_logger


class EncryptionManager:
    """
    Manages encryption and decryption of mapping table values.
    
    Uses Fernet symmetric encryption (AES-128-CBC + HMAC) for secure,
    authenticated encryption of sensitive data.
    
    Attributes:
        fernet: Fernet instance for encryption/decryption operations
        logger: Logger instance for operation tracking
        
    Example:
        ```python
        # Set encryption key in environment
        os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = EncryptionManager.generate_key()
        
        # Initialize manager
        manager = EncryptionManager()
        
        # Encrypt a value
        encrypted = manager.encrypt("john.doe@example.com")
        
        # Decrypt the value
        original = manager.decrypt(encrypted)
        assert original == "john.doe@example.com"
        ```
    
    Edge Cases:
        - None values: Returns None without encryption/decryption
        - Empty strings: Encrypted as empty strings
        - Invalid keys: Raises MappingError.encryption_key_missing()
        - Decryption failures: Raises MappingError.decryption_failed()
    """
    
    ENV_VAR_NAME = "SANITIZATION_MAPPING_ENCRYPTION_KEY"
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize the encryption manager.
        
        Args:
            encryption_key: Optional Fernet key (base64-encoded string).
                          If not provided, loads from environment variable.
                          
        Raises:
            MappingError: If encryption key is missing or invalid
        """
        self.logger = get_logger(self.__class__.__name__)
        
        try:
            # Load key from parameter or environment
            key_bytes = self._load_key(encryption_key)
            
            # Initialize Fernet with the key
            self.fernet = Fernet(key_bytes)
            
            self.logger.info(
                "EncryptionManager initialized successfully",
                extra={"key_source": "parameter" if encryption_key else "environment"}
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to initialize EncryptionManager",
                extra={"error": str(e)},
                exc_info=True
            )
            raise
    
    def _load_key(self, key_str: Optional[str] = None) -> bytes:
        """
        Load encryption key from parameter or environment variable.
        
        Args:
            key_str: Optional key string (base64-encoded)
            
        Returns:
            Key bytes for Fernet initialization
            
        Raises:
            MappingError: If key is missing or invalid
        """
        # Use provided key or load from environment
        key_source = key_str or os.environ.get(self.ENV_VAR_NAME)
        
        if not key_source:
            raise MappingError.encryption_key_missing()
        
        try:
            # Validate and convert to bytes
            if isinstance(key_source, str):
                key_bytes = key_source.encode('utf-8')
            else:
                key_bytes = key_source
            
            # Validate key format by attempting to create Fernet instance
            Fernet(key_bytes)
            
            return key_bytes
            
        except Exception as e:
            raise MappingError.encryption_failed(
                reason=f"Invalid encryption key format: {str(e)}"
            )
    
    def encrypt(self, value: Optional[str]) -> Optional[bytes]:
        """
        Encrypt a string value.
        
        Args:
            value: String value to encrypt (can be None)
            
        Returns:
            Encrypted bytes, or None if input was None
            
        Raises:
            MappingError: If encryption fails
            
        Example:
            ```python
            manager = EncryptionManager()
            encrypted = manager.encrypt("sensitive_data")
            # Returns: b'gAAAA...' (encrypted bytes)
            ```
        """
        # Handle NULL values
        if value is None:
            return None
        
        try:
            # Convert string to bytes, encrypt, and return
            value_bytes = value.encode('utf-8')
            encrypted_bytes = self.fernet.encrypt(value_bytes)
            
            self.logger.debug(
                "Value encrypted successfully",
                extra={
                    "original_length": len(value),
                    "encrypted_length": len(encrypted_bytes)
                }
            )
            
            return encrypted_bytes
            
        except Exception as e:
            self.logger.error(
                "Encryption failed",
                extra={
                    "error": str(e),
                    "value_length": len(value) if value else 0
                },
                exc_info=True
            )
            raise MappingError.encryption_failed(
                reason=str(e)
            )
    
    def decrypt(self, encrypted_value: Optional[bytes]) -> Optional[str]:
        """
        Decrypt an encrypted value.
        
        Args:
            encrypted_value: Encrypted bytes (can be None)
            
        Returns:
            Decrypted string, or None if input was None
            
        Raises:
            MappingError: If decryption fails (wrong key, corrupted data)
            
        Example:
            ```python
            manager = EncryptionManager()
            encrypted = b'gAAAA...'
            original = manager.decrypt(encrypted)
            # Returns: "sensitive_data"
            ```
        """
        # Handle NULL values
        if encrypted_value is None:
            return None
        
        try:
            # Decrypt and convert bytes to string
            decrypted_bytes = self.fernet.decrypt(encrypted_value)
            original_value = decrypted_bytes.decode('utf-8')
            
            self.logger.debug(
                "Value decrypted successfully",
                extra={
                    "encrypted_length": len(encrypted_value),
                    "decrypted_length": len(original_value)
                }
            )
            
            return original_value
            
        except InvalidToken:
            # This typically means wrong key or corrupted data
            self.logger.error(
                "Decryption failed: Invalid token (wrong key or corrupted data)",
                extra={"encrypted_length": len(encrypted_value)}
            )
            raise MappingError.decryption_failed(
                reason="Invalid token - check encryption key matches the key used for encryption"
            )
        except Exception as e:
            self.logger.error(
                "Decryption failed",
                extra={
                    "error": str(e),
                    "encrypted_length": len(encrypted_value) if encrypted_value else 0
                },
                exc_info=True
            )
            raise MappingError.decryption_failed(
                reason=str(e)
            )
    
    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key.
        
        Returns:
            Base64-encoded Fernet key (44 characters)
            
        Example:
            ```python
            key = EncryptionManager.generate_key()
            print(key)  # 'X1LYFQEkMLZBGrfQhFZ-1234567890abcdefghij=='
            
            # Set as environment variable
            os.environ['SANITIZATION_MAPPING_ENCRYPTION_KEY'] = key
            ```
            
        Note:
            Store generated keys securely. Loss of key = loss of ability to decrypt.
        """
        key_bytes = Fernet.generate_key()
        return key_bytes.decode('utf-8')
    
    @staticmethod
    def is_key_valid(key: str) -> bool:
        """
        Check if a key string is a valid Fernet key.
        
        Args:
            key: Key string to validate
            
        Returns:
            True if valid Fernet key, False otherwise
            
        Example:
            ```python
            key = "invalid_key_123"
            assert not EncryptionManager.is_key_valid(key)
            
            valid_key = EncryptionManager.generate_key()
            assert EncryptionManager.is_key_valid(valid_key)
            ```
        """
        try:
            key_bytes = key.encode('utf-8')
            Fernet(key_bytes)
            return True
        except Exception:
            return False
