import json
import os
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


class CodexCliProvider:
    provider_name = "codex_cli"

    _VALID_SANDBOXES = {
        "read-only",
        "workspace-write",
        "danger-full-access",
    }

    def __init__(
        self,
        *,
        executable: str = "codex",
        default_timeout: int = 120,
        sandbox: str = "read-only",
        ephemeral: bool = True,
        run_fn: Callable[..., Any] | None = None,
    ) -> None:
        executable = str(
            executable or ""
        ).strip()

        if not executable:
            raise ValueError(
                "Codex executable cannot be empty."
            )

        if default_timeout < 1:
            raise ValueError(
                "default_timeout must be >= 1"
            )

        sandbox = str(
            sandbox or ""
        ).strip().lower()

        if sandbox not in self._VALID_SANDBOXES:
            raise ValueError(
                "Unsupported Codex sandbox: "
                f"{sandbox}"
            )

        self.executable = executable
        self.default_timeout = int(
            default_timeout
        )
        self.sandbox = sandbox
        self.ephemeral = bool(
            ephemeral
        )
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
                "cli_family": "openai_codex",
                "output_format": "jsonl",
                "sandbox": self.sandbox,
                "ephemeral": self.ephemeral,
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

            if value:
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
    ]:
        timeout = self._resolve_timeout(
            request
        )

        command = [
            self.executable,
            "exec",
            "--json",
            "--sandbox",
            self.sandbox,
        ]

        if self.ephemeral:
            command.append(
                "--ephemeral"
            )

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

        working_directory = (
            self._working_directory(
                request
            )
        )

        if working_directory:
            command.extend(
                [
                    "--cd",
                    working_directory,
                ]
            )

        command.append(
            self._compose_prompt(
                request
            )
        )

        return command, timeout

    @staticmethod
    def _parse_jsonl(
        stdout: str,
    ) -> tuple[
        list[dict[str, Any]],
        list[str],
    ]:
        events: list[
            dict[str, Any]
        ] = []

        invalid_lines: list[
            str
        ] = []

        for raw_line in (
            stdout.splitlines()
        ):
            line = raw_line.strip()

            if not line:
                continue

            try:
                payload = json.loads(
                    line
                )

            except json.JSONDecodeError:
                invalid_lines.append(
                    line
                )
                continue

            if isinstance(
                payload,
                dict,
            ):
                events.append(
                    payload
                )
            else:
                invalid_lines.append(
                    line
                )

        return (
            events,
            invalid_lines,
        )

    @staticmethod
    def _error_text_from_events(
        events: list[
            dict[str, Any]
        ],
    ) -> str:
        messages: list[str] = []

        for event in events:
            event_type = str(
                event.get(
                    "type",
                    "",
                )
                or ""
            ).casefold()

            if (
                "error" not in event_type
                and "failed" not in event_type
            ):
                continue

            for key in (
                "message",
                "error",
                "detail",
            ):
                value = event.get(
                    key
                )

                if isinstance(
                    value,
                    dict,
                ):
                    nested = (
                        value.get(
                            "message"
                        )
                        or value.get(
                            "detail"
                        )
                    )

                    if nested:
                        messages.append(
                            str(nested)
                        )

                elif value:
                    messages.append(
                        str(value)
                    )

        return "\n".join(
            message.strip()
            for message in messages
            if message.strip()
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
                "not logged in",
                "login required",
                "sign in",
                "unauthorized",
                "401",
            )
        ):
            raise (
                AgentProviderUnavailableError(
                    "Codex CLI authentication "
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
                "too many requests",
                "429",
            )
        ):
            raise (
                AgentProviderRateLimitError(
                    "Codex CLI rate limit "
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
                    "Codex model is unavailable: "
                    f"{message}"
                )
            )

        if any(
            marker in normalized
            for marker in (
                "timeout",
                "timed out",
            )
        ):
            raise (
                AgentProviderTimeoutError(
                    "Codex CLI timed out: "
                    f"{message}"
                )
            )

        raise RuntimeError(
            "Codex CLI failed: "
            f"{message}"
        )

    @staticmethod
    def _extract_result(
        events: list[
            dict[str, Any]
        ],
    ) -> tuple[
        str,
        str | None,
        dict[str, Any],
    ]:
        thread_id = None
        messages: list[str] = []
        usage: dict[str, Any] = {}

        for event in events:
            event_type = str(
                event.get(
                    "type",
                    "",
                )
                or ""
            )

            if (
                event_type
                == "thread.started"
            ):
                value = event.get(
                    "thread_id"
                )

                if value:
                    thread_id = str(
                        value
                    )

            elif (
                event_type
                == "item.completed"
            ):
                item = event.get(
                    "item"
                )

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                if (
                    item.get("type")
                    != "agent_message"
                ):
                    continue

                text = item.get(
                    "text"
                )

                if isinstance(
                    text,
                    str,
                ):
                    messages.append(
                        text
                    )

            elif (
                event_type
                == "turn.completed"
            ):
                value = event.get(
                    "usage"
                )

                if isinstance(
                    value,
                    dict,
                ):
                    usage = dict(
                        value
                    )

        if not messages:
            raise RuntimeError(
                "Codex CLI completed without "
                "an agent_message."
            )

        return (
            messages[-1].rstrip(
                "\r\n"
            ),
            thread_id,
            usage,
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
            "codex",
            "codex.exe",
        }:
            return None

        local_app_data = (
            os.environ.get(
                "LOCALAPPDATA"
            )
        )

        if not local_app_data:
            return None

        candidate = (
            Path(local_app_data)
            / "Programs"
            / "OpenAI"
            / "Codex"
            / "bin"
            / "codex.exe"
        )

        if not candidate.is_file():
            return None

        return str(candidate)

    def _run_command(
        self,
        command: list[str],
        *,
        timeout: int,
    ):
        try:
            return self._run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )

        except FileNotFoundError as exc:
            fallback = (
                self
                ._installed_executable_fallback()
            )

            if not fallback:
                raise (
                    AgentProviderUnavailableError(
                        "Codex CLI executable "
                        "was not found: "
                        f"{self.executable}"
                    )
                ) from exc

            retry_command = list(
                command
            )

            retry_command[0] = (
                fallback
            )

            try:
                return self._run(
                    retry_command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    check=False,
                )

            except FileNotFoundError as retry_exc:
                raise (
                    AgentProviderUnavailableError(
                        "Codex CLI executable "
                        "was not found through PATH "
                        "or the official Windows "
                        "installation location."
                    )
                ) from retry_exc

            except subprocess.TimeoutExpired as retry_exc:
                raise (
                    AgentProviderTimeoutError(
                        "Codex CLI process exceeded "
                        f"{timeout} seconds."
                    )
                ) from retry_exc

        except subprocess.TimeoutExpired as exc:
            raise (
                AgentProviderTimeoutError(
                    "Codex CLI process exceeded "
                    f"{timeout} seconds."
                )
            ) from exc

    def complete(
        self,
        request: AgentRequest,
    ) -> AgentResult:
        command, timeout = (
            self._build_command(
                request
            )
        )

        completed = (
            self._run_command(
                command,
                timeout=timeout,
            )
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

        events, invalid_lines = (
            self._parse_jsonl(
                stdout
            )
        )

        event_error = (
            self._error_text_from_events(
                events
            )
        )

        if returncode != 0:
            message = (
                event_error
                or stderr
                or stdout
                or (
                    "process exited with "
                    f"code {returncode}"
                )
            )

            self._raise_mapped_error(
                message
            )

        if event_error:
            self._raise_mapped_error(
                event_error
            )

        if not events:
            if invalid_lines:
                raise RuntimeError(
                    "Codex CLI returned "
                    "invalid JSONL output."
                )

            raise RuntimeError(
                "Codex CLI returned "
                "no JSONL events."
            )

        content, thread_id, usage = (
            self._extract_result(
                events
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
            content=content,
            provider=self.provider_name,
            model=model_name,
            metadata={
                "model_role": (
                    request.model_role
                ),
                "transport": "cli",
                "cli": "codex",
                "thread_id": thread_id,
                "sandbox": self.sandbox,
                "ephemeral": self.ephemeral,
                "event_count": len(
                    events
                ),
                "usage": usage,
                "input_tokens": (
                    usage.get(
                        "input_tokens"
                    )
                ),
                "cached_input_tokens": (
                    usage.get(
                        "cached_input_tokens"
                    )
                ),
                "cache_write_input_tokens": (
                    usage.get(
                        "cache_write_input_tokens"
                    )
                ),
                "output_tokens": (
                    usage.get(
                        "output_tokens"
                    )
                ),
                "reasoning_output_tokens": (
                    usage.get(
                        "reasoning_output_tokens"
                    )
                ),
            },
        )
