"""Trusted dependency-environment bootstrap (container-side).

Factory-owned. Mounted read-only into bootstrap containers.
Creates / refreshes a Linux venv at the volume mount root
using stdlib only — no shell.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import venv

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows host never runs this
    fcntl = None  # type: ignore[assignment]


ENV_DIR = "/opt/ai-factory/venv"
LOCK_NAME = ".ai-factory-bootstrap.lock"
READY_NAME = ".ai-factory-ready.json"
SCHEMA_VERSION = 1


def _python_mm() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _lock_path() -> str:
    return os.path.join(ENV_DIR, LOCK_NAME)


def _ready_path() -> str:
    return os.path.join(ENV_DIR, READY_NAME)


def _python_bin() -> str:
    return os.path.join(ENV_DIR, "bin", "python")


def _read_ready() -> dict | None:
    path = _ready_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _is_complete() -> bool:
    marker = _read_ready()
    if marker is None:
        return False
    if marker.get("schema_version") != SCHEMA_VERSION:
        return False
    if marker.get("python") != _python_mm():
        return False
    return os.path.isfile(_python_bin())


def _clear_except_lock() -> None:
    lock = LOCK_NAME
    if not os.path.isdir(ENV_DIR):
        os.makedirs(ENV_DIR, exist_ok=True)
        return
    for name in os.listdir(ENV_DIR):
        if name == lock:
            continue
        path = os.path.join(ENV_DIR, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            try:
                os.unlink(path)
            except IsADirectoryError:
                shutil.rmtree(path)


def _write_ready_atomic() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "python": _python_mm(),
    }
    os.makedirs(ENV_DIR, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".ai-factory-ready.",
        dir=ENV_DIR,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, _ready_path())
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _create_venv() -> None:
    _clear_except_lock()
    builder = venv.EnvBuilder(with_pip=True, clear=False)
    builder.create(ENV_DIR)
    if not os.path.isfile(_python_bin()):
        raise RuntimeError(
            "venv create completed but bin/python missing"
        )
    _write_ready_atomic()


def main() -> int:
    if fcntl is None:
        print(
            "bootstrap: fcntl unavailable "
            "(must run in Linux container)",
            file=sys.stderr,
        )
        return 2

    os.makedirs(ENV_DIR, exist_ok=True)
    lock_path = _lock_path()
    lock_fd = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT,
        0o644,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if _is_complete():
            return 0
        try:
            _create_venv()
        except Exception as exc:
            print(
                f"bootstrap: venv create failed: {exc}",
                file=sys.stderr,
            )
            return 1
        if not _is_complete():
            print(
                "bootstrap: environment incomplete "
                "after create",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
