from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import sys
from typing import Iterable


class RuntimeGroundingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeCandidate:
    runtime_id: str
    family: str
    executable: str
    source: str
    project_local: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "family": self.family,
            "executable": self.executable,
            "source": self.source,
            "project_local": self.project_local,
        }


def _runtime_id(
    *,
    family: str,
    executable: str,
) -> str:
    payload = (
        f"{family}:{executable}"
        .encode("utf-8")
    )

    digest = hashlib.sha1(
        payload
    ).hexdigest()[:12]

    return f"runtime-{family}-{digest}"


def _is_within(
    path: Path,
    root: Path,
) -> bool:
    try:
        path.resolve().relative_to(
            root.resolve()
        )
        return True
    except ValueError:
        return False


def _candidate(
    *,
    family: str,
    executable: Path,
    source: str,
    project_root: Path,
) -> RuntimeCandidate | None:
    try:
        resolved = executable.resolve()
    except OSError:
        return None

    if not resolved.exists():
        return None

    if not resolved.is_file():
        return None

    value = str(resolved)

    return RuntimeCandidate(
        runtime_id=_runtime_id(
            family=family,
            executable=value,
        ),
        family=family,
        executable=value,
        source=source,
        project_local=_is_within(
            resolved,
            project_root,
        ),
    )


def _python_venv_paths(
    root: Path,
) -> Iterable[
    tuple[Path, str]
]:
    env_names = (
        ".venv",
        "venv",
        "env",
    )

    if os.name == "nt":
        python_rel = (
            "Scripts/python.exe",
        )
    else:
        python_rel = (
            "bin/python",
            "bin/python3",
        )

    bases = [root]

    try:
        children = [
            child
            for child in root.iterdir()
            if child.is_dir()
        ]
    except OSError:
        children = []

    # One nested project level is intentional.
    bases.extend(
        children
    )

    for base in bases:
        for env_name in env_names:
            for rel in python_rel:
                yield (
                    base
                    / env_name
                    / rel,
                    (
                        "project_venv:"
                        + str(
                            (
                                base
                                / env_name
                            ).relative_to(
                                root
                            )
                        )
                    ),
                )


def _path_runtime(
    name: str,
) -> Path | None:
    value = shutil.which(
        name
    )

    if not value:
        return None

    return Path(
        value
    )


def discover_runtime_candidates(
    project_root: str | Path,
) -> list[
    RuntimeCandidate
]:
    root = Path(
        project_root
    ).expanduser().resolve()

    if not root.exists():
        raise RuntimeGroundingError(
            "Project root bulunamadi: "
            f"{root}"
        )

    candidates: list[
        RuntimeCandidate
    ] = []

    seen: set[
        tuple[str, str]
    ] = set()

    def add(
        family: str,
        path: Path | None,
        source: str,
    ) -> None:
        if path is None:
            return

        item = _candidate(
            family=family,
            executable=path,
            source=source,
            project_root=root,
        )

        if item is None:
            return

        key = (
            item.family,
            os.path.normcase(
                item.executable
            ),
        )

        if key in seen:
            return

        seen.add(
            key
        )
        candidates.append(
            item
        )

    # Project-local runtimes first.
    for path, source in _python_venv_paths(
        root
    ):
        add(
            "python",
            path,
            source,
        )

    # Current process runtime is evidence, not an automatic choice.
    add(
        "python",
        Path(
            sys.executable
        ),
        "current_process",
    )

    # PATH-visible interpreters.
    for name in (
        "python",
        "python3",
    ):
        add(
            "python",
            _path_runtime(
                name
            ),
            f"path:{name}",
        )

    add(
        "node",
        _path_runtime(
            "node"
        ),
        "path:node",
    )

    # Stable preference:
    # project-local first, then current process, then PATH.
    def sort_key(
        item: RuntimeCandidate,
    ):
        if item.project_local:
            bucket = 0
        elif (
            item.source
            == "current_process"
        ):
            bucket = 1
        else:
            bucket = 2

        return (
            bucket,
            item.family,
            item.executable.casefold(),
        )

    return sorted(
        candidates,
        key=sort_key,
    )


class RuntimeEvidenceStore:
    def __init__(
        self,
        candidates: list[
            RuntimeCandidate
        ],
    ) -> None:
        self._candidates = {
            item.runtime_id: item
            for item in candidates
        }

    @classmethod
    def discover(
        cls,
        project_root: str | Path,
    ) -> "RuntimeEvidenceStore":
        return cls(
            discover_runtime_candidates(
                project_root
            )
        )

    def records(
        self,
    ) -> list[
        RuntimeCandidate
    ]:
        return list(
            self._candidates.values()
        )

    def to_model_payload(
        self,
    ) -> list[
        dict[str, object]
    ]:
        return [
            item.to_dict()
            for item in self.records()
        ]

    def get(
        self,
        runtime_id: str,
    ) -> RuntimeCandidate:
        try:
            return self._candidates[
                runtime_id
            ]
        except KeyError as exc:
            raise RuntimeGroundingError(
                "Bilinmeyen runtime_id: "
                f"{runtime_id}"
            ) from exc

    def candidates_for(
        self,
        family: str,
    ) -> list[
        RuntimeCandidate
    ]:
        return [
            item
            for item in self.records()
            if item.family
            == family
        ]

    def executable_known(
        self,
        executable: str,
    ) -> bool:
        target = os.path.normcase(
            str(
                Path(
                    executable
                ).expanduser()
                .resolve()
            )
        )

        return any(
            os.path.normcase(
                item.executable
            )
            == target
            for item in self.records()
        )

_RUNTIME_ALIASES = {
    "python": {"python", "python3", "py"},
    "node": {"node"},
}


@dataclass(frozen=True)
class RuntimeBinding:
    runtime: RuntimeCandidate
    request: object


def runtime_family_for_request(request) -> str | None:
    if request.tool_name != "run_process":
        return None

    raw = request.arguments.get("argv")
    if (
        not isinstance(raw, list)
        or not raw
        or not isinstance(raw[0], str)
    ):
        return None

    executable = raw[0].strip().casefold()

    for family, aliases in _RUNTIME_ALIASES.items():
        if executable in aliases:
            return family

    return None


def _select_runtime_candidate(
    *,
    store: "RuntimeEvidenceStore",
    family: str,
    runtime_ref: str | None = None,
) -> RuntimeCandidate:
    candidates = store.candidates_for(family)

    if not candidates:
        raise RuntimeGroundingError(
            f"{family} runtime adayi bulunamadi."
        )

    if runtime_ref:
        item = store.get(runtime_ref)

        if item.family != family:
            raise RuntimeGroundingError(
                "runtime_ref family ile eslesmiyor."
            )

        return item

    project_local = [
        item
        for item in candidates
        if item.project_local
    ]

    if len(project_local) == 1:
        return project_local[0]

    if len(project_local) > 1:
        raise RuntimeGroundingError(
            "Birden fazla project-local runtime var; "
            "runtime_ref gerekli."
        )

    current_process = [
        item
        for item in candidates
        if item.source == "current_process"
    ]

    if len(current_process) == 1:
        return current_process[0]

    if len(candidates) == 1:
        return candidates[0]

    raise RuntimeGroundingError(
        "Runtime secimi belirsiz; runtime_ref gerekli."
    )


def bind_runtime_request(
    *,
    request,
    store: "RuntimeEvidenceStore",
    runtime_ref: str | None = None,
) -> RuntimeBinding | None:
    family = runtime_family_for_request(request)

    if family is None:
        return None

    runtime = _select_runtime_candidate(
        store=store,
        family=family,
        runtime_ref=runtime_ref,
    )

    raw_argv = request.arguments.get("argv")
    argv = list(raw_argv)

    argv[0] = runtime.executable

    arguments = dict(request.arguments)
    arguments["argv"] = argv

    bound_request = request.model_copy(
        update={
            "arguments": arguments,
        }
    )

    return RuntimeBinding(
        runtime=runtime,
        request=bound_request,
    )
