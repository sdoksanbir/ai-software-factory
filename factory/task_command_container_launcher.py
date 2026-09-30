"""Trusted container launcher for task commands.

This is NOT user project code. TaskCommandSandbox
bind-mounts this file read-only into the container
and feeds a JSON payload on stdin (including secret
env values). It never uses a shell.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(
            f"launcher: invalid stdin JSON: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    if not isinstance(payload, dict):
        print(
            "launcher: payload must be an object",
            file=sys.stderr,
        )
        raise SystemExit(2)

    argv = payload.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(x, str) for x in argv)
    ):
        print(
            "launcher: argv must be a non-empty string list",
            file=sys.stderr,
        )
        raise SystemExit(2)

    extra_env = payload.get("env") or {}
    if not isinstance(extra_env, dict):
        print(
            "launcher: env must be an object",
            file=sys.stderr,
        )
        raise SystemExit(2)

    for key, value in extra_env.items():
        if not isinstance(key, str) or not isinstance(
            value,
            str,
        ):
            print(
                "launcher: env keys/values must be strings",
                file=sys.stderr,
            )
            raise SystemExit(2)

    # Start from container image environment only;
    # overlay explicit request env (may include secrets).
    process_env = dict(os.environ)
    process_env.update(extra_env)

    executable = argv[0]
    try:
        os.execvpe(executable, argv, process_env)
    except OSError as exc:
        print(
            f"launcher: exec failed: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(127) from exc


if __name__ == "__main__":
    main()
