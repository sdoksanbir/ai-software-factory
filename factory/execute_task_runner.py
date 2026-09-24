from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

from factory.task_router import normalize_text


class ExecuteTaskError(RuntimeError):
    pass


def _virtualenv_name(prompt: str) -> str:
    raw = prompt.casefold()

    if ".venv" in raw:
        return ".venv"

    if "venv" in normalize_text(prompt):
        return "venv"

    return ".venv"


def _ensure_local_git_exclude(
    project_root: Path,
    env_name: str,
) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        return

    raw_git_dir = completed.stdout.strip()
    if not raw_git_dir:
        return

    git_dir = Path(raw_git_dir)
    if not git_dir.is_absolute():
        git_dir = (project_root / git_dir).resolve()

    exclude_file = git_dir / "info" / "exclude"
    exclude_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    ignore_line = f"/{env_name}/"

    existing = (
        exclude_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
        if exclude_file.exists()
        else ""
    )

    lines = {
        line.strip()
        for line in existing.splitlines()
        if line.strip()
    }

    if ignore_line in lines:
        return

    with exclude_file.open(
        "a",
        encoding="utf-8",
        newline="\n",
    ) as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(ignore_line + "\n")


def _create_virtualenv(
    project_root: Path,
    env_name: str,
) -> str:
    if env_name not in {
        "venv",
        ".venv",
    }:
        raise ExecuteTaskError(
            "Desteklenmeyen sanal ortam adi."
        )

    target = (
        project_root / env_name
    ).resolve()

    if target.parent != project_root:
        raise ExecuteTaskError(
            "Sanal ortam proje kokunun disina "
            "olusturulamaz."
        )

    config_file = target / "pyvenv.cfg"

    if target.exists():
        if config_file.exists():
            _ensure_local_git_exclude(
                project_root,
                env_name,
            )
            return (
                "Sanal ortam zaten mevcut: "
                f"{target}"
            )

        raise ExecuteTaskError(
            f"Hedef klasor zaten mevcut ve venv degil: {target}"
        )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            env_name,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )

    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "bilinmeyen hata"
        )
        raise ExecuteTaskError(
            "Sanal ortam olusturulamadi: "
            + detail
        )

    if not config_file.exists():
        raise ExecuteTaskError(
            "python -m venv basarili gorundu ancak "
            "pyvenv.cfg bulunamadi."
        )

    _ensure_local_git_exclude(
        project_root,
        env_name,
    )

    return (
        "Sanal ortam olusturuldu: "
        f"{target}"
    )



def _find_project_python(
    project_root: Path,
) -> Path:
    candidates = [
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / "venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
        project_root / "venv" / "bin" / "python",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise ExecuteTaskError(
        "Pip kurulumu icin proje icinde venv/.venv "
        "bulunamadi. Once sanal ortam olusturun."
    )


def _ensure_pip(
    project_root: Path,
) -> str:
    python_exe = _find_project_python(
        project_root
    )

    completed = subprocess.run(
        [
            str(python_exe),
            "-m",
            "ensurepip",
            "--upgrade",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )

    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "bilinmeyen hata"
        )
        raise ExecuteTaskError(
            "Pip kurulumu basarisiz: "
            + detail
        )

    version = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "--version",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    if version.returncode != 0:
        detail = (
            version.stderr.strip()
            or version.stdout.strip()
            or "pip dogrulanamadi"
        )
        raise ExecuteTaskError(
            "Pip kuruldu ancak dogrulama basarisiz: "
            + detail
        )

    return (
        "Pip kurulumu tamamlandi: "
        + version.stdout.strip()
    )


_PACKAGE_TARGET_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
)


def _validate_package_target(
    target: str | None,
) -> str:
    package = (target or "").strip()

    if not package:
        raise ExecuteTaskError(
            "Paket kurulumu icin hedef paket adi bulunamadi."
        )

    if not _PACKAGE_TARGET_RE.fullmatch(package):
        raise ExecuteTaskError(
            "Guvenli olmayan veya desteklenmeyen paket adi: "
            f"{package!r}"
        )

    return package


def _install_python_package(
    project_root: Path,
    target: str | None,
) -> str:
    package = _validate_package_target(
        target
    )

    python_exe = _find_project_python(
        project_root
    )

    completed = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--upgrade",
            package,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )

    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "bilinmeyen hata"
        )
        raise ExecuteTaskError(
            f"{package} kurulumu basarisiz: "
            + detail
        )

    verify = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "show",
            package,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    if verify.returncode != 0:
        detail = (
            verify.stderr.strip()
            or verify.stdout.strip()
            or "paket dogrulanamadi"
        )
        raise ExecuteTaskError(
            f"{package} kuruldu ancak dogrulanamadi: "
            + detail
        )

    version = None
    for line in verify.stdout.splitlines():
        if line.lower().startswith("version:"):
            version = line.split(":", 1)[1].strip()
            break

    suffix = (
        f" {version}"
        if version
        else ""
    )

    return (
        f"Paket kurulumu tamamlandi: "
        f"{package}{suffix}"
    )


_PROJECT_NAME_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]{0,79}$"
)


def _validate_project_name(
    target: str | None,
) -> str:
    name = (target or "").strip()

    if not name:
        raise ExecuteTaskError(
            "Framework projesi icin proje adi bulunamadi."
        )

    if not _PROJECT_NAME_RE.fullmatch(name):
        raise ExecuteTaskError(
            "Gecersiz veya guvenli olmayan proje adi: "
            f"{name!r}"
        )

    return name


def _create_framework_scaffold(
    project_root: Path,
    *,
    framework: str | None,
    target: str | None,
) -> str:
    framework_name = (
        framework or ""
    ).strip().casefold()

    project_name = _validate_project_name(
        target
    )

    if framework_name != "django":
        raise ExecuteTaskError(
            "Desteklenmeyen framework scaffold: "
            f"{framework_name or 'belirsiz'}"
        )

    target_dir = (
        project_root / project_name
    ).resolve()

    if target_dir.parent != project_root:
        raise ExecuteTaskError(
            "Framework projesi proje kokunun disina "
            "olusturulamaz."
        )

    if target_dir.exists():
        raise ExecuteTaskError(
            f"Hedef klasor zaten mevcut: {project_name}"
        )

    python_exe = _find_project_python(
        project_root
    )

    completed = subprocess.run(
        [
            str(python_exe),
            "-m",
            "django",
            "startproject",
            project_name,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "bilinmeyen hata"
        )
        raise ExecuteTaskError(
            "Django projesi olusturulamadi: "
            + detail
        )

    manage_py = target_dir / "manage.py"
    settings_py = (
        target_dir
        / project_name
        / "settings.py"
    )

    if not manage_py.exists():
        raise ExecuteTaskError(
            "Django komutu tamamlandi ancak "
            "manage.py bulunamadi."
        )

    if not settings_py.exists():
        raise ExecuteTaskError(
            "Django komutu tamamlandi ancak "
            "settings.py bulunamadi."
        )

    return (
        "Django projesi olusturuldu: "
        f"{project_name}"
    )

def run_execute_task(
    *,
    project_path: str,
    prompt: str,
    intent: str | None = None,
    target: str | None = None,
    framework: str | None = None,
) -> str:
    project_root = Path(
        project_path
    ).resolve()

    if not project_root.is_dir():
        raise ExecuteTaskError(
            f"Proje klasoru bulunamadi: {project_root}"
        )

    normalized = normalize_text(prompt)

    if intent == "package_install":
        return _install_python_package(
            project_root,
            target,
        )

    if intent == "framework_scaffold":
        return _create_framework_scaffold(
            project_root,
            framework=framework,
            target=target,
        )

    if intent == "create_virtualenv":
        return _create_virtualenv(
            project_root,
            _virtualenv_name(prompt),
        )

    if intent == "ensure_pip":
        return _ensure_pip(
            project_root,
        )

    is_pip_setup_request = (
        "pip" in normalized
        and any(
            token in normalized
            for token in (
                "kur",
                "kurulum",
                "yukle",
                "install",
                "setup",
                "gerceklestir",
            )
        )
    )

    if is_pip_setup_request:
        return _ensure_pip(
            project_root,
        )

    is_virtualenv_request = (
        "venv" in normalized
        or "sanal ortam" in normalized
        or "virtual environment" in normalized
    )

    if is_virtualenv_request:
        return _create_virtualenv(
            project_root,
            _virtualenv_name(prompt),
        )

    raise ExecuteTaskError(
        "Bu EXECUTE gorevi henuz izin verilen "
        "eylemler arasinda degil."
    )
