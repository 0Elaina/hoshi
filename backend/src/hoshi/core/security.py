from functools import lru_cache

from pwdlib import PasswordHash


@lru_cache(maxsize=1)
def get_password_encoder() -> PasswordHash:
    return PasswordHash.recommended()


@lru_cache(maxsize=1)
def get_dummy_hash() -> str:
    return get_password_encoder().hash("dummy")
