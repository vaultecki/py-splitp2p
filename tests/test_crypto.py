from dataclasses import dataclass

import crypto
from models import Expense


@dataclass
class FakeRecord:
    payload: str
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        return self.payload.encode()


def test_generate_and_roundtrip_private_key():
    key = crypto.generate_private_key()
    raw = crypto.private_key_to_bytes(key)
    restored = crypto.private_key_from_bytes(raw)
    assert crypto.get_public_key_hex(restored) == crypto.get_public_key_hex(key)


def test_sign_and_verify_record_roundtrip():
    key = crypto.generate_private_key()
    pubkey_hex = crypto.get_public_key_hex(key)
    record = FakeRecord(payload="hello world")
    record.signature = crypto.sign_record(record, key)
    assert crypto.verify_record(record, pubkey_hex)


def test_verify_fails_on_tampered_data():
    key = crypto.generate_private_key()
    pubkey_hex = crypto.get_public_key_hex(key)
    record = FakeRecord(payload="hello world")
    record.signature = crypto.sign_record(record, key)
    record.payload = "tampered"
    assert not crypto.verify_record(record, pubkey_hex)


def test_verify_fails_with_wrong_key():
    key = crypto.generate_private_key()
    other_pubkey_hex = crypto.get_public_key_hex(crypto.generate_private_key())
    record = FakeRecord(payload="hello world")
    record.signature = crypto.sign_record(record, key)
    assert not crypto.verify_record(record, other_pubkey_hex)


def test_verify_fails_on_missing_signature():
    record = FakeRecord(payload="hello world", signature="")
    assert not crypto.verify_record(record, "deadbeef")


def test_verify_expense_uses_author_pubkey():
    key = crypto.generate_private_key()
    pubkey_hex = crypto.get_public_key_hex(key)
    exp = Expense.create(group_id="g1", description="Dinner", amount=1000, author_pubkey=pubkey_hex)
    exp.signature = crypto.sign_expense(exp, key)
    assert crypto.verify_expense(exp)


def test_encrypt_decrypt_record_roundtrip():
    group_key = crypto.generate_group_key()
    key = crypto.generate_private_key()
    exp = Expense.create(
        group_id="g1",
        description="Taxi",
        amount=2500,
        author_pubkey=crypto.get_public_key_hex(key),
    )
    blob = crypto.encrypt_record(exp, group_key)
    restored = crypto.decrypt_record(blob, group_key, Expense)
    assert restored is not None
    assert restored.description == "Taxi"
    assert restored.amount == 2500


def test_decrypt_record_returns_none_with_wrong_key():
    group_key = crypto.generate_group_key()
    wrong_key = crypto.generate_group_key()
    key = crypto.generate_private_key()
    exp = Expense.create(
        group_id="g1", description="Taxi", amount=2500, author_pubkey=crypto.get_public_key_hex(key)
    )
    blob = crypto.encrypt_record(exp, group_key)
    assert crypto.decrypt_record(blob, wrong_key, Expense) is None


def test_encrypt_decrypt_chunk_roundtrip():
    group_key = crypto.generate_group_key()
    data = b"some file bytes here"
    blob = crypto.encrypt_chunk(data, group_key)
    assert crypto.decrypt_chunk(blob, group_key) == data


def test_hash_bytes_is_sha256_hex():
    import hashlib

    data = b"hello"
    assert crypto.hash_bytes(data) == hashlib.sha256(data).hexdigest()


def test_mime_type_from_path():
    assert crypto.mime_type_from_path("photo.PNG") == "image/png"
    assert crypto.mime_type_from_path("doc.pdf") == "application/pdf"
    assert crypto.mime_type_from_path("archive.zip") == "application/octet-stream"
