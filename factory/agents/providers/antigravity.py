import json
import subprocess
from collections.abc import Callable
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


class AntigravityCliProvider:
    provider_name = "antigravity_cli"

    def __init__(
        self,
        *,
        executable: str = "agy",
        default_timeout: int = 120,
        mode: str = "plan",
        run_fn: Callable[..., Any] | None = None,
    ) -> None:
        executable = str(
            executable or ""
        ).strip()

        if not executable:
            raise ValueError(
                "Antigravity executable "
                "cannot be empty."
            )

        if default_timeout < 1:
            raise ValueError(
                "default_timeout must be >= 1"
            )

        mode = str(
            mode or ""
        ).strip().lower()

        if mode not in {
            "plan",
            "accept-edits",
        }:
            raise ValueError(
                "Unsupported Antigravity mode: "
                f"{mode}"
            )

        self.executable = executable
        self.default_timeout = (
            int(default_timeout)
        )
        self.mode = mode
        self._run = (
            run_fn
            or subprocess.run
        )

    def describe(
        self,
    ) -> ProviderDescriptor:
        return ProviderDescriptor(
            name=self.provider_name,
            transport=(
                ProviderTransport.CLI
            ),
            executable=self.executable,
            features=frozenset(
                {
                    ProviderFeature
                    .SYSTEM_PROMPT,
                    ProviderFeature
                    .MODEL_OVERRIDE,
                    ProviderFeature
                    .TIMEOUT,
                    ProviderFeature
                    .USAGE_METADATA,
                }
            ),
            metadata={
                "cli_family": (
                    "google_antigravity"
                ),
                "output_format": "json",
                "mode": self.mode,
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

        timeout = int(requested)

        if timeout < 1:
            raise ValueError(
                "Agent request timeout "
                "must be >= 1."
            )

        return timeout

    def _build_command(
        self,
        request: AgentRequest,
    ) -> tuple[
        list[str],
        int,
    ]:
        timeout = self._resolve_timeout(
            request
        )

        command = [
            self.executable,
            "--print",
            self._compose_prompt(
                request
            ),
            "--output-format",
            "json",
            "--mode",
            self.mode,
            "--print-timeout",
            f"{timeout}s",
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

        return command, timeout

    @staticmethod
    def _extract_error_text(
        *,
        stdout: str = "",
        stderr: str = "",
        payload: dict[str, Any] | None = None,
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
                message = error.get(
                    "message"
                )

                if message:
                    parts.append(
                        str(message)
                    )

            elif error:
                parts.append(
                    str(error)
                )

            response = payload.get(
                "response"
            )

            if (
                response
                and payload.get(
                    "status"
                )
                != "SUCCESS"
            ):
                parts.append(
                    str(response)
                )

        if stderr:
            parts.append(
                stderr
            )

        if stdout:
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
                "authentication required",
                "not authenticated",
                "authentication failed",
                "sign in",
                "login required",
                "unauthorized",
            )
        ):
            raise (
                AgentProviderUnavailableError(
                    "Antigravity CLI "
                    "authentication is unavailable: "
                    f"{message}"
                )
            )

        if any(
            marker in normalized
            for marker in (
                "rate limit",
                "rate_limit",
                "quota exceeded",
                "too many requests",
                "429",
            )
        ):
            raise (
                AgentProviderRateLimitError(
                    "Antigravity CLI "
                    "rate limit reached: "
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
            )
        ):
            raise (
                AgentModelUnavailableError(
                    "Antigravity model "
                    "is unavailable: "
                    f"{message}"
                )
            )

        if "timeout" in normalized:
            raise (
                AgentProviderTimeoutError(
                    "Antigravity CLI "
                    "timed out: "
                    f"{message}"
                )
            )

        raise RuntimeError(
            "Antigravity CLI failed: "
            f"{message}"
        )

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        command, timeout = (
            self._build_command(
                request
            )
        )

        try:
            completed = self._run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 10,
                check=False,
            )

        except FileNotFoundError as exc:
            raise (
                AgentProviderUnavailableError(
                    "Antigravity CLI "
                    "executable was not found: "
                    f"{self.executable}"
                )
            ) from exc

        except subprocess.TimeoutExpired as exc:
            raise (
                AgentProviderTimeoutError(
                    "Antigravity CLI process "
                    f"exceeded {timeout} seconds."
                )
            ) from exc

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

        if returncode != 0:
            self._raise_mapped_error(
                self._extract_error_text(
                    stdout=stdout,
                    stderr=stderr,
                )
                or (
                    "process exited with "
                    f"code {returncode}"
                )
            )

        try:
            payload = json.loads(
                stdout
            )

        except (
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "Antigravity CLI returned "
                "invalid JSON output."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise RuntimeError(
                "Antigravity CLI JSON "
                "response must be an object."
            )

        status = str(
            payload.get(
                "status",
                "",
            )
            or ""
        ).strip().upper()

        if status != "SUCCESS":
            self._raise_mapped_error(
                self._extract_error_text(
                    payload=payload,
                    stderr=stderr,
                )
                or (
                    "unexpected status "
                    f"{status or '<empty>'}"
                )
            )

        response = payload.get(
            "response"
        )

        if not isinstance(
            response,
            str,
        ):
            raise RuntimeError(
                "Antigravity CLI success "
                "response is missing "
                "string field 'response'."
            )

        usage = payload.get(
            "usage"
        )

        if not isinstance(
            usage,
            dict,
        ):
            usage = {}

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
                "cli": "antigravity",
                "conversation_id": (
                    payload.get(
                        "conversation_id"
                    )
                ),
                "status": status,
                "duration_seconds": (
                    payload.get(
                        "duration_seconds"
                    )
                ),
                "num_turns": (
                    payload.get(
                        "num_turns"
                    )
                ),
                "usage": usage,
                "input_tokens": (
                    usage.get(
                        "input_tokens"
                    )
                ),
                "output_tokens": (
                    usage.get(
                        "output_tokens"
                    )
                ),
                "thinking_tokens": (
                    usage.get(
                        "thinking_tokens"
                    )
                ),
                "cache_read_tokens": (
                    usage.get(
                        "cache_read_tokens"
                    )
                ),
                "total_tokens": (
                    usage.get(
                        "total_tokens"
                    )
                ),
            },
        )
