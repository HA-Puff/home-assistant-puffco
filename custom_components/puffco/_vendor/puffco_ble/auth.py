"""Firmware X authentication helpers."""

from hashlib import sha256

from puffco_ble.constants import DEVICE_HANDSHAKE2_KEY, DEVICE_HANDSHAKE_KEY


def create_auth_token(
    access_seed: bytes | bytearray | list[int],
    handshake_key: bytes | bytearray = DEVICE_HANDSHAKE_KEY,
) -> bytearray:
    """Create a 16-byte auth token from seed + handshake (Flat / Lorax unlock)."""
    new_key = bytearray(32)
    seed = bytes(access_seed)
    for i in range(16):
        new_key[i] = handshake_key[i]
        new_key[i + 16] = seed[i]
    digested = sha256(new_key).hexdigest()
    return bytearray(int(digested[i : i + 2], 16) for i in range(0, 32, 2))


def create_lorax_auth_token_seed_only(
    access_seed: bytes | bytearray | list[int],
) -> bytearray:
    """Alternate Lorax auth: seed in last 16 bytes only (per app bundle)."""
    new_key = bytearray(32)
    seed = bytes(access_seed)
    for i in range(16):
        new_key[i + 16] = seed[i]
    digested = sha256(new_key).hexdigest()
    return bytearray(int(digested[i : i + 2], 16) for i in range(0, 32, 2))


def create_flat_auth_token(access_seed: bytes | bytearray | list[int]) -> bytearray:
    return create_auth_token(access_seed, DEVICE_HANDSHAKE_KEY)


def create_lorax_auth_token(access_seed: bytes | bytearray | list[int]) -> bytearray:
    return create_auth_token(access_seed, DEVICE_HANDSHAKE2_KEY)
