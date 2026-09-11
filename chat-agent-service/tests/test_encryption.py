import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core import encryption
from app.core.config import settings


@pytest.fixture(autouse=True)
def setup_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", key)
    encryption._fernet.cache_clear()
    yield
    encryption._fernet.cache_clear()


def test_encryption_roundtrip():
    original = "ya29.a0AfH6SMD_sample_oauth_token_12345"
    encrypted = encryption.encrypt_str(original)

    assert encrypted != original
    decrypted = encryption.decrypt_str(encrypted)
    assert decrypted == original


def test_decrypt_tampered_ciphertext_raises():
    original = "secret_token_abc"
    encrypted = encryption.encrypt_str(original)

    # Tamper with the ciphertext
    tampered = encrypted[:-4] + ("AAAA" if not encrypted.endswith("AAAA") else "BBBB")
    with pytest.raises(InvalidToken):
        encryption.decrypt_str(tampered)


def test_missing_encryption_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", None)
    encryption._fernet.cache_clear()

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY is not set"):
        encryption.encrypt_str("test")
