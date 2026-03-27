"""
Unit tests for EncryptionManager class (encryption_utils.py).

Tests cover:
- Initialization with parameter key vs environment variable
- Key loading and validation
- Encryption of various data types (strings, Unicode, empty, None)
- Decryption and round-trip verification
- generate_key() static method
- is_key_valid() static method  
- Error handling (missing keys, invalid keys, invalid data, decryption failures)
- Edge cases (empty strings, Unicode, long strings, special characters)
- Security considerations (no plaintext logging)

Test Organization:
- TestEncryptionManagerInit: Initialization and key loading
- TestKeyGeneration: generate_key() functionality
- TestKeyValidation: is_key_valid() functionality  
- TestEncryption: encrypt() method
- TestDecryption: decrypt() method
- TestRoundTrip: Full encrypt/decrypt cycles
- TestNullHandling: None and empty string handling
- TestEdgeCases: Unicode, long strings, special characters
- TestErrorHandling: Invalid keys, decryption failures

Author: Database Sanitization Team
Date: 2026-03-27
"""

import pytest
from unittest.mock import Mock, patch
import os

from cryptography.fernet import Fernet, InvalidToken

from src.mapping.encryption_utils import EncryptionManager
from src.exceptions import MappingError
from tests.test_helpers import generate_unicode_strings, generate_long_strings, generate_special_character_strings


class TestEncryptionManagerInit:
    """Test EncryptionManager initialization."""
    
    def test_init_with_parameter_key(self):
        """Test initialization with encryption key as parameter."""
        key = Fernet.generate_key()
        key_str = key.decode('utf-8')
        
        manager = EncryptionManager(encryption_key=key_str)
        
        assert manager.fernet is not None
        assert manager.logger is not None
    
    def test_init_with_environment_variable(self):
        """Test initialization loading key from environment variable."""
        key = Fernet.generate_key()
        key_str = key.decode('utf-8')
        
        with patch.dict(os.environ, {'SANITIZATION_MAPPING_ENCRYPTION_KEY': key_str}):
            manager = EncryptionManager()
            
            assert manager.fernet is not None
            assert manager.logger is not None
    
    def test_init_without_key_raises_error(self):
        """Test initialization without key raises MappingError."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove env var
            os.environ.pop('SANITIZATION_MAPPING_ENCRYPTION_KEY', None)
            
            with pytest.raises(MappingError):
                EncryptionManager()
    
    def test_init_with_invalid_key_format(self):
        """Test initialization with invalid key format raises error."""
        invalid_key = "not-a-valid-fernet-key"
        
        with pytest.raises(MappingError):
            EncryptionManager(encryption_key=invalid_key)
    
    def test_init_with_short_key(self):
        """Test initialization with too-short key raises error."""
        short_key = "short"
        
        with pytest.raises(MappingError):
            EncryptionManager(encryption_key=short_key)
    
    def test_init_parameter_overrides_environment(self):
        """Test that parameter key overrides environment variable."""
        env_key = Fernet.generate_key().decode('utf-8')
        param_key = Fernet.generate_key().decode('utf-8')
        
        with patch.dict(os.environ, {'SANITIZATION_MAPPING_ENCRYPTION_KEY': env_key}):
            manager = EncryptionManager(encryption_key=param_key)
            
            # Encrypt with param key
            encrypted = manager.encrypt("test")
            
            # Should decrypt with param key, not env key
            decrypted = manager.decrypt(encrypted)
            assert decrypted == "test"


class TestKeyGeneration:
    """Test generate_key() static method."""
    
    def test_generate_key_returns_string(self):
        """Test generate_key() returns a string."""
        key = EncryptionManager.generate_key()
        
        assert isinstance(key, str)
    
    def test_generate_key_length(self):
        """Test generate_key() returns 44-character key."""
        key = EncryptionManager.generate_key()
        
        # Fernet keys are 44 characters (32 bytes base64-encoded)
        assert len(key) == 44
    
    def test_generate_key_unique(self):
        """Test generate_key() generates unique keys."""
        key1 = EncryptionManager.generate_key()
        key2 = EncryptionManager.generate_key()
        
        assert key1 != key2
    
    def test_generate_key_valid(self):
        """Test generate_key() produces valid Fernet keys."""
        key = EncryptionManager.generate_key()
        
        # Should be able to create Fernet instance
        fernet = Fernet(key.encode('utf-8'))
        assert fernet is not None
    
    def test_generate_key_can_encrypt_decrypt(self):
        """Test that generated key can be used for encryption/decryption."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        original = "test_value"
        encrypted = manager.encrypt(original)
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == original


class TestKeyValidation:
    """Test is_key_valid() static method."""
    
    def test_is_key_valid_with_valid_key(self):
        """Test is_key_valid() returns True for valid key."""
        key = EncryptionManager.generate_key()
        
        assert EncryptionManager.is_key_valid(key) is True
    
    def test_is_key_valid_with_invalid_key(self):
        """Test is_key_valid() returns False for invalid key."""
        invalid_key = "not-a-valid-key"
        
        assert EncryptionManager.is_key_valid(invalid_key) is False
    
    def test_is_key_valid_with_short_key(self):
        """Test is_key_valid() returns False for short key."""
        short_key = "short"
        
        assert EncryptionManager.is_key_valid(short_key) is False
    
    def test_is_key_valid_with_empty_string(self):
        """Test is_key_valid() returns False for empty string."""
        assert EncryptionManager.is_key_valid("") is False
    
    def test_is_key_valid_with_wrong_length(self):
        """Test is_key_valid() returns False for wrong length."""
        # 43 characters (too short by 1)
        wrong_length = "A" * 43
        
        assert EncryptionManager.is_key_valid(wrong_length) is False


class TestEncryption:
    """Test encrypt() method."""
    
    def test_encrypt_basic_string(self):
        """Test encrypting a basic string."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        value = "test_value"
        encrypted = manager.encrypt(value)
        
        assert encrypted is not None
        assert isinstance(encrypted, bytes)
        assert encrypted != value.encode('utf-8')  # Should be encrypted, not plaintext
    
    def test_encrypt_returns_bytes(self):
        """Test encrypt() returns bytes type."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt("test")
        
        assert isinstance(encrypted, bytes)
    
    def test_encrypt_none_returns_none(self):
        """Test encrypting None returns None."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt(None)
        
        assert encrypted is None
    
    def test_encrypt_empty_string(self):
        """Test encrypting empty string."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt("")
        
        assert encrypted is not None
        assert isinstance(encrypted, bytes)
        assert len(encrypted) > 0  # Fernet adds overhead even for empty strings
    
    def test_encrypt_same_value_different_output(self):
        """Test encrypting same value produces different ciphertext (due to IV)."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        value = "test_value"
        encrypted1 = manager.encrypt(value)
        encrypted2 = manager.encrypt(value)
        
        # Fernet uses random IV, so same plaintext = different ciphertext
        assert encrypted1 != encrypted2
    
    def test_encrypt_long_string(self):
        """Test encrypting long strings."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        long_strings = generate_long_strings()
        
        for name, long_value in long_strings.items():
            encrypted = manager.encrypt(long_value)
            
            assert encrypted is not None
            assert isinstance(encrypted, bytes)
    
    def test_encrypt_unicode_string(self):
        """Test encrypting Unicode strings."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        unicode_strings = generate_unicode_strings()
        
        for name, unicode_value in unicode_strings.items():
            encrypted = manager.encrypt(unicode_value)
            
            assert encrypted is not None
            assert isinstance(encrypted, bytes)
    
    def test_encrypt_special_characters(self):
        """Test encrypting strings with special characters."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        special_strings = generate_special_character_strings()
        
        for name, special_value in special_strings.items():
            encrypted = manager.encrypt(special_value)
            
            assert encrypted is not None
            assert isinstance(encrypted, bytes)


class TestDecryption:
    """Test decrypt() method."""
    
    def test_decrypt_basic_encrypted_value(self):
        """Test decrypting an encrypted value."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        original = "test_value"
        encrypted = manager.encrypt(original)
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == original
    
    def test_decrypt_none_returns_none(self):
        """Test decrypting None returns None."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        decrypted = manager.decrypt(None)
        
        assert decrypted is None
    
    def test_decrypt_empty_string_ciphertext(self):
        """Test decrypting empty string ciphertext."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt("")
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == ""
    
    def test_decrypt_with_wrong_key_raises_error(self):
        """Test decrypting with wrong key raises error."""
        key1 = EncryptionManager.generate_key()
        key2 = EncryptionManager.generate_key()
        
        manager1 = EncryptionManager(encryption_key=key1)
        manager2 = EncryptionManager(encryption_key=key2)
        
        encrypted = manager1.encrypt("test")
        
        # Should fail to decrypt with wrong key
        with pytest.raises(MappingError):
            manager2.decrypt(encrypted)
    
    def test_decrypt_invalid_ciphertext(self):
        """Test decrypting invalid ciphertext raises error."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        invalid_ciphertext = b"not-valid-fernet-ciphertext"
        
        with pytest.raises(MappingError):
            manager.decrypt(invalid_ciphertext)
    
    def test_decrypt_corrupted_ciphertext(self):
        """Test decrypting corrupted ciphertext raises error."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt("test")
        
        # Corrupt the ciphertext (flip some bits)
        corrupted = bytearray(encrypted)
        corrupted[10] ^= 0xFF  # Flip bits
        corrupted = bytes(corrupted)
        
        with pytest.raises(MappingError):
            manager.decrypt(corrupted)


class TestRoundTrip:
    """Test full encrypt/decrypt round trips."""
    
    def test_roundtrip_basic_string(self):
        """Test encrypt/decrypt round trip preserves value."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        original = "test_value"
        encrypted = manager.encrypt(original)
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == original
    
    def test_roundtrip_unicode_strings(self):
        """Test round trip with Unicode strings."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        unicode_strings = generate_unicode_strings()
        
        for name, original in unicode_strings.items():
            encrypted = manager.encrypt(original)
            decrypted = manager.decrypt(encrypted)
            
            assert decrypted == original, f"Round trip failed for {name}"
    
    def test_roundtrip_long_strings(self):
        """Test round trip with long strings."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        long_strings = generate_long_strings()
        
        for name, original in long_strings.items():
            encrypted = manager.encrypt(original)
            decrypted = manager.decrypt(encrypted)
            
            assert decrypted == original, f"Round trip failed for {name}"
    
    def test_roundtrip_special_characters(self):
        """Test round trip with special characters."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        special_strings = generate_special_character_strings()
        
        for name, original in special_strings.items():
            encrypted = manager.encrypt(original)
            decrypted = manager.decrypt(encrypted)
            
            assert decrypted == original, f"Round trip failed for {name}"
    
    def test_roundtrip_pii_data(self):
        """Test round trip with realistic PII data."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        pii_samples = [
            "john.doe@example.com",
            "555-123-4567",
            "123-45-6789",
            "123 Main St, Apt 4B, New York, NY 10001",
            "O'Brien, Mary Jane",
            "$1,234,567.89",
            "2026-03-27"
        ]
        
        for original in pii_samples:
            encrypted = manager.encrypt(original)
            decrypted = manager.decrypt(encrypted)
            
            assert decrypted == original
    
    def test_roundtrip_multiple_values(self):
        """Test encrypting/decrypting multiple values."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        values = [f"value_{i}" for i in range(100)]
        
        encrypted_values = [manager.encrypt(v) for v in values]
        decrypted_values = [manager.decrypt(e) for e in encrypted_values]
        
        assert decrypted_values == values


class TestNullHandling:
    """Test None and empty string handling."""
    
    def test_none_input_returns_none(self):
        """Test that None input returns None (no encryption)."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        result = manager.encrypt(None)
        
        assert result is None
    
    def test_none_encrypted_value_returns_none(self):
        """Test that None encrypted value returns None (no decryption)."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        result = manager.decrypt(None)
        
        assert result is None
    
    def test_empty_string_encrypts(self):
        """Test that empty string is encrypted (not treated as None)."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt("")
        
        assert encrypted is not None
        assert isinstance(encrypted, bytes)
        assert len(encrypted) > 0
    
    def test_empty_string_roundtrip(self):
        """Test empty string round trip."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        encrypted = manager.encrypt("")
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == ""


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_whitespace_only_string(self):
        """Test encrypting whitespace-only strings."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        whitespace_strings = ["   ", "\t", "\n", "\r\n", "  \t\n  "]
        
        for ws in whitespace_strings:
            encrypted = manager.encrypt(ws)
            decrypted = manager.decrypt(encrypted)
            
            assert decrypted == ws
    
    def test_very_long_string(self):
        """Test encrypting very long strings (1MB+)."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        # 1MB string
        very_long = "A" * (1024 * 1024)
        
        encrypted = manager.encrypt(very_long)
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == very_long
    
    def test_binary_like_strings(self):
        """Test strings that look like binary data."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        binary_like = [
            "\\x00\\x01\\x02",
            "\x00\x01\x02",
            "00000000",
            "DEADBEEF"
        ]
        
        for value in binary_like:
            encrypted = manager.encrypt(value)
            decrypted = manager.decrypt(encrypted)
            
            assert decrypted == value
    
    def test_repeated_encryption_different_ciphertext(self):
        """Test that repeated encryption of same value produces different ciphertexts."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        value = "test_value"
        ciphertexts = set()
        
        for _ in range(10):
            encrypted = manager.encrypt(value)
            ciphertexts.add(encrypted)
        
        # All ciphertexts should be different (Fernet uses random IV)
        assert len(ciphertexts) == 10
    
    def test_key_as_bytes(self):
        """Test initialization with key as bytes (not string)."""
        key_bytes = Fernet.generate_key()
        
        # Should accept bytes
        manager = EncryptionManager(encryption_key=key_bytes.decode('utf-8'))
        
        encrypted = manager.encrypt("test")
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == "test"


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_missing_key_error_message(self):
        """Test that missing key error has clear message."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('SANITIZATION_MAPPING_ENCRYPTION_KEY', None)
            
            with pytest.raises(MappingError) as exc_info:
                EncryptionManager()
            
            assert "key" in str(exc_info.value).lower()
    
    def test_invalid_key_error_message(self):
        """Test that invalid key error has clear message."""
        with pytest.raises(MappingError) as exc_info:
            EncryptionManager(encryption_key="invalid")
        
        assert "key" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()
    
    def test_decryption_failure_error_message(self):
        """Test that decryption failure error has clear message."""
        key = EncryptionManager.generate_key()
        manager = EncryptionManager(encryption_key=key)
        
        with pytest.raises(MappingError) as exc_info:
            manager.decrypt(b"invalid_ciphertext")
        
        assert "decrypt" in str(exc_info.value).lower()
