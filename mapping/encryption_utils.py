"""
Encryption utilities for mapping table data at rest.

This module provides AES-256-GCM encryption for protecting sensitive
mapping data (original_value and masked_value) stored in the token_mappings table.

Usage:
    from mapping.encryption_utils import MappingEncryptor
    
    # Initialize with key from environment
    encryptor = MappingEncryptor.from_environment()
    
    # Encrypt a value
    encrypted = encryptor.encrypt("sensitive_data")
    
    # Decrypt a value
    original = encryptor.decrypt(encrypted)
    
    # Key rotation support
    old_encryptor = MappingEncryptor(old_key)
    new_encryptor = MappingEncryptor.from_environment()
    
    decrypted = old_encryptor.decrypt(old_encrypted_value)
    re_encrypted = new_encryptor.encrypt(decrypted)

Author: Database Sanitization Team
Date: April 9, 2026
"""

import os
import base64
from typing import Optional, List

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from .exceptions import EncryptionError, KeyManagementError, DecryptionError


class MappingEncryptor:
    """
    AES-256-GCM encryption for mapping table data.
    
    Provides transparent encryption/decryption of sensitive mapping values
    with authenticated encryption (prevents tampering). Supports key rotation
    by allowing multiple decryption keys while encrypting with the latest key.
    
    Key Format:
        - 32 bytes (256 bits) for AES-256
        - Base64-encoded for storage in environment variables
        - Generated with: cryptography.fernet.Fernet.generate_key() or similar
    
    Attributes:
        _cipher: AESGCM cipher instance for current encryption key
        _fallback_ciphers: List of AESGCM instances for key rotation support
        _key_id: Optional identifier for current key (for debugging)
    """
    
    DEFAULT_KEY_ENV_VAR = "MAPPING_ENCRYPTION_KEY"
    KEY_SIZE_BYTES = 32  # 256 bits for AES-256
    
    def __init__(
        self,
        encryption_key: bytes,
        fallback_keys: Optional[List[bytes]] = None,
        key_id: Optional[str] = None
    ):
        """
        Initialize encryptor with encryption key.
        
        Args:
            encryption_key: 32-byte encryption key (for AES-256)
            fallback_keys: Optional list of old keys for key rotation support
            key_id: Optional identifier for debugging (not stored with data)
            
        Raises:
            KeyManagementError: If key is invalid (wrong length, wrong type)
        """
        # Validate encryption key
        if not isinstance(encryption_key, bytes):
            raise KeyManagementError(
                f"Encryption key must be bytes, got {type(encryption_key).__name__}",
                suggested_action="Use base64.b64decode() to convert base64 string to bytes"
            )
        
        if len(encryption_key) != self.KEY_SIZE_BYTES:
            raise KeyManagementError(
                f"Encryption key must be {self.KEY_SIZE_BYTES} bytes (256 bits), "
                f"got {len(encryption_key)} bytes",
                suggested_action=f"Generate a valid key with: "
                f"python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        
        # Initialize primary cipher
        try:
            self._cipher = AESGCM(encryption_key)
        except Exception as e:
            raise KeyManagementError(
                f"Failed to initialize cipher with provided key: {e}",
                suggested_action="Verify key is valid 32-byte AES key"
            ) from e
        
        # Initialize fallback ciphers for key rotation
        self._fallback_ciphers = []
        if fallback_keys:
            for idx, fallback_key in enumerate(fallback_keys):
                if not isinstance(fallback_key, bytes):
                    raise KeyManagementError(
                        f"Fallback key {idx} must be bytes, got {type(fallback_key).__name__}"
                    )
                if len(fallback_key) != self.KEY_SIZE_BYTES:
                    raise KeyManagementError(
                        f"Fallback key {idx} must be {self.KEY_SIZE_BYTES} bytes, "
                        f"got {len(fallback_key)} bytes"
                    )
                try:
                    self._fallback_ciphers.append(AESGCM(fallback_key))
                except Exception as e:
                    raise KeyManagementError(
                        f"Failed to initialize fallback cipher {idx}: {e}"
                    ) from e
        
        self._key_id = key_id or "primary"
    
    @classmethod
    def from_environment(
        cls,
        key_env_var: str = DEFAULT_KEY_ENV_VAR,
        fallback_env_vars: Optional[List[str]] = None
    ) -> 'MappingEncryptor':
        """
        Create encryptor from environment variable.
        
        Args:
            key_env_var: Environment variable name containing base64-encoded key
            fallback_env_vars: Optional list of env vars for old keys (key rotation)
            
        Returns:
            MappingEncryptor instance
            
        Raises:
            KeyManagementError: If environment variable missing or invalid
            
        Example:
            >>> os.environ['MAPPING_ENCRYPTION_KEY'] = 'base64_encoded_32_byte_key...'
            >>> encryptor = MappingEncryptor.from_environment()
        """
        # Load primary key
        key_b64 = os.getenv(key_env_var)
        if not key_b64:
            raise KeyManagementError(
                f"Encryption key not found in environment variable '{key_env_var}'",
                suggested_action=(
                    f"Set {key_env_var} in your environment:\n"
                    f"  1. Generate a key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
                    f"  2. Set environment variable: export {key_env_var}='your_generated_key'\n"
                    f"  Or add to .env file: {key_env_var}=your_generated_key"
                )
            )
        
        # Decode primary key
        try:
            encryption_key = base64.b64decode(key_b64)
        except Exception as e:
            raise KeyManagementError(
                f"Failed to decode base64 key from '{key_env_var}': {e}",
                suggested_action="Ensure key is valid base64-encoded 32-byte value"
            ) from e
        
        # Load fallback keys for rotation support
        fallback_keys = []
        if fallback_env_vars:
            for var_name in fallback_env_vars:
                fallback_b64 = os.getenv(var_name)
                if fallback_b64:
                    try:
                        fallback_keys.append(base64.b64decode(fallback_b64))
                    except Exception as e:
                        raise KeyManagementError(
                            f"Failed to decode fallback key from '{var_name}': {e}"
                        ) from e
        
        return cls(
            encryption_key=encryption_key,
            fallback_keys=fallback_keys if fallback_keys else None,
            key_id=key_env_var
        )
    
    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt a plaintext value.
        
        Uses AES-256-GCM authenticated encryption with a random 96-bit nonce.
        The nonce is prepended to the ciphertext for decryption.
        
        Args:
            plaintext: String value to encrypt (None returns None)
            
        Returns:
            Base64-encoded encrypted value (format: nonce + ciphertext + tag)
            Returns None if plaintext is None (preserves NULL semantics)
            
        Raises:
            EncryptionError: If encryption fails
            
        Example:
            >>> encryptor.encrypt("john.doe@example.com")
            'AQIDBAUGBwgJCgsMDQ4P...encrypted_data...'
        """
        # Preserve NULL values (database NULL should remain NULL)
        if plaintext is None:
            return None
        
        # Convert to bytes
        plaintext_bytes = plaintext.encode('utf-8')
        
        try:
            # Generate random 96-bit nonce (12 bytes, GCM standard)
            nonce = os.urandom(12)
            
            # Encrypt with authenticated encryption
            # Returns: ciphertext + authentication tag (appended)
            ciphertext = self._cipher.encrypt(nonce, plaintext_bytes, None)
            
            # Prepend nonce to ciphertext for storage
            # Format: [nonce (12 bytes)][ciphertext + tag (variable)]
            encrypted_data = nonce + ciphertext
            
            # Base64 encode for storage in NVARCHAR column
            return base64.b64encode(encrypted_data).decode('ascii')
            
        except Exception as e:
            raise EncryptionError(
                f"Encryption failed: {e}",
                suggested_action="Verify encryption key is valid and not corrupted"
            ) from e
    
    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        Decrypt an encrypted value.
        
        Attempts decryption with primary key first, then fallback keys if configured
        (supports key rotation). Verifies authentication tag to detect tampering.
        
        Args:
            ciphertext: Base64-encoded encrypted value (None returns None)
            
        Returns:
            Decrypted plaintext string
            Returns None if ciphertext is None (preserves NULL semantics)
            
        Raises:
            DecryptionError: If decryption fails (wrong key, corrupted data, tampered)
            
        Example:
            >>> encryptor.decrypt('AQIDBAUGBwgJCgsMDQ4P...encrypted_data...')
            'john.doe@example.com'
        """
        # Preserve NULL values
        if ciphertext is None:
            return None
        
        # Decode from base64
        try:
            encrypted_data = base64.b64decode(ciphertext)
        except Exception as e:
            raise DecryptionError(
                f"Failed to decode base64 ciphertext: {e}",
                suggested_action="Data may be corrupted or not encrypted with this system"
            ) from e
        
        # Validate minimum length (12-byte nonce + at least 16-byte tag)
        if len(encrypted_data) < 28:
            raise DecryptionError(
                f"Ciphertext too short ({len(encrypted_data)} bytes, minimum 28)",
                suggested_action="Data may be corrupted or truncated"
            )
        
        # Extract nonce (first 12 bytes)
        nonce = encrypted_data[:12]
        ciphertext_with_tag = encrypted_data[12:]
        
        # Try decryption with primary key
        try:
            plaintext_bytes = self._cipher.decrypt(nonce, ciphertext_with_tag, None)
            return plaintext_bytes.decode('utf-8')
        except InvalidTag:
            # Authentication tag verification failed - try fallback keys
            if not self._fallback_ciphers:
                raise DecryptionError(
                    "Decryption failed: Authentication tag mismatch (possible tampering or wrong key)",
                    suggested_action=(
                        "Verify MAPPING_ENCRYPTION_KEY matches the key used for encryption. "
                        "If key was rotated, configure fallback keys."
                    )
                )
            
            # Try fallback keys (key rotation support)
            for idx, fallback_cipher in enumerate(self._fallback_ciphers):
                try:
                    plaintext_bytes = fallback_cipher.decrypt(nonce, ciphertext_with_tag, None)
                    return plaintext_bytes.decode('utf-8')
                except InvalidTag:
                    continue  # Try next fallback key
            
            # All keys failed
            raise DecryptionError(
                f"Decryption failed with primary and {len(self._fallback_ciphers)} fallback key(s)",
                suggested_action=(
                    "None of the configured keys can decrypt this data. "
                    "Verify correct encryption keys are configured."
                )
            )
        except Exception as e:
            raise DecryptionError(
                f"Decryption failed: {e}",
                suggested_action="Data may be corrupted or encrypted with incompatible algorithm"
            ) from e
    
    def encrypt_batch(self, values: List[Optional[str]]) -> List[Optional[str]]:
        """
        Encrypt multiple values efficiently.
        
        Args:
            values: List of plaintext values (None elements preserved)
            
        Returns:
            List of encrypted values (same length as input)
            
        Raises:
            EncryptionError: If any encryption fails
        """
        return [self.encrypt(value) for value in values]
    
    def decrypt_batch(self, values: List[Optional[str]]) -> List[Optional[str]]:
        """
        Decrypt multiple values efficiently.
        
        Args:
            values: List of encrypted values (None elements preserved)
            
        Returns:
            List of decrypted values (same length as input)
            
        Raises:
            DecryptionError: If any decryption fails
        """
        return [self.decrypt(value) for value in values]
    
    def __repr__(self) -> str:
        fallback_count = len(self._fallback_ciphers)
        return (
            f"MappingEncryptor(key_id='{self._key_id}', "
            f"fallback_keys={fallback_count})"
        )


def generate_encryption_key() -> str:
    """
    Generate a new AES-256 encryption key.
    
    Returns:
        Base64-encoded 32-byte key suitable for MAPPING_ENCRYPTION_KEY
        
    Example:
        >>> key = generate_encryption_key()
        >>> print(f"export MAPPING_ENCRYPTION_KEY='{key}'")
    """
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode('ascii')


def validate_encryption_key(key_b64: str) -> bool:
    """
    Validate an encryption key format.
    
    Args:
        key_b64: Base64-encoded key to validate
        
    Returns:
        True if key is valid, False otherwise
    """
    try:
        key_bytes = base64.b64decode(key_b64)
        return len(key_bytes) == MappingEncryptor.KEY_SIZE_BYTES
    except Exception:
        return False
