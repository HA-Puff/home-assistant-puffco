"""Auth token tests using README example vectors."""

from hashlib import sha256

import pytest

from puffco_ble.auth import (
    create_auth_token,
    create_flat_auth_token,
    create_lorax_auth_token,
    create_lorax_auth_token_seed_only,
)
from puffco_ble.constants import DEVICE_HANDSHAKE2_KEY, DEVICE_HANDSHAKE_KEY

README_SEED = bytes(
    [42, 45, 124, 169, 105, 200, 18, 27, 188, 123, 188, 171, 2, 237, 37, 19]
)


def _reference_token(seed: bytes, handshake: bytes) -> bytearray:
    new_key = bytearray(32)
    for i in range(16):
        new_key[i] = handshake[i]
        new_key[i + 16] = seed[i]
    digested = sha256(new_key).hexdigest()
    return bytearray(int(digested[i : i + 2], 16) for i in range(0, 32, 2))


def test_flat_auth_matches_reference_implementation():
    expected = _reference_token(README_SEED, DEVICE_HANDSHAKE_KEY)
    assert create_flat_auth_token(README_SEED) == expected
    assert create_auth_token(README_SEED, DEVICE_HANDSHAKE_KEY) == expected


def test_lorax_auth_uses_handshake2():
    expected = _reference_token(README_SEED, DEVICE_HANDSHAKE2_KEY)
    assert create_lorax_auth_token(README_SEED) == expected


def test_lorax_seed_only_auth():
    new_key = bytearray(32)
    for i in range(16):
        new_key[i + 16] = README_SEED[i]
    digested = sha256(new_key).hexdigest()
    expected = bytearray(int(digested[i : i + 2], 16) for i in range(0, 32, 2))
    assert create_lorax_auth_token_seed_only(README_SEED) == expected


def test_auth_token_length():
    assert len(create_flat_auth_token(README_SEED)) == 16
