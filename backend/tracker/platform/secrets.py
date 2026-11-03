"""API keys the user saves, sealed before they reach the database.

A key saved in Settings (the price feed's, a cloud or local model's) is stored
as `sealed:v1:<Fernet token>`. The Fernet key lives in a file of its own,
`~/.roleband/secret.key` (`ROLEBAND_SECRET_KEY_FILE` names another), readable by
its owner only and outside `data/`, so a database dump or a backup copied
elsewhere holds ciphertext, not the key.

A value without the prefix is a key saved before sealing existed: it reads as
itself, and the next save seals it (`scripts.seal_secrets` seals them all at
once). A sealed value this machine cannot open (the key file is missing or is
another machine's) raises `SecretUnavailable`; the stores read it as no key at
all, so the user is asked to enter it again rather than shown an error.
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "sealed:v1:"
KEY_FILE_ENV = "ROLEBAND_SECRET_KEY_FILE"

logger = logging.getLogger(__name__)


class SecretUnavailable(Exception):
    """A sealed value that the key file on this machine does not open."""


def key_path() -> Path:
    override = os.environ.get(KEY_FILE_ENV)
    return Path(override).expanduser() if override else Path.home() / ".roleband" / "secret.key"


def is_sealed(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def _read_key(path: Path) -> bytes | None:
    try:
        key = path.read_bytes().strip()
    except FileNotFoundError:
        return None
    try:
        valid = len(base64.urlsafe_b64decode(key)) == 32
    except ValueError:
        valid = False
    if not valid:
        raise SecretUnavailable(f"{path} does not hold a Fernet key")
    return key


def _create_key(path: Path) -> bytes:
    """Write a new key, or read the one another process wrote first.

    The key reaches its name by `link`, which fails if the name exists, so two
    processes saving their first key at once agree on one: the loser reads the
    winner's, and no reader ever sees a half-written file."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".secret-key-")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, key + b"\n")
        os.fsync(fd)
        os.close(fd)
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = _read_key(path)
            if existing is None:
                raise
            return existing
        return key
    finally:
        os.unlink(temp)


def seal(value: str | None) -> str | None:
    """The value to store for `value`; empty and already sealed values pass."""
    if not value or is_sealed(value):
        return value
    path = key_path()
    key = _read_key(path) or _create_key(path)
    return PREFIX + Fernet(key).encrypt(value.encode()).decode()


def unseal(value: str | None) -> str | None:
    """The key a stored value holds. Raises `SecretUnavailable` for a sealed
    value the key file here does not open."""
    if not is_sealed(value):
        return value
    assert value is not None
    key = _read_key(key_path())
    if key is None:
        raise SecretUnavailable(f"no key file at {key_path()}")
    try:
        return Fernet(key).decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as error:
        raise SecretUnavailable("the key file here did not seal this value") from error


def unseal_or_none(value: str | None) -> str | None:
    """`unseal`, reading a value this machine cannot open as no key."""
    try:
        return unseal(value)
    except SecretUnavailable as error:
        logger.warning("a saved API key cannot be read here (%s); it reads as not set", error)
        return None
