import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from factory.agents.contracts import (
    AgentRequest,
    AgentResult,
)
from factory.agents.provider_adapter import (
    ProviderDescriptor,
    ProviderFeature,
    ProviderTransport,
)
from factory.agents.provider_errors import (
    AgentModelUnavailableError,
    AgentProviderRateLimitError,
    AgentProviderTimeoutError,
    AgentProviderUnavailableError,
)


class GeminiCliProvider:
    provider_name = "gemini_cli"

    _VALID_APPROVAL_MODES = {
        "default",
        "auto_edit",
        "yolo",
        "plan",
    }

    def __init__(
        self,
        *,
        executable: str = "gemini",
        default_timeout: int = 120,
        approval_mode: str = "plan",
        run_fn: Callable[..., Any] | None = None,
    ) -> None:
        executable = str(
            executable or ""
        ).strip()

        if not executable:
            raise ValueError(
                "Gemini executable cannot be empty."
            )

        if default_timeout < 1:
            raise ValueError(
                "default_timeout must be >= 1"
            )

        approval_mode = str(
            approval_mode or ""
        ).strip().lower()

        if (
            approval_mode
            not in self._VALID_APPROVAL_MODES
        ):
            raise ValueError(
                "Unsupported Gemini approval mode: "
                f"{approval_mode}"
            )

        self.executable = executable
        self.default_timeout = int(
            default_timeout
        )
        self.approval_mode = approval_mode

        self._run = (
            run_fn
            or subprocess.run
        )

    def describe(
        self,
    ) -> ProviderDescriptor:
        return ProviderDescriptor(
            name=self.provider_name,
            transport=ProviderTransport.CLI,
            executable=self.executable,
            features=frozenset(
                {
                    ProviderFeature.SYSTEM_PROMPT,
                    ProviderFeature.MODEL_OVERRIDE,
                    ProviderFeature.TIMEOUT,
                    ProviderFeature.USAGE_METADATA,
                }
            ),
            metadata={
                "cli_family": "google_gemini",
                "output_format": "json",
                "approval_mode": (
                    self.approval_mode
                ),
                "non_interactive": True,
            },
        )

    @staticmethod
    def _compose_prompt(
        request: AgentRequest,
    ) -> str:
        system_prompt = str(
            request.system_prompt
            or ""
        ).strip()

        user_prompt = str(
            request.user_prompt
            or ""
        ).strip()

        if not system_prompt:
            return user_prompt

        return (
            "SYSTEM INSTRUCTIONS:\n"
            f"{system_prompt}\n\n"
            "USER REQUEST:\n"
            f"{user_prompt}"
        )

    def _resolve_timeout(
        self,
        request: AgentRequest,
    ) -> int:
        requested = getattr(
            request,
            "timeout",
            None,
        )

        if requested is None:
            return self.default_timeout

        timeout = int(
            requested
        )

        if timeout < 1:
            raise ValueError(
                "Agent request timeout "
                "must be >= 1."
            )

        return timeout

    @staticmethod
    def _working_directory(
        request: AgentRequest,
    ) -> str | None:
        metadata = getattr(
            request,
            "metadata",
            None,
        )

        if not isinstance(
            metadata,
            dict,
        ):
            return None

        for key in (
            "working_directory",
            "worktree_path",
        ):
            value = metadata.get(
                key
            )

            if not value:
                continue

            normalized = str(
                value
            ).strip()

            if normalized:
                return normalized

        return None

    def _build_command(
        self,
        request: AgentRequest,
    ) -> tuple[
        list[str],
        int,
        str | None,
    ]:
        timeout = self._resolve_timeout(
            request
        )

        command = [
            self.executable,
            "--prompt",
            self._compose_prompt(
                request
            ),
            "--output-format",
            "json",
            "--approval-mode",
            self.approval_mode,
        ]

        model_name = str(
            getattr(
                request,
                "model_name",
                None,
            )
            or ""
        ).strip()

        if model_name:
            command.extend(
                [
                    "--model",
                    model_name,
                ]
            )

        return (
            command,
            timeout,
            self._working_directory(
                request
            ),
        )

    @staticmethod
    def _parse_payload(
        stdout: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(
                stdout
            )

        except (
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "Gemini CLI returned "
                "invalid JSON output."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeError(
                "Gemini CLI JSON response "
                "must be an object."
            )

        return payload

    @staticmethod
    def _extract_error_text(
        *,
        stdout: str = "",
        stderr: str = "",
        payload: (
            dict[str, Any]
            | None
        ) = None,
    ) -> str:
        parts: list[str] = []

        if payload:
            error = payload.get(
                "error"
            )

            if isinstance(
                error,
                dict,
            ):
                for key in (
                    "message",
                    "detail",
                    "type",
                ):
                    value = error.get(
                        key
                    )

                    if value:
                        parts.append(
                            str(value)
                        )

            elif error:
                parts.append(
                    str(error)
                )

            errors = payload.get(
                "errors"
            )

            if isinstance(
                errors,
                list,
            ):
                for item in errors:
                    if isinstance(
                        item,
                        dict,
                    ):
                        message = (
                            item.get(
                                "message"
                            )
                            or item.get(
                                "detail"
                            )
                            or item.get(
                                "error"
                            )
                        )

                        if message:
                            parts.append(
                                str(message)
                            )

                    elif item:
                        parts.append(
                            str(item)
                        )

        if stderr:
            parts.append(
                stderr
            )

        if (
            stdout
            and not payload
        ):
            parts.append(
                stdout
            )

        return "\n".join(
            item.strip()
            for item in parts
            if item
            and item.strip()
        )

    @staticmethod
    def _raise_mapped_error(
        message: str,
    ) -> None:
        normalized = (
            message.casefold()
        )

        if any(
            marker in normalized
            for marker in (
                "authentication",
                "authenticating",
                "not authenticated",
                "login required",
                "sign in",
                "unauthorized",
                "credentials",
                "ineligibletiererror",
                "ineligible tier",
                "unsupported_client",
                "no longer supported",
                "401",
            )
        ):
            raise (
                AgentProviderUnavailableError(
                    "Gemini CLI authentication "
                    "is unavailable: "
                    f"{message}"
                )
            )

        if any(
            marker in normalized
            for marker in (
                "rate limit",
                "rate_limit",
                "quota exceeded",
                "resource exhausted",
                "too many requests",
                "429",
            )
        ):
            raise (
                AgentProviderRateLimitError(
                    "Gemini CLI rate limit "
                    "reached: "
                    f"{message}"
                )
            )

        if any(
            marker in normalized
            for marker in (
                "model not found",
                "unknown model",
                "invalid model",
                "unsupported model",
                "model does not exist",
            )
        ):
            raise (
                AgentModelUnavailableError(
                    "Gemini model is unavailable: "
                    f"{message}"
                )
            )

        if any(
            marker in normalized
            for marker in (
                "timeout",
                "timed out",
                "deadline exceeded",
            )
        ):
            raise (
                AgentProviderTimeoutError(
                    "Gemini CLI timed out: "
                    f"{message}"
                )
            )

        raise RuntimeError(
            "Gemini CLI failed: "
            f"{message}"
        )

    def _installed_executable_fallback(
        self,
    ) -> str | None:
        executable_name = (
            Path(
                self.executable
            ).name.casefold()
        )

        if executable_name not in {
            "gemini",
            "gemini.cmd",
            "gemini.ps1",
        }:
            return None

        app_data = os.environ.get(
            "APPDATA"
        )

        if not app_data:
            return None

        candidate = (
            Path(app_data)
            / "npm"
            / "gemini.cmd"
        )

        if not candidate.is_file():
            return None

        return str(candidate)

    def _resolve_executable(
        self,
    ) -> str | None:
        executable_path = Path(
            self.executable
        )

        if (
            executable_path.is_absolute()
            or executable_path.parent
            != Path(".")
        ):
            if executable_path.is_file():
                return str(
                    executable_path
                )

            return None

        resolved = shutil.which(
            self.executable
        )

        if resolved:
            return resolved

        return (
            self
            ._installed_executable_fallback()
        )

    def _run_command(
        self,
        command: list[str],
        *,
        timeout: int,
        cwd: str | None,
    ):
        resolved = (
            self._resolve_executable()
        )

        run_command = list(
            command
        )

        if resolved:
            run_command[0] = resolved

        try:
            return self._run(
                run_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                cwd=cwd,
            )

        except FileNotFoundError as exc:
            raise (
                AgentProviderUnavailableError(
                    "Gemini CLI executable "
                    "was not found: "
                    f"{self.executable}"
                )
            ) from exc

        except subprocess.TimeoutExpired as exc:
            raise (
                AgentProviderTimeoutError(
                    "Gemini CLI process exceeded "
                    f"{timeout} seconds."
                )
            ) from exc

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        (
            command,
            timeout,
            cwd,
        ) = self._build_command(
            request
        )

        completed = self._run_command(
            command,
            timeout=timeout,
            cwd=cwd,
        )

        stdout = str(
            getattr(
                completed,
                "stdout",
                "",
            )
            or ""
        ).strip()

        stderr = str(
            getattr(
                completed,
                "stderr",
                "",
            )
            or ""
        ).strip()

        returncode = int(
            getattr(
                completed,
                "returncode",
                0,
            )
        )

        payload: (
            dict[str, Any]
            | None
        ) = None

        if stdout:
            try:
                payload = (
                    self._parse_payload(
                        stdout
                    )
                )
            except RuntimeError:
                if returncode == 0:
                    raise

        if returncode != 0:
            message = (
                self._extract_error_text(
                    stdout=stdout,
                    stderr=stderr,
                    payload=payload,
                )
                or (
                    "process exited with "
                    f"code {returncode}"
                )
            )

            self._raise_mapped_error(
                message
            )

        if payload is None:
            raise RuntimeError(
                "Gemini CLI returned "
                "no JSON response."
            )

        error_text = (
            self._extract_error_text(
                stderr="",
                payload=payload,
            )
        )

        if error_text:
            self._raise_mapped_error(
                error_text
            )

        response = payload.get(
            "response"
        )

        if not isinstance(
            response,
            str,
        ):
            raise RuntimeError(
                "Gemini CLI success response "
                "is missing string field "
                "'response'."
            )

        stats = payload.get(
            "stats"
        )

        if not isinstance(
            stats,
            dict,
        ):
            stats = {}

        warnings = payload.get(
            "warnings"
        )

        if not isinstance(
            warnings,
            list,
        ):
            warnings = []

        session_id = (
            payload.get(
                "session_id"
            )
            or payload.get(
                "sessionId"
            )
        )

        model_name = (
            str(
                getattr(
                    request,
                    "model_name",
                    None,
                )
                or ""
            ).strip()
            or None
        )

        return AgentResult(
            content=response.rstrip(
                "\r\n"
            ),
            provider=self.provider_name,
            model=model_name,
            metadata={
                "model_role": (
                    request.model_role
                ),
                "transport": "cli",
                "cli": "gemini",
                "approval_mode": (
                    self.approval_mode
                ),
                "session_id": (
                    str(session_id)
                    if session_id
                    else None
                ),
                "stats": stats,
                "warnings": list(
                    warnings
                ),
            },
        )
