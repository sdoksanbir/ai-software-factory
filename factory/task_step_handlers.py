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

        # Dosya-hedef ayrisimini test/fake
        # orchestrator nesnesine baglama.
        # Gercek Orchestrator static yardimcisini
        # kullan.
        from factory.orchestrator import Orchestrator

        # Bu adimin acikca hedefledigi dosyalari bul.
        step_targets = (
            Orchestrator
            ._extract_explicit_file_targets(
                instruction
            )
        )

        # Ana kullanici gorevindeki dosyalar sadece
        # context amaciyla kullanilir. Yazma izni
        # step hedeflerine gore belirlenir.
        global_targets = (
            Orchestrator
            ._extract_explicit_file_targets(
                self.scope_prompt
            )
            if self.scope_prompt
            else []
        )

        context_targets = []

        for target in [
            *step_targets,
            *global_targets,
        ]:
            if target not in context_targets:
                context_targets.append(
                    target
                )

        # Multi-step runner ana kullanici scope'unu
        # verdiyse yalnizca o gorevin hedef dosyalari
        # context'e alinir. Boylece ilgisiz factory
        # dosyalari modele gosterilmez.
        if global_targets:
            context_parts = []

            for rel_path in context_targets:
                try:
                    content = RepoTool.read_file(
                        worktree_path,
                        rel_path,
                    )
                except Exception:
                    continue

                context_parts.append(
                    "===== TARGET FILE: "
                    f"{rel_path} =====\n"
                    f"{content}\n"
                    "===== END TARGET FILE ====="
                )

            if context_parts:
                repository_context = (
                    "\n\n".join(
                        context_parts
                    )
                )
            else:
                repository_context = (
                    "Hedef dosyalar henuz mevcut "
                    "degil. Yalnizca istenen "
                    "dosyalari olustur."
                )

        else:
            # scope_prompt olmayan kullanimlarda
            # eski ayni-worktree davranisini koru.
            # Boylece sonraki WRITE onceki WRITE'in
            # degisikliklerini gorebilir.
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

        # Step kendi hedef dosyalarini acikca
        # belirtiyorsa izin yalnizca o step'e aittir.
        # Step'te hedef yoksa ana gorev scope'una
        # geri don.
        scope_source = (
            instruction
            if step_targets
            else (
                self.scope_prompt
                or instruction
            )
        )

        allowed_targets = (
            step_targets
            if step_targets
            else global_targets
        )

        if allowed_targets:
            scope_contract = (
                "ZORUNLU DOSYA SINIRI:\n"
                "Bu adimda yalnizca su dosya "
                "yollari degistirilebilir:\n"
                + "\n".join(
                    f"- {target}"
                    for target
                    in allowed_targets
                )
                + "\nBaska hicbir dosyayi "
                "olusturma veya degistirme.\n\n"
            )
        else:
            scope_contract = ""

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
                    "Yalnizca mevcut WRITE "
                    "adiminin istedigi davranisi "
                    "uygula. "
                    "Repository context yeni bir "
                    "gorev degildir. "
                    "Context icindeki ilgisiz "
                    "dosyalari degistirme. "
                    "Bir onceki adim tarafindan "
                    "yapilmis degisiklikleri koru. "
                    "content alaninda patch degil, "
                    "dosyanin degisiklik sonrasi "
                    "TAM icerigini ver."
                ),
                user_prompt=(
                    "WRITE STEP:\n"
                    f"{instruction}\n\n"
                    f"{scope_contract}"
                    "HEDEF DOSYA BAGLAMI "
                    "- sadece referans:\n"
                    f"{repository_context}\n\n"
                    "Yalnizca WRITE STEP'i "
                    "tamamla. "
                    "Context'ten yeni bir gorev "
                    "cikarma. "
                    "JSON disinda hicbir sey "
                    "dondurme."
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
        instruction = str(
            step.get("instruction", "")
        ).strip()

        sandbox = self.orchestrator.sandbox

        if sandbox is None:
            raise RuntimeError(
                "Docker sandbox kullanilamiyor."
            )

        import shlex
        from pathlib import Path as FilePath
        from factory.orchestrator import Orchestrator

        # Multi-step gorevde ana kullanici scope'u
        # varsa tum repository yerine yalnizca o
        # gorevin dosyalarini dogrula.
        scope_source = (
            self.scope_prompt
            or instruction
        )

        explicit_targets = (
            Orchestrator
            ._extract_explicit_file_targets(
                scope_source
            )
        )

        python_targets = [
            target
            for target in explicit_targets
            if target.lower().endswith(".py")
        ]

        test_targets = []

        for target in python_targets:
            normalized = (
                target
                .replace("\\", "/")
            )

            filename = (
                normalized
                .rsplit("/", 1)[-1]
            )

            if (
                normalized.startswith("tests/")
                or filename.startswith("test_")
            ):
                if target not in test_targets:
                    test_targets.append(
                        target
                    )

        # Kaynak Python dosyasi verildiyse ve
        # karsilik gelen test dosyasi worktree'de
        # mevcutsa onu da scoped teste ekle.
        for target in python_targets:
            normalized = (
                target
                .replace("\\", "/")
            )

            if normalized.startswith("tests/"):
                continue

            filename = (
                normalized
                .rsplit("/", 1)[-1]
            )

            if not filename.lower().endswith(".py"):
                continue

            stem = filename[:-3]

            candidate = (
                f"tests/test_{stem}.py"
            )

            candidate_path = (
                FilePath(worktree_path)
                / candidate
            )

            if (
                candidate_path.exists()
                and candidate not in test_targets
            ):
                test_targets.append(
                    candidate
                )

        # Scope varsa sadece ilgili Python
        # dosyalarini derle.
        if python_targets:
            compile_command = (
                "python -m py_compile "
                + " ".join(
                    shlex.quote(target)
                    for target
                    in python_targets
                )
            )
        else:
            # Eski / genel davranis.
            compile_command = (
                "python -m compileall -q ."
            )

        compile_result = (
            sandbox.run_command(
                worktree_path,
                compile_command,
                timeout_seconds=120,
            )
        )

        if not compile_result.success:
            raise RuntimeError(
                "Compile validation failed:\n"
                + (
                    compile_result.stderr
                    or compile_result.stdout
                    or "Unknown compile error"
                )
            )

        # Explicit test dosyalari varsa yalnizca
        # onlari calistir. Boylece gorevle ilgisiz
        # proje testleri sandbox dependency
        # eksiklikleri yuzunden gorevi bozmaz.
        if test_targets:
            test_command = (
                "python -m pytest -q "
                + " ".join(
                    shlex.quote(target)
                    for target
                    in test_targets
                )
            )

            test_result = (
                sandbox.run_command(
                    worktree_path,
                    test_command,
                    timeout_seconds=180,
                )
            )

            if not test_result.success:
                raise RuntimeError(
                    "Test validation failed:\n"
                    + (
                        test_result.stderr
                        or test_result.stdout
                        or "Unknown pytest error"
                    )
                )

            return (
                "Scoped dogrulama tamamlandi. "
                "Python dosyalari derlendi ve "
                "ilgili pytest testleri basarili."
            )

        # Scope verilmediyse eski full-suite
        # davranisini koru.
        if not explicit_targets:
            test_command = (
                "python -m pytest -q; "
                "code=$?; "
                "if [ $code -eq 5 ]; "
                "then exit 0; "
                "else exit $code; fi"
            )

            test_result = (
                sandbox.run_command(
                    worktree_path,
                    test_command,
                    timeout_seconds=180,
                )
            )

            if not test_result.success:
                raise RuntimeError(
                    "Test validation failed:\n"
                    + (
                        test_result.stderr
                        or test_result.stdout
                        or "Unknown pytest error"
                    )
                )

            return (
                "Dogrulama tamamlandi. "
                "Python compile ve pytest basarili."
            )

        # Explicit scope var fakat o scope'ta
        # pytest dosyasi yoksa scoped compile
        # yeterli kabul edilir.
        return (
            "Scoped dogrulama tamamlandi. "
            "Python dosyalari derlendi; "
            "scope icinde pytest dosyasi yok."
        )

