"""
Encryption utilities for securing PII mappings.

This module provides AES-256-GCM encryption/decryption capabilities using the
Fernet symmetric encryption scheme from the cryptography library.

Key Features:
    - AES-256-GCM encryption via Fernet
    - Key derivation from environment variable
    - Transparent encryption/decryption
    - Comprehensive error handling
    - Thread-safe operations

Security Notes:
    - Encryption key must be 32 bytes (Fernet requirement)
    - Keys should be stored securely in environment variables
    - Never log or expose encryption keys
    - Rotate keys periodically in production

Usage:
    from mapping.encryption_utils import EncryptionManager
    
    # Initialize with key from environment
    encryptor = EncryptionManager()
    
    # Encrypt sensitive data
    encrypted = encryptor.encrypt("sensitive@email.com")
    
    # Decrypt when needed
    original = encryptor.decrypt(encrypted)

Author: Database Sanitization Team
Date: 2026-04-16
"""

import os
import base64
from typing import Optional, Union
from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Base exception for encryption-related errors."""
    pass


class EncryptionKeyError(EncryptionError):
    """Raised when encryption key is missing or invalid."""
    pass


class DecryptionError(EncryptionError):
    """Raised when decryption fails."""
    pass


class EncryptionManager:
    """
    Manages AES-256-GCM encryption/decryption for PII values.
    
    This class provides a simple interface for encrypting original PII values
    before storing them in the mapping table and decrypting them during
    desanitization.
    
    Attributes:
        _fernet: Fernet instance for encryption/decryption operations
        _key_source: Source of the encryption key (for debugging)
    
    Environment Variables:
        SANITIZATION_ENCRYPTION_KEY: Base64-encoded Fernet key (32 bytes)
    
    Example:
        ```python
        # Generate a new key (one-time setup)
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        print(f"Export this: export SANITIZATION_ENCRYPTION_KEY={key.decode()}")
        
        # Use in application
        manager = EncryptionManager()
        encrypted = manager.encrypt("secret value")
        decrypted = manager.decrypt(encrypted)
        assert decrypted == "secret value"
        ```
    
    Thread Safety:
        Fernet operations are thread-safe. Multiple threads can safely
        use the same EncryptionManager instance.
    """
    
    ENV_KEY_NAME = "SANITIZATION_ENCRYPTION_KEY"
    
    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize encryption manager with key from environment or parameter.
        
        Args:
            encryption_key: Optional base64-encoded Fernet key.
                          If not provided, reads from environment variable.
        
        Raises:
            EncryptionKeyError: If key is missing or invalid
        """
        # Get encryption key
        if encryption_key:
            key = encryption_key
            self._key_source = "parameter"
        else:
            key = os.getenv(self.ENV_KEY_NAME)
            self._key_source = f"environment ({self.ENV_KEY_NAME})"
        
        if not key:
            raise EncryptionKeyError(
                f"Encryption key not found. Set {self.ENV_KEY_NAME} "
                f"environment variable or provide encryption_key parameter.\n"
                f"Generate a key with: python -c 'from cryptography.fernet import Fernet; "
                f"print(Fernet.generate_key().decode())'"
            )
        
        # Initialize Fernet cipher
        try:
            # Ensure key is bytes
            if isinstance(key, str):
                key_bytes = key.encode('utf-8')
            else:
                key_bytes = key
            
            self._fernet = Fernet(key_bytes)
        except Exception as e:
            raise EncryptionKeyError(
                f"Invalid encryption key format: {str(e)}\n"
                f"Key must be a valid base64-encoded Fernet key (32 bytes).\n"
                f"Generate a new key with: python -c 'from cryptography.fernet import Fernet; "
                f"print(Fernet.generate_key().decode())'"
            )
    
    def encrypt(self, plaintext: Optional[str]) -> Optional[bytes]:
        """
        Encrypt a plaintext string.
        
        Args:
            plaintext: String to encrypt (None for NULL values)
        
        Returns:
            Encrypted bytes or None if plaintext is None
        
        Raises:
            EncryptionError: If encryption fails
        
        Example:
            ```python
            manager = EncryptionManager()
            encrypted = manager.encrypt("john@example.com")
            # encrypted is bytes: b'gAAAAA...'
            ```
        """
        if plaintext is None:
            return None
        
        try:
            # Convert string to bytes and encrypt
            plaintext_bytes = plaintext.encode('utf-8')
            encrypted_bytes = self._fernet.encrypt(plaintext_bytes)
            return encrypted_bytes
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {str(e)}")
    
    def decrypt(self, ciphertext: Optional[Union[bytes, memoryview]]) -> Optional[str]:
        """
        Decrypt ciphertext back to original string.
        
        Args:
            ciphertext: Encrypted bytes to decrypt (None for NULL values)
        
        Returns:
            Decrypted string or None if ciphertext is None
        
        Raises:
            DecryptionError: If decryption fails (invalid key, corrupted data, etc.)
        
        Example:
            ```python
            manager = EncryptionManager()
            encrypted = manager.encrypt("john@example.com")
            original = manager.decrypt(encrypted)
            assert original == "john@example.com"
            ```
        """
        if ciphertext is None:
            return None
        
        try:
            # Convert memoryview to bytes if needed (from SQL Server VARBINARY)
            if isinstance(ciphertext, memoryview):
                ciphertext = bytes(ciphertext)
            
            # Decrypt and convert bytes to string
            plaintext_bytes = self._fernet.decrypt(ciphertext)
            plaintext = plaintext_bytes.decode('utf-8')
            return plaintext
        except InvalidToken:
            raise DecryptionError(
                "Decryption failed: Invalid token. "
                "This usually means the encryption key has changed or the data is corrupted."
            )
        except Exception as e:
            raise DecryptionError(f"Decryption failed: {str(e)}")
    
    def encrypt_batch(self, values: list[Optional[str]]) -> list[Optional[bytes]]:
        """
        Encrypt multiple values efficiently.
        
        Args:
            values: List of strings to encrypt
        
        Returns:
            List of encrypted bytes (same order as input)
        
        Example:
            ```python
            manager = EncryptionManager()
            emails = ["user1@example.com", "user2@example.com", None]
            encrypted = manager.encrypt_batch(emails)
            ```
        """
        return [self.encrypt(value) for value in values]
    
    def decrypt_batch(self, ciphertexts: list[Optional[Union[bytes, memoryview]]]) -> list[Optional[str]]:
        """
        Decrypt multiple values efficiently.
        
        Args:
            ciphertexts: List of encrypted bytes to decrypt
        
        Returns:
            List of decrypted strings (same order as input)
        
        Example:
            ```python
            manager = EncryptionManager()
            encrypted = [b'gAAAAA...', b'gAAAAB...', None]
            decrypted = manager.decrypt_batch(encrypted)
            ```
        """
        return [self.decrypt(ciphertext) for ciphertext in ciphertexts]
    
    def is_available(self) -> bool:
        """
        Check if encryption is properly configured.
        
        Returns:
            True if encryption key is available and valid
        """
        return self._fernet is not None
    
    def get_key_info(self) -> dict:
        """
        Get information about the encryption key (for debugging).
        
        Returns:
            Dictionary with key source and availability status
        
        Note:
            Never returns the actual key value for security reasons
        """
        return {
            "available": self.is_available(),
            "source": self._key_source,
            "algorithm": "Fernet (AES-256-GCM)"
        }


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.
    
    Returns:
        Base64-encoded encryption key suitable for environment variable
    
    Example:
        ```python
        from mapping.encryption_utils import generate_encryption_key
        
        key = generate_encryption_key()
        print(f"Add to .env file:")
        print(f"SANITIZATION_ENCRYPTION_KEY={key}")
        ```
    
    Note:
        This should only be used once during initial setup.
        Store the generated key securely and never regenerate it
        if you have existing encrypted data.
    """
    key = Fernet.generate_key()
    return key.decode('utf-8')


def validate_encryption_key(key: str) -> bool:
    """
    Validate that a key is a valid Fernet encryption key.
    
    Args:
        key: Base64-encoded key to validate
    
    Returns:
        True if key is valid, False otherwise
    
    Example:
        ```python
        key = generate_encryption_key()
        assert validate_encryption_key(key) == True
        assert validate_encryption_key("invalid") == False
        ```
    """
    try:
        key_bytes = key.encode('utf-8') if isinstance(key, str) else key
        Fernet(key_bytes)
        return True
    except Exception:
        return False


# Convenience functions for quick encryption/decryption
def quick_encrypt(plaintext: str, key: Optional[str] = None) -> bytes:
    """
    Quick encryption without creating manager instance.
    
    Args:
        plaintext: String to encrypt
        key: Optional encryption key (uses environment if not provided)
    
    Returns:
        Encrypted bytes
    """
    manager = EncryptionManager(key)
    return manager.encrypt(plaintext)


def quick_decrypt(ciphertext: bytes, key: Optional[str] = None) -> str:
    """
    Quick decryption without creating manager instance.
    
    Args:
        ciphertext: Encrypted bytes to decrypt
        key: Optional encryption key (uses environment if not provided)
    
    Returns:
        Decrypted string
    """
    manager = EncryptionManager(key)
    return manager.decrypt(ciphertext)


if __name__ == "__main__":
    # Self-test and key generation utility
    print("=" * 70)
    print("Encryption Utilities - Key Generation & Test")
    print("=" * 70)
    
    # Check if key exists in environment
    existing_key = os.getenv(EncryptionManager.ENV_KEY_NAME)
    
    if existing_key:
        print("\n✓ Encryption key found in environment")
        print(f"  Variable: {EncryptionManager.ENV_KEY_NAME}")
        print(f"  Valid: {validate_encryption_key(existing_key)}")
        
        # Test encryption roundtrip
        try:
            manager = EncryptionManager()
            test_value = "test@example.com"
            encrypted = manager.encrypt(test_value)
            decrypted = manager.decrypt(encrypted)
            
            print(f"\n✓ Encryption test passed")
            print(f"  Original:  {test_value}")
            print(f"  Encrypted: {encrypted[:50]}..." if len(encrypted) > 50 else f"  Encrypted: {encrypted}")
            print(f"  Decrypted: {decrypted}")
            print(f"  Match: {test_value == decrypted}")
        except Exception as e:
            print(f"\n✗ Encryption test failed: {e}")
    else:
        print(f"\n⚠ No encryption key found in environment")
        print(f"  Variable name: {EncryptionManager.ENV_KEY_NAME}")
        print(f"\nGenerating new encryption key...")
        
        new_key = generate_encryption_key()
        print(f"\n{'=' * 70}")
        print("ADD THIS TO YOUR .env FILE:")
        print(f"{'=' * 70}")
        print(f"{EncryptionManager.ENV_KEY_NAME}={new_key}")
        print(f"{'=' * 70}")
        print("\n⚠ IMPORTANT:")
        print("  - Store this key securely")
        print("  - Never commit it to version control")
        print("  - Backup the key in a secure location")
        print("  - Do not regenerate if you have existing encrypted data")
        print(f"{'=' * 70}")
