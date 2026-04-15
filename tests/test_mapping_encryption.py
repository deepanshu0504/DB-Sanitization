"""
Unit tests for mapping encryption utilities (Story 1.3).

Tests cover:
- Encryption/decryption round-trips
- NULL value handling
- Key validation
- Key rotation support
- Error handling (missing key, invalid key, corrupted data)
- Batch operations

Run with: pytest tests/test_mapping_encryption.py -v
"""

import os
import base64
import pytest
from typing import Optional

from mapping.encryption_utils import (
    MappingEncryptor,
    generate_encryption_key,
    validate_encryption_key
)
from mapping.exceptions import KeyManagementError, EncryptionError, DecryptionError


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def valid_key() -> bytes:
    """Generate a valid 32-byte encryption key."""
    return os.urandom(32)


@pytest.fixture
def valid_key_b64(valid_key: bytes) -> str:
    """Generate a valid base64-encoded key."""
    return base64.b64encode(valid_key).decode('ascii')


@pytest.fixture
def encryptor(valid_key: bytes) -> MappingEncryptor:
    """Create MappingEncryptor instance with valid key."""
    return MappingEncryptor(valid_key)


@pytest.fixture
def old_key() -> bytes:
    """Generate an old key for rotation tests."""
    return os.urandom(32)


@pytest.fixture
def setup_env_key(valid_key_b64: str):
    """Set up environment variable with encryption key."""
    os.environ['MAPPING_ENCRYPTION_KEY'] = valid_key_b64
    yield
    # Cleanup
    if 'MAPPING_ENCRYPTION_KEY' in os.environ:
        del os.environ['MAPPING_ENCRYPTION_KEY']


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

def test_init_with_valid_key(valid_key: bytes):
    """Test initialization with valid 32-byte key."""
    encryptor = MappingEncryptor(valid_key)
    assert encryptor is not None
    assert encryptor._key_id == "primary"


def test_init_with_fallback_keys(valid_key: bytes, old_key: bytes):
    """Test initialization with fallback keys for rotation."""
    encryptor = MappingEncryptor(
        encryption_key=valid_key,
        fallback_keys=[old_key],
        key_id="current"
    )
    assert encryptor is not None
    assert len(encryptor._fallback_ciphers) == 1
    assert encryptor._key_id == "current"


def test_init_with_invalid_key_type():
    """Test initialization with wrong key type raises error."""
    with pytest.raises(KeyManagementError) as exc_info:
        MappingEncryptor("not_bytes")
    
    assert "must be bytes" in str(exc_info.value)
    assert "base64.b64decode()" in exc_info.value.suggested_action


def test_init_with_wrong_key_length():
    """Test initialization with wrong key length raises error."""
    short_key = os.urandom(16)  # 128 bits, not 256
    
    with pytest.raises(KeyManagementError) as exc_info:
        MappingEncryptor(short_key)
    
    assert "32 bytes" in str(exc_info.value)
    assert "256 bits" in str(exc_info.value)


def test_from_environment(setup_env_key, valid_key_b64):
    """Test creating encryptor from environment variable."""
    encryptor = MappingEncryptor.from_environment()
    assert encryptor is not None
    assert encryptor._key_id == "MAPPING_ENCRYPTION_KEY"


def test_from_environment_missing_key():
    """Test error when environment variable not set."""
    # Ensure key not in environment
    if 'MAPPING_ENCRYPTION_KEY' in os.environ:
        del os.environ['MAPPING_ENCRYPTION_KEY']
    
    with pytest.raises(KeyManagementError) as exc_info:
        MappingEncryptor.from_environment()
    
    assert "not found" in str(exc_info.value)
    assert "MAPPING_ENCRYPTION_KEY" in str(exc_info.value)
    assert "export" in exc_info.value.suggested_action.lower()


def test_from_environment_invalid_base64():
    """Test error when environment variable has invalid base64."""
    os.environ['MAPPING_ENCRYPTION_KEY'] = "not_valid_base64!!!"
    
    try:
        with pytest.raises(KeyManagementError) as exc_info:
            MappingEncryptor.from_environment()
        
        assert "decode" in str(exc_info.value).lower()
    finally:
        del os.environ['MAPPING_ENCRYPTION_KEY']


def test_from_environment_with_fallback_keys(valid_key_b64, old_key: bytes):
    """Test loading fallback keys from environment."""
    old_key_b64 = base64.b64encode(old_key).decode('ascii')
    
    os.environ['MAPPING_ENCRYPTION_KEY'] = valid_key_b64
    os.environ['OLD_KEY_1'] = old_key_b64
    
    try:
        encryptor = MappingEncryptor.from_environment(
            fallback_env_vars=['OLD_KEY_1']
        )
        assert len(encryptor._fallback_ciphers) == 1
    finally:
        del os.environ['MAPPING_ENCRYPTION_KEY']
        del os.environ['OLD_KEY_1']


# ============================================================================
# ENCRYPTION/DECRYPTION TESTS
# ============================================================================

def test_encrypt_decrypt_round_trip(encryptor: MappingEncryptor):
    """Test basic encryption and decryption round-trip."""
    plaintext = "sensitive_data@example.com"
    
    encrypted = encryptor.encrypt(plaintext)
    assert encrypted is not None
    assert encrypted != plaintext
    assert len(encrypted) > len(plaintext)  # Encrypted data is larger
    
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == plaintext


def test_encrypt_null_value(encryptor: MappingEncryptor):
    """Test encrypting NULL value returns NULL."""
    result = encryptor.encrypt(None)
    assert result is None


def test_decrypt_null_value(encryptor: MappingEncryptor):
    """Test decrypting NULL value returns NULL."""
    result = encryptor.decrypt(None)
    assert result is None


def test_encrypt_empty_string(encryptor: MappingEncryptor):
    """Test encrypting empty string."""
    encrypted = encryptor.encrypt("")
    assert encrypted is not None
    assert encrypted != ""
    
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == ""


def test_encrypt_unicode(encryptor: MappingEncryptor):
    """Test encrypting unicode characters."""
    plaintext = "テスト@例.com 🔒"
    
    encrypted = encryptor.encrypt(plaintext)
    decrypted = encryptor.decrypt(encrypted)
    
    assert decrypted == plaintext


def test_encrypt_long_text(encryptor: MappingEncryptor):
    """Test encrypting long text values."""
    plaintext = "x" * 10000  # 10KB of data
    
    encrypted = encryptor.encrypt(plaintext)
    decrypted = encryptor.decrypt(encrypted)
    
    assert decrypted == plaintext
    assert len(encrypted) > len(plaintext)


def test_encrypt_deterministic_nonce(encryptor: MappingEncryptor):
    """Test that encryption generates different ciphertexts for same plaintext."""
    plaintext = "test@example.com"
    
    encrypted1 = encryptor.encrypt(plaintext)
    encrypted2 = encryptor.encrypt(plaintext)
    
    # Different nonces mean different ciphertexts
    assert encrypted1 != encrypted2
    
    # But both decrypt to same plaintext
    assert encryptor.decrypt(encrypted1) == plaintext
    assert encryptor.decrypt(encrypted2) == plaintext


def test_decrypt_with_wrong_key(valid_key: bytes):
    """Test decryption fails with wrong key."""
    encryptor1 = MappingEncryptor(valid_key)
    encryptor2 = MappingEncryptor(os.urandom(32))  # Different key
    
    plaintext = "secret_data"
    encrypted = encryptor1.encrypt(plaintext)
    
    with pytest.raises(DecryptionError) as exc_info:
        encryptor2.decrypt(encrypted)
    
    assert "Authentication tag mismatch" in str(exc_info.value) or "Decryption failed" in str(exc_info.value)


def test_decrypt_corrupted_data(encryptor: MappingEncryptor):
    """Test decryption fails with corrupted ciphertext."""
    plaintext = "test_data"
    encrypted = encryptor.encrypt(plaintext)
    
    # Corrupt the ciphertext
    encrypted_bytes = base64.b64decode(encrypted)
    corrupted_bytes = encrypted_bytes[:-1] + b'X'  # Change last byte
    corrupted = base64.b64encode(corrupted_bytes).decode('ascii')
    
    with pytest.raises(DecryptionError):
        encryptor.decrypt(corrupted)


def test_decrypt_too_short_data(encryptor: MappingEncryptor):
    """Test decryption fails with too short ciphertext."""
    short_data = base64.b64encode(b'short').decode('ascii')
    
    with pytest.raises(DecryptionError) as exc_info:
        encryptor.decrypt(short_data)
    
    assert "too short" in str(exc_info.value).lower()


def test_decrypt_invalid_base64(encryptor: MappingEncryptor):
    """Test decryption fails with invalid base64."""
    with pytest.raises(DecryptionError) as exc_info:
        encryptor.decrypt("not_valid_base64!!!")
    
    assert "decode" in str(exc_info.value).lower()


# ============================================================================
# KEY ROTATION TESTS
# ============================================================================

def test_key_rotation_decrypt_with_fallback(valid_key: bytes, old_key: bytes):
    """Test decrypting data encrypted with old key using fallback."""
    old_encryptor = MappingEncryptor(old_key)
    new_encryptor = MappingEncryptor(
        encryption_key=valid_key,
        fallback_keys=[old_key]
    )
    
    plaintext = "rotated_secret"
    
    # Encrypted with old key
    old_encrypted = old_encryptor.encrypt(plaintext)
    
    # Decrypted with new encryptor (using fallback)
    decrypted = new_encryptor.decrypt(old_encrypted)
    
    assert decrypted == plaintext


def test_key_rotation_encrypt_with_current_key(valid_key: bytes, old_key: bytes):
    """Test encryption always uses current key, not fallbacks."""
    encryptor = MappingEncryptor(
        encryption_key=valid_key,
        fallback_keys=[old_key]
    )
    
    plaintext = "new_data"
    encrypted = encryptor.encrypt(plaintext)
    
    # Should decrypt with current key
    current_only_encryptor = MappingEncryptor(valid_key)
    decrypted = current_only_encryptor.decrypt(encrypted)
    
    assert decrypted == plaintext


def test_multiple_fallback_keys(valid_key: bytes):
    """Test multiple fallback keys for complex rotation scenarios."""
    key1 = os.urandom(32)
    key2 = os.urandom(32)
    key3 = os.urandom(32)
    
    # Data encrypted with first old key
    encryptor1 = MappingEncryptor(key1)
    plaintext = "multi_rotation_test"
    encrypted = encryptor1.encrypt(plaintext)
    
    # New encryptor with multiple fallbacks
    encryptor_new = MappingEncryptor(
        encryption_key=valid_key,
        fallback_keys=[key3, key2, key1]  # Order matters
    )
    
    # Should find key1 in fallbacks
    decrypted = encryptor_new.decrypt(encrypted)
    assert decrypted == plaintext


# ============================================================================
# BATCH OPERATIONS TESTS
# ============================================================================

def test_encrypt_batch(encryptor: MappingEncryptor):
    """Test batch encryption."""
    plaintexts = [
        "email1@example.com",
        "email2@example.com",
        None,
        "email3@example.com",
        ""
    ]
    
    encrypted_batch = encryptor.encrypt_batch(plaintexts)
    
    assert len(encrypted_batch) == len(plaintexts)
    assert encrypted_batch[2] is None  # NULL preserved
    assert encrypted_batch[4] is not None  # Empty string encrypted


def test_decrypt_batch(encryptor: MappingEncryptor):
    """Test batch decryption."""
    plaintexts = [
        "value1",
        "value2",
        None,
        "value3"
    ]
    
    encrypted_batch = encryptor.encrypt_batch(plaintexts)
    decrypted_batch = encryptor.decrypt_batch(encrypted_batch)
    
    assert decrypted_batch == plaintexts


# ============================================================================
# UTILITY FUNCTION TESTS
# ============================================================================

def test_generate_encryption_key():
    """Test key generation utility."""
    key = generate_encryption_key()
    
    assert isinstance(key, str)
    assert len(key) > 0
    
    # Should be valid base64
    key_bytes = base64.b64decode(key)
    assert len(key_bytes) == 32  # 256 bits


def test_validate_encryption_key_valid(valid_key_b64):
    """Test key validation with valid key."""
    assert validate_encryption_key(valid_key_b64) is True


def test_validate_encryption_key_invalid():
    """Test key validation with invalid keys."""
    assert validate_encryption_key("short") is False
    assert validate_encryption_key("not_base64!!!") is False
    assert validate_encryption_key("") is False


def test_validate_encryption_key_wrong_length():
    """Test key validation with wrong length."""
    short_key = base64.b64encode(os.urandom(16)).decode('ascii')
    assert validate_encryption_key(short_key) is False


# ============================================================================
# REPR TESTS
# ============================================================================

def test_repr(encryptor: MappingEncryptor):
    """Test string representation."""
    repr_str = repr(encryptor)
    
    assert "MappingEncryptor" in repr_str
    assert "key_id" in repr_str
    assert "fallback_keys=0" in repr_str


def test_repr_with_fallbacks(valid_key: bytes, old_key: bytes):
    """Test string representation with fallback keys."""
    encryptor = MappingEncryptor(
        encryption_key=valid_key,
        fallback_keys=[old_key],
        key_id="production"
    )
    
    repr_str = repr(encryptor)
    
    assert "production" in repr_str
    assert "fallback_keys=1" in repr_str


# ============================================================================
# EDGE CASES
# ============================================================================

def test_encrypt_special_characters(encryptor: MappingEncryptor):
    """Test encryption of special characters that might break encoding."""
    special_chars = [
        "user@example.com\n\r\t",
        "test'with\"quotes",
        "back\\slash",
        "null\x00byte"
    ]
    
    for plaintext in special_chars:
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        assert decrypted == plaintext, f"Failed for: {repr(plaintext)}"


def test_fallback_key_wrong_type(valid_key: bytes):
    """Test fallback key validation."""
    with pytest.raises(KeyManagementError) as exc_info:
        MappingEncryptor(
            encryption_key=valid_key,
            fallback_keys=["not_bytes"]
        )
    
    assert "Fallback key" in str(exc_info.value)
    assert "must be bytes" in str(exc_info.value)


def test_fallback_key_wrong_length(valid_key: bytes):
    """Test fallback key length validation."""
    with pytest.raises(KeyManagementError) as exc_info:
        MappingEncryptor(
            encryption_key=valid_key,
            fallback_keys=[os.urandom(16)]  # Wrong length
        )
    
    assert "Fallback key" in str(exc_info.value)
    assert "32 bytes" in str(exc_info.value)
