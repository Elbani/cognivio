"""JWT_SECRET_FILE: the secret a single-machine install creates on first start."""
from __future__ import annotations

import os
import stat

import pytest

from app.core.config import load_or_create_secret


def test_creates_a_secret_on_first_start(tmp_path):
    path = tmp_path / "data" / "jwt_secret"
    secret = load_or_create_secret(str(path))
    assert len(secret) == 64
    assert path.read_text().strip() == secret
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_returns_the_same_secret_on_later_starts(tmp_path):
    path = tmp_path / "jwt_secret"
    first = load_or_create_secret(str(path))
    assert load_or_create_secret(str(path)) == first
    assert load_or_create_secret(str(path)) == first


def test_two_files_get_different_secrets(tmp_path):
    assert load_or_create_secret(str(tmp_path / "a")) != load_or_create_secret(str(tmp_path / "b"))


def test_keeps_a_secret_someone_put_there(tmp_path):
    path = tmp_path / "jwt_secret"
    path.write_text("x" * 40 + "\n")
    assert load_or_create_secret(str(path)) == "x" * 40


def test_fills_an_empty_file(tmp_path):
    path = tmp_path / "jwt_secret"
    path.write_text("")
    secret = load_or_create_secret(str(path))
    assert len(secret) == 64
    assert path.read_text().strip() == secret


def test_refuses_a_short_secret_and_leaves_it_alone(tmp_path):
    path = tmp_path / "jwt_secret"
    path.write_text("too-short")
    with pytest.raises(RuntimeError, match="shorter than 32"):
        load_or_create_secret(str(path))
    assert path.read_text() == "too-short"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_says_so_when_the_directory_is_not_writable(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(RuntimeError, match="Could not write JWT_SECRET_FILE"):
            load_or_create_secret(str(locked / "jwt_secret"))
    finally:
        locked.chmod(0o700)
