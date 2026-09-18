from typing import Any

from factory.model_router import route_model
from factory.read_task_runner import run_read_task
from factory.tools.patch import PatchTool
from factory.tools.repo import RepoTool


class TaskStepHandlers:
    def __init__(
        self,
        orchestrator: Any,
        *,
        scope_prompt: str | None = None,
        model_name: str | None = None,
    ):
        self.orchestrator = orchestrator
        self.scope_prompt = (
            str(scope_prompt or "").strip()
        )
        self.model_name = model_name

    def read(
        self,
        step: dict[str, Any],
        worktree_path: str,
    ) -> str:
        instruction = str(
            step["instruction"]
        ).strip()

        model_route = route_model(
            instruction
        )

        if self.model_name:
            model_route = type(model_route)(
                model=self.model_name,
                profile=model_route.profile,
                reason=model_route.reason,
                code_score=model_route.code_score,
            )

        return run_read_task(
            project_path=worktree_path,
            prompt=instruction,
            model_route=model_route,
            model_client=(
                self.orchestrator.model_client
            ),
        )

    def write(
        self,
        step: dict[str, Any],
        worktree_path: str,
    ) -> str:
        instruction = str(
            step["instruction"]
        ).strip()

        if not instruction:
            raise ValueError(
                "WRITE step instruction is blank"
            )

        # Her WRITE adiminda context yeniden
        # okunur. Boylece onceki WRITE adimlarinin
        # degisiklikleri sonraki adim tarafindan
        # gorulur.
        repository_context = (
            RepoTool.build_context(
                worktree_path
            )
        )

        selected_model = (
            self.model_name
            or route_model(
                instruction
            ).model
        )

        response = (
            self.orchestrator
            .model_client
            .complete(
                model_role="fast_local",
                system_prompt=(
                    "Sen otonom bir yazilim "
                    "gelistirme ajanisin. "
                    "Yanitin yalnizca gecerli bir "
                    "JSON nesnesi olmali. "
                    "Markdown veya kod blogu "
                    "kullanma. "
                    "JSON semasi tam olarak: "
                    '{"files":['
                    '{"path":"REQUESTED_FILE_PATH",'
                    '"content":"dosyanin TAM '
                    'son icerigi"}],'
                    '"explanation":"kisa aciklama"}. '
                    "Yalnizca bu adimin gerektirdigi "
                    "dosyalari degistir. "
                    "Mevcut repository icerigini "
                    "dikkate al. "
                    "Bir onceki adim tarafindan "
                    "yapilmis degisiklikleri koru. "
                    "content alaninda patch degil, "
                    "dosyanin degisiklik sonrasi "
                    "TAM icerigini ver."
                ),
                user_prompt=(
                    "STEP GOREVI:\n"
                    f"{instruction}\n\n"
                    "MEVCUT WORKTREE BAGLAMI:\n"
                    f"{repository_context}\n\n"
                    "Bu adimi tamamlamak icin "
                    "gereken dosyalari JSON "
                    "formatinda uret."
                ),
                temperature=0.0,
                model_name_override=(
                    selected_model
                ),
            )
        )

        patch = (
            PatchTool
            .parse_multi_file_response(
                response.content
            )
        )

        changed_paths = [
            file_change.path
            for file_change in patch.files
        ]

        scope_source = (
            self.scope_prompt
            or instruction
        )

        self.orchestrator\
            ._validate_explicit_file_scope(
                scope_source,
                changed_paths,
            )

        written_files = (
            PatchTool
            .apply_multi_file_patch(
                worktree_path,
                patch,
            )
        )

        if not written_files:
            raise RuntimeError(
                "WRITE step produced no files"
            )

        return (
            "Degistirilen dosyalar: "
            + ", ".join(
                str(item)
                for item in written_files
            )
        )

    def verify(
        self,
        step: dict[str, Any],
        worktree_path: str,
    ) -> str:
        sandbox = self.orchestrator.sandbox

        if sandbox is None:
            raise RuntimeError(
                "Docker sandbox is not available"
            )

        compile_result = sandbox.run_command(
            worktree_path,
            "python -m compileall -q .",
            timeout_seconds=120,
        )

        if not compile_result.success:
            raise RuntimeError(
                "Python compile validation failed:\n"
                + (
                    compile_result.stderr
                    or compile_result.stdout
                    or "unknown compile error"
                )
            )

        test_command = (
            "python -m pytest -q; "
            "code=$?; "
            "if [ $code -eq 5 ]; "
            "then exit 0; "
            "else exit $code; fi"
        )

        test_result = sandbox.run_command(
            worktree_path,
            test_command,
            timeout_seconds=180,
        )

        if not test_result.success:
            raise RuntimeError(
                "Test validation failed:\n"
                + (
                    test_result.stderr
                    or test_result.stdout
                    or "unknown test error"
                )
            )

        return (
            "Dogrulama tamamlandi. "
            "Python compile ve pytest basarili."
        )

