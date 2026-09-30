"""Persistent TaskCommandSandbox Python dependency environments.

Linux-native virtualenv stored in a Docker named volume.
Independent of WRITE DockerSandbox and host Windows venvs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import hashlib
import os
import re
import subprocess

from factory.task_command_models import (
    TaskCommandPolicyError,
    TaskCommandSandboxRuntimeError,
    TaskCommandValidationError,
)


CONTAINER_VENV_ROOT = "/opt/ai-factory/venv"
CONTAINER_VENV_PYTHON = f"{CONTAINER_VENV_ROOT}/bin/python"
BOOTSTRAP_CONTAINER_PATH = (
    "/opt/ai-factory/task_command_dependency_bootstrap.py"
)
VOLUME_NAME_PREFIX = "ai-factory-pyenv-"
VOLUME_HASH_HEX_LEN = 24
_VOLUME_NAME_RE = re.compile(
    rf"^{re.escape(VOLUME_NAME_PREFIX)}[0-9a-f]{{{VOLUME_HASH_HEX_LEN}}}$"
)

MAX_REQUIREMENTS_FILE_BYTES = 256_000
MAX_REQUIREMENTS_PACKAGES = 200

# Default image — same as task command sandbox.
DEFAULT_TASK_COMMAND_IMAGE = os.environ.get(
    "AI_FACTORY_TASK_COMMAND_IMAGE",
    "ai-factory-python-test",
)

SANDBOX_PIDS_LIMIT = "256"
SANDBOX_MEMORY = "1g"
SANDBOX_CPUS = "1"

# Conservative PEP 503-ish name + optional exact ==version.
_SAFE_PACKAGE_SPEC = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?"
    r"(==[A-Za-z0-9]([A-Za-z0-9._+-]*[A-Za-z0-9])?)?$"
)

_REJECT_INSTALL_FLAGS = frozenset(
    {
        "--target",
        "--prefix",
        "--root",
        "--user",
        "--index-url",
        "-i",
        "--extra-index-url",
        "--find-links",
        "-f",
        "--no-index",
        "--editable",
        "-e",
    }
)

_VCS_OR_URL_PREFIXES = (
    "git+",
    "svn+",
    "hg+",
    "bzr+",
    "http://",
    "https://",
    "file://",
    "ssh://",
    "git@",
)


def bootstrap_host_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "task_command_dependency_bootstrap.py"
    )


def normalize_project_root(
    project_root: str | Path,
) -> str:
    return (
        Path(project_root)
        .expanduser()
        .resolve()
        .as_posix()
        .casefold()
    )


def normalize_task_id(task_id: str) -> str:
    value = str(task_id or "").strip()
    if not value:
        raise TaskCommandValidationError(
            "task_id bos olamaz."
        )
    return value.casefold()


def dependency_environment_id(
    *,
    project_root: str | Path,
    task_id: str,
) -> str:
    """Opaque SHA-256 identity (full hex)."""
    material = (
        f"{normalize_project_root(project_root)}"
        f"\0"
        f"{normalize_task_id(task_id)}"
    )
    return hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def dependency_environment_name(
    *,
    project_root: str | Path,
    task_id: str,
) -> str:
    digest = dependency_environment_id(
        project_root=project_root,
        task_id=task_id,
    )
    return (
        f"{VOLUME_NAME_PREFIX}"
        f"{digest[:VOLUME_HASH_HEX_LEN]}"
    )


def validate_dependency_volume_name(
    volume_name: str,
) -> str:
    """Accept only factory-generated dependency volume names."""
    if not isinstance(volume_name, str):
        raise TaskCommandValidationError(
            "dependency volume name string olmali."
        )
    if not _VOLUME_NAME_RE.fullmatch(volume_name):
        raise TaskCommandValidationError(
            "Gecersiz dependency volume name. "
            "Yalnizca ai-factory-pyenv-<24 hex> "
            "kabul edilir."
        )
    return volume_name


def build_docker_cli_env(
    host_environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Minimal host env for the docker CLI only."""
    host = (
        host_environ
        if host_environ is not None
        else dict(os.environ)
    )
    allow = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "DOCKER_HOST",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
    }
    by_fold = {
        key.casefold(): (key, value)
        for key, value in host.items()
    }
    result: dict[str, str] = {}
    for name in allow:
        hit = by_fold.get(name.casefold())
        if hit is not None:
            result[hit[0]] = hit[1]
    return result


def build_volume_create_argv(volume_name: str) -> list[str]:
    validate_dependency_volume_name(volume_name)
    return ["docker", "volume", "create", volume_name]


def build_volume_rm_argv(volume_name: str) -> list[str]:
    validate_dependency_volume_name(volume_name)
    return ["docker", "volume", "rm", volume_name]


def build_volume_inspect_argv(volume_name: str) -> list[str]:
    validate_dependency_volume_name(volume_name)
    return ["docker", "volume", "inspect", volume_name]


def build_bootstrap_docker_argv(
    *,
    volume_name: str,
    container_name: str,
    image_name: str = DEFAULT_TASK_COMMAND_IMAGE,
    bootstrap_path: Path | None = None,
) -> list[str]:
    validate_dependency_volume_name(volume_name)
    bootstrap = (
        bootstrap_path
        if bootstrap_path is not None
        else bootstrap_host_path()
    ).resolve()
    if not bootstrap.is_file():
        raise TaskCommandSandboxRuntimeError(
            f"Dependency bootstrap bulunamadi: {bootstrap}"
        )

    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        SANDBOX_PIDS_LIMIT,
        "--memory",
        SANDBOX_MEMORY,
        "--cpus",
        SANDBOX_CPUS,
        "-v",
        f"{volume_name}:{CONTAINER_VENV_ROOT}",
        "-v",
        f"{bootstrap}:{BOOTSTRAP_CONTAINER_PATH}:ro",
        image_name,
        "python",
        BOOTSTRAP_CONTAINER_PATH,
    ]


def _force_remove_bootstrap_container(
    container_name: str,
    *,
    docker_env: dict[str, str],
) -> None:
    try:
        subprocess.run(
            [
                "docker",
                "rm",
                "-f",
                container_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
            check=False,
            timeout=30,
            env=docker_env,
        )
    except Exception:
        # Cleanup must not replace the primary timeout error.
        return


def create_dependency_volume(
    volume_name: str,
    *,
    host_environ: dict[str, str] | None = None,
) -> None:
    argv = build_volume_create_argv(volume_name)
    docker_env = build_docker_cli_env(host_environ)
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=60,
            env=docker_env,
        )
    except FileNotFoundError as exc:
        raise TaskCommandSandboxRuntimeError(
            "Docker is not installed or not found "
            "in system PATH."
        ) from exc

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        # Idempotent: already exists is OK.
        lowered = err.casefold()
        if "already exists" in lowered:
            return
        raise TaskCommandSandboxRuntimeError(
            "Docker volume create basarisiz: "
            f"{err or completed.returncode}"
        )


def ensure_dependency_environment(
    *,
    project_root: str | Path,
    task_id: str,
    image_name: str = DEFAULT_TASK_COMMAND_IMAGE,
    host_environ: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> str:
    """Create volume + bootstrap Linux venv. Returns volume name."""
    volume_name = dependency_environment_name(
        project_root=project_root,
        task_id=task_id,
    )
    create_dependency_volume(
        volume_name,
        host_environ=host_environ,
    )

    container_name = (
        f"ai-factory-depboot-{uuid4().hex[:12]}"
    )
    argv = build_bootstrap_docker_argv(
        volume_name=volume_name,
        container_name=container_name,
        image_name=image_name,
    )
    if "sh" in argv and "-c" in argv:
        raise TaskCommandSandboxRuntimeError(
            "Bootstrap docker argv shell wrapper iceremez."
        )

    docker_env = build_docker_cli_env(host_environ)
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=timeout_seconds,
            env=docker_env,
        )
    except FileNotFoundError as exc:
        raise TaskCommandSandboxRuntimeError(
            "Docker is not installed or not found "
            "in system PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        _force_remove_bootstrap_container(
            container_name,
            docker_env=docker_env,
        )
        raise TaskCommandSandboxRuntimeError(
            "Dependency environment bootstrap timed out."
        ) from exc

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise TaskCommandSandboxRuntimeError(
            "Dependency environment bootstrap failed: "
            f"{err or completed.returncode}"
        )

    return volume_name


def remove_dependency_environment(
    *,
    project_root: str | Path | None = None,
    task_id: str | None = None,
    volume_name: str | None = None,
    host_environ: dict[str, str] | None = None,
) -> None:
    """Idempotent docker volume rm."""
    if volume_name is None:
        if project_root is None or task_id is None:
            raise TaskCommandValidationError(
                "volume_name veya project_root+task_id gerekli."
            )
        volume_name = dependency_environment_name(
            project_root=project_root,
            task_id=task_id,
        )
    else:
        validate_dependency_volume_name(volume_name)

    argv = build_volume_rm_argv(volume_name)
    docker_env = build_docker_cli_env(host_environ)
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=60,
            env=docker_env,
        )
    except FileNotFoundError as exc:
        raise TaskCommandSandboxRuntimeError(
            "Docker is not installed or not found "
            "in system PATH."
        ) from exc

    if completed.returncode == 0:
        return

    err = (completed.stderr or completed.stdout or "").strip()
    lowered = err.casefold()
    if (
        "no such volume" in lowered
        or "not found" in lowered
    ):
        return

    raise TaskCommandSandboxRuntimeError(
        "Docker volume rm basarisiz: "
        f"{err or completed.returncode}"
    )


@dataclass(frozen=True)
class DependencyEnvironmentInspection:
    volume_name: str
    exists: bool
    raw: str = ""


def inspect_dependency_environment(
    *,
    project_root: str | Path | None = None,
    task_id: str | None = None,
    volume_name: str | None = None,
    host_environ: dict[str, str] | None = None,
) -> DependencyEnvironmentInspection:
    if volume_name is None:
        if project_root is None or task_id is None:
            raise TaskCommandValidationError(
                "volume_name veya project_root+task_id gerekli."
            )
        volume_name = dependency_environment_name(
            project_root=project_root,
            task_id=task_id,
        )
    else:
        validate_dependency_volume_name(volume_name)

    argv = build_volume_inspect_argv(volume_name)
    docker_env = build_docker_cli_env(host_environ)
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=60,
            env=docker_env,
        )
    except FileNotFoundError as exc:
        raise TaskCommandSandboxRuntimeError(
            "Docker is not installed or not found "
            "in system PATH."
        ) from exc

    if completed.returncode != 0:
        return DependencyEnvironmentInspection(
            volume_name=volume_name,
            exists=False,
            raw=(completed.stderr or "").strip(),
        )

    return DependencyEnvironmentInspection(
        volume_name=volume_name,
        exists=True,
        raw=(completed.stdout or "").strip(),
    )


def trusted_pip_install_env() -> dict[str, str]:
    """Factory-controlled env for package installs (no caller env)."""
    return {
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PIP_CONFIG_FILE": "/dev/null",
    }


def _is_vcs_or_url(token: str) -> bool:
    folded = token.casefold()
    return any(
        folded.startswith(prefix)
        for prefix in _VCS_OR_URL_PREFIXES
    )


def _is_safe_package_spec(token: str) -> bool:
    if not token or len(token) > 200:
        return False
    if _is_vcs_or_url(token):
        return False
    if "/" in token or "\\" in token:
        return False
    if token in {".", ".."}:
        return False
    return bool(_SAFE_PACKAGE_SPEC.fullmatch(token))


def _requirements_path_allowed(
    *,
    project_root: Path,
    raw: str,
) -> Path:
    """Resolve -r path against project_root only (not cwd)."""
    root = project_root.resolve()
    candidate_input = Path(raw)
    if candidate_input.is_absolute():
        raise TaskCommandPolicyError(
            "pip -r absolute path V1'de reddedilir."
        )
    if ".." in candidate_input.parts:
        raise TaskCommandPolicyError(
            "pip -r proje disina cikan path reddedilir."
        )
    resolved = (root / candidate_input).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise TaskCommandPolicyError(
            "pip -r proje kokunun disina cikamaz."
        ) from exc
    if not resolved.is_file():
        raise TaskCommandPolicyError(
            f"requirements dosyasi bulunamadi: {raw}"
        )
    return resolved


def load_safe_requirements_packages(
    requirements_path: Path,
) -> list[str]:
    """Host-side V1 requirements sanitizer.

    Accepts only blank lines, # comments, and safe
    package specs. Never lets pip read the file.
    """
    try:
        size = requirements_path.stat().st_size
    except OSError as exc:
        raise TaskCommandPolicyError(
            f"requirements dosyasi okunamadi: {exc}"
        ) from exc

    if size > MAX_REQUIREMENTS_FILE_BYTES:
        raise TaskCommandPolicyError(
            "requirements dosyasi cok buyuk."
        )

    try:
        raw = requirements_path.read_bytes()
    except OSError as exc:
        raise TaskCommandPolicyError(
            f"requirements dosyasi okunamadi: {exc}"
        ) from exc

    if raw.startswith(b"\xff\xfe") or raw.startswith(
        b"\xfe\xff"
    ):
        raise TaskCommandPolicyError(
            "requirements yalnizca UTF-8/UTF-8-SIG olabilir."
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TaskCommandPolicyError(
            "requirements UTF-8 olarak cozumlenemedi."
        ) from exc

    packages: list[str] = []
    for line in text.splitlines():
        if "\\" in line:
            raise TaskCommandPolicyError(
                "requirements satir devamı (\\) V1'de "
                "reddedilir."
            )
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if (
            ";" in stripped
            or "$" in stripped
            or "{" in stripped
            or "}" in stripped
        ):
            raise TaskCommandPolicyError(
                "requirements environment marker / "
                "degisken V1'de reddedilir."
            )
        if stripped.startswith("-"):
            raise TaskCommandPolicyError(
                "requirements pip direktifi V1'de "
                f"reddedilir: {stripped}"
            )
        if not _is_safe_package_spec(stripped):
            raise TaskCommandPolicyError(
                "requirements paket spesifikasyonu "
                f"guvenli degil: {stripped}"
            )
        packages.append(stripped)
        if len(packages) > MAX_REQUIREMENTS_PACKAGES:
            raise TaskCommandPolicyError(
                "requirements cok fazla paket iceriyor."
            )

    if not packages:
        raise TaskCommandPolicyError(
            "requirements en az bir guvenli paket "
            "icermelidir."
        )

    return packages


def extract_pip_install_args(
    executable: str,
    args: list[str],
) -> list[str] | None:
    """Return pip args after 'install', or None if not pip install."""
    name = Path(executable).name.casefold()

    if name.startswith("pip"):
        lowered = [a.casefold() for a in args]
        if "install" not in lowered:
            return None
        idx = lowered.index("install")
        return list(args[idx + 1 :])

    if name.startswith("python") or name in {
        "py",
        "py.exe",
    }:
        if (
            len(args) >= 3
            and args[0].casefold() == "-m"
            and args[1].casefold() == "pip"
        ):
            pip_args = args[2:]
            lowered = [a.casefold() for a in pip_args]
            if "install" not in lowered:
                return None
            idx = lowered.index("install")
            return list(pip_args[idx + 1 :])

    return None


def prepare_package_install_argv(
    *,
    project_root: Path,
    executable: str,
    args: list[str],
) -> list[str]:
    """Validate install argv and expand -r into package specs.

    Returns rewritten ``args`` (not including executable).
    Pip never reads the original requirements file.
    """
    install_args = extract_pip_install_args(
        executable,
        args,
    )
    if install_args is None:
        raise TaskCommandPolicyError(
            "NETWORK_PACKAGE_INSTALL yalnizca pip install "
            "icin desteklenir."
        )

    if not install_args:
        raise TaskCommandPolicyError(
            "pip install en az bir paket veya -r gerektirir."
        )

    name = Path(executable).name.casefold()
    is_python_m_pip = (
        name.startswith("python")
        or name in {"py", "py.exe"}
    ) and (
        len(args) >= 2
        and args[0].casefold() == "-m"
        and args[1].casefold() == "pip"
    )

    rebuilt_install: list[str] = []
    index = 0
    saw_requirement = False

    while index < len(install_args):
        token = install_args[index]
        folded = token.casefold()

        if folded in {"-r"}:
            if index + 1 >= len(install_args):
                raise TaskCommandPolicyError(
                    "pip install -r dosya yolu gerektirir."
                )
            req_path = install_args[index + 1]
            if req_path.casefold().startswith("-"):
                raise TaskCommandPolicyError(
                    "pip install -r dosya yolu gerektirir."
                )
            resolved = _requirements_path_allowed(
                project_root=project_root,
                raw=req_path,
            )
            packages = load_safe_requirements_packages(
                resolved
            )
            rebuilt_install.extend(packages)
            saw_requirement = True
            index += 2
            continue

        if folded in _REJECT_INSTALL_FLAGS:
            raise TaskCommandPolicyError(
                f"pip install bayragi V1'de reddedilir: {token}"
            )

        if folded.startswith("-"):
            if folded in {
                "--no-cache-dir",
                "--upgrade",
                "-u",
            }:
                rebuilt_install.append(token)
                index += 1
                continue
            raise TaskCommandPolicyError(
                f"pip install bayragi V1'de reddedilir: {token}"
            )

        if _is_vcs_or_url(token):
            raise TaskCommandPolicyError(
                f"pip URL/VCS kaynagi V1'de reddedilir: {token}"
            )

        if token in {".", ".."} or token.startswith("."):
            raise TaskCommandPolicyError(
                "pip yerel path/editable V1'de "
                f"reddedilir: {token}"
            )

        if "/" in token or "\\" in token:
            raise TaskCommandPolicyError(
                f"pip path kaynagi V1'de reddedilir: {token}"
            )

        if not _is_safe_package_spec(token):
            raise TaskCommandPolicyError(
                "pip paket spesifikasyonu guvenli degil: "
                f"{token}"
            )

        rebuilt_install.append(token)
        saw_requirement = True
        index += 1

    if not saw_requirement:
        raise TaskCommandPolicyError(
            "pip install en az bir paket veya -r gerektirir."
        )

    if is_python_m_pip:
        return ["-m", "pip", "install", *rebuilt_install]

    # bare pip / pip.exe
    return ["install", *rebuilt_install]


def validate_package_install_argv(
    *,
    project_root: Path,
    executable: str,
    args: list[str],
) -> None:
    """Fail-closed V1 validator for NETWORK_PACKAGE_INSTALL argv."""
    prepare_package_install_argv(
        project_root=project_root,
        executable=executable,
        args=args,
    )


def uses_python_dependency_environment(
    executable: str,
) -> bool:
    name = Path(executable).name.casefold()
    if name.startswith("python") or name in {
        "py",
        "py.exe",
    }:
        return True
    if name.startswith("pip"):
        return True
    if name in {"pytest", "pytest.exe"}:
        return True
    return False
