"""Exercise the exact defects addressed by the reviewed dependency updates."""

import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def test_recursive_unsigned_payload_raises_the_documented_token_error():
    header = jwt.utils.base64url_encode(json.dumps({"alg": "HS256"}).encode())
    payload = jwt.utils.base64url_encode(b"[" * 20000 + b"]" * 20000)
    token = b".".join([header, payload, b"Zm9yZ2Vk"])
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(token, options={"verify_signature": False})


def test_okp_private_jwk_rejects_a_different_declared_public_identity():
    # Fixed synthetic fixture keys have no accounts, grants or authentication use.
    first = Ed25519PrivateKey.from_private_bytes(bytes(32))
    second = Ed25519PrivateKey.from_private_bytes(bytes([1]) * 32)
    jwk = {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": jwt.utils.base64url_encode(first.public_key().public_bytes_raw()).decode(),
        "d": jwt.utils.base64url_encode(second.private_bytes_raw()).decode(),
    }
    with pytest.raises(jwt.InvalidKeyError):
        jwt.PyJWK.from_dict(jwk)
