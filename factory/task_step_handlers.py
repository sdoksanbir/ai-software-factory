from typing import Any

from factory.agents.capabilities import (
    AgentCapability,
)
from factory.agents.contracts import AgentRequest
from factory.agents.runtime import (
    build_default_agent_execution_router,
    resolve_provider_for_role,
)
from factory.model_router import route_model
from factory.read_task_runner import run_read_task
from factory.task_step_executor import (
    AgentStepExecutionError,
    StepHandlerResult,
    StepHandoffRequest,
)
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
    ) -> StepHandlerResult:
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

        runtime = (
            build_default_agent_execution_router(
                self.orchestrator.model_client
            )
        )

        preferred_provider = (
            resolve_provider_for_role(
                self.orchestrator.model_client,
                "fast_local",
                runtime.provider_registry,
            )
        )

        initial_route = runtime.route(
            {
                AgentCapability.READ_REPOSITORY,
            },
            preferred_provider=preferred_provider,
        )

        actual_execution = None
        fallback_failures = []

        def observe_execution(execution):
            nonlocal actual_execution
            actual_execution = execution

            fallback_failures.extend(
                getattr(
                    execution,
                    "failures",
                    (),
                )
            )

        try:
            output = run_read_task(
                project_path=worktree_path,
                prompt=instruction,
                model_route=model_route,
                model_client=(
                    self.orchestrator.model_client
                ),
                execution_observer=(
                    observe_execution
                ),
            )

        except Exception as exc:
            raise AgentStepExecutionError(
                str(exc),
                agent_name=(
                    initial_route.agent.name
                ),
                provider_name=(
                    initial_route
                    .provider
                    .provider_name
                ),
                model_name=model_route.model,
                capabilities=[
                    AgentCapability
                    .READ_REPOSITORY
                    .value,
                ],
            ) from exc

        actual_route = (
            actual_execution.route
            if actual_execution is not None
            else initial_route
        )

        actual_model = (
            getattr(
                getattr(
                    actual_execution,
                    "result",
                    None,
                ),
                "model",
                None,
            )
            or model_route.model
        )

        return StepHandlerResult(
            output=output,
            agent_name=actual_route.agent.name,
            provider_name=(
                actual_route
                .provider
                .provider_name
            ),
            checkpoint_payload={
                "model": actual_model,
            },
            fallback_attempts=tuple(
                {
                    "agent_name": failure.agent_name,
                    "provider_name": (
                        failure.provider_name
                    ),
                    "model_name": model_route.model,
                    "error": failure.error,
                    "error_type": (
                        failure.error_type
                    ),
                }
                for failure
                in fallback_failures
            ),
        )

    def write(
        self,
        step: dict[str, Any],
        worktree_path: str,
    ) -> StepHandlerResult:
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
        # belirtiyorsa o hedefler esas alinir.
        # Ana gorevde ayni dosya adi daha kesin bir
        # yol ile verilmisse (ornegin
        # test_string_utils.py ->
        # tests/test_string_utils.py), bu canonical
        # yol da ayni step icin izinli sayilir.
        if step_targets:
            allowed_targets = list(step_targets)

            step_basenames = {
                target.replace("\\", "/")
                .rsplit("/", 1)[-1]
                for target in step_targets
            }

            for target in global_targets:
                normalized = target.replace(
                    "\\",
                    "/",
                )
                basename = normalized.rsplit(
                    "/",
                    1,
                )[-1]

                if (
                    basename in step_basenames
                    and target not in allowed_targets
                ):
                    allowed_targets.append(target)
        else:
            allowed_targets = list(global_targets)

        # Scope validator ayni izin listesini kullansin.
        # Boylece prompttaki kisa dosya adi ile ana
        # gorevdeki tam yol birbiriyle celismez.
        scope_source = (
            "\n".join(allowed_targets)
            if allowed_targets
            else (
                self.scope_prompt
                or instruction
            )
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

        runtime = (
            build_default_agent_execution_router(
                self.orchestrator.model_client
            )
        )

        preferred_provider = (
            resolve_provider_for_role(
                self.orchestrator.model_client,
                "fast_local",
                runtime.provider_registry,
            )
        )

        required_capabilities = {
            AgentCapability.READ_REPOSITORY,
            AgentCapability.WRITE_CODE,
        }

        initial_route = runtime.route(
            required_capabilities,
            preferred_provider=preferred_provider,
        )

        try:
            fallback_execution = (
                runtime.execute_with_fallback(
                    AgentRequest(
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
                    "TEST REQUIREMENT RULE: "
                    "Testler yalnizca ORIGINAL USER TASK "
                    "ve mevcut WRITE STEP icinde acikca "
                    "istenen davranislari dogrulamali. "
                    "Kullanicinin istemedigi yeni davranis "
                    "veya edge-case uydurma. "
                    "Belirtilmeyen normalization, validation, "
                    "whitespace collapsing, coercion, exception, "
                    "default veya transformation davranislarini "
                    "testlere ekleme. "
                    "Ozellikle kullanici acikca istemediyse "
                    "ic bosluklari degistirme veya teke indirme. "
                    "content alaninda patch degil, "
                    "dosyanin degisiklik sonrasi "
                    "TAM icerigini ver."
                ),
                user_prompt=(
                    "ORIGINAL USER TASK:\n"
                    f"{self.scope_prompt or instruction}\n\n"
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
                    model_name=selected_model,
                ),
                required_capabilities,
                preferred_provider=preferred_provider,
            )
            )

            agent_route = (
                fallback_execution.route
            )
            response = (
                fallback_execution.result
            )

        except Exception as exc:
            raise AgentStepExecutionError(
                str(exc),
                agent_name=(
                    initial_route.agent.name
                ),
                provider_name=(
                    initial_route
                    .provider
                    .provider_name
                ),
                model_name=selected_model,
                capabilities=[
                    AgentCapability
                    .READ_REPOSITORY
                    .value,
                    AgentCapability
                    .WRITE_CODE
                    .value,
                ],
            ) from exc

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

        output = (
            "Degistirilen dosyalar: "
            + ", ".join(
                str(item)
                for item in written_files
            )
        )

        return StepHandlerResult(
            output=output,
            agent_name=agent_route.agent.name,
            provider_name=(
                agent_route
                .provider
                .provider_name
            ),
            checkpoint_payload={
                "model": (
                    getattr(
                        response,
                        "model",
                        None,
                    )
                    or selected_model
                ),
                "files": [
                    str(item)
                    for item in written_files
                ],
            },
            handoff_request=StepHandoffRequest(
                required_capabilities=frozenset(
                    {
                        AgentCapability.REVIEW_CODE,
                    }
                ),
                reason=(
                    "Independent review after "
                    "WRITE step"
                ),
                instruction=(
                    "Review the completed WRITE "
                    "step using the supplied "
                    "checkpoint context. "
                    "Identify correctness, "
                    "regression, security, and "
                    "scope problems. Do not "
                    "modify files. Return ONLY "
                    "valid JSON with this shape: "
                    "{"
                    "\"verdict\": "
                    "\"pass|warn|block\", "
                    "\"summary\": "
                    "\"short summary\", "
                    "\"findings\": ["
                    "{"
                    "\"severity\": "
                    "\"info|warning|error|critical\", "
                    "\"category\": "
                    "\"correctness|regression|"
                    "security|scope|other\", "
                    "\"message\": "
                    "\"finding text\", "
                    "\"blocking\": true"
                    "}"
                    "]"
                    "}. "
                    "Use block when a finding "
                    "must prevent progression."
                ),
                required=False,
                quality_gate=True,
            ),
            fallback_attempts=tuple(
                {
                    "agent_name": failure.agent_name,
                    "provider_name": (
                        failure.provider_name
                    ),
                    "model_name": selected_model,
                    "error": failure.error,
                    "error_type": (
                        failure.error_type
                    ),
                }
                for failure
                in fallback_execution.failures
            ),
        )


    def handoff(
        self,
        source_checkpoint: dict[str, Any],
        request: StepHandoffRequest,
        db_path,
    ) -> dict[str, Any]:
        from factory.agents.handoff import (
            execute_prepared_handoff,
            prepare_agent_handoff,
        )

        runtime = (
            build_default_agent_execution_router(
                self.orchestrator.model_client
            )
        )

        prepared = prepare_agent_handoff(
            source_checkpoint[
                "checkpoint_id"
            ],
            required_capabilities=(
                request.required_capabilities
            ),
            reason=request.reason,
            runtime=runtime,
            preferred_provider=(
                request.preferred_provider
            ),
            db_path=db_path,
        )

        executed = execute_prepared_handoff(
            prepared,
            instruction=request.instruction,
            model_role="fast_local",
            temperature=0.0,
            db_path=db_path,
        )

        return executed.target_checkpoint


    def verify(
        self,
        step: dict[str, Any],
        worktree_path: str,
    ) -> str | StepHandlerResult:
        instruction = str(
            step.get("instruction", "")
        ).strip()

        sandbox = self.orchestrator.sandbox

        if sandbox is None:
            raise RuntimeError(
                "Docker sandbox kullanilamiyor."
            )

        model_client = getattr(
            self.orchestrator,
            "model_client",
            None,
        )

        verifier_route = None

        if model_client is not None:
            runtime = (
                build_default_agent_execution_router(
                    model_client
                )
            )

            preferred_provider = (
                resolve_provider_for_role(
                    model_client,
                    "fast_local",
                    runtime.provider_registry,
                )
            )

            verifier_route = runtime.route(
                {
                    AgentCapability.READ_REPOSITORY,
                    AgentCapability.RUN_TESTS,
                },
                preferred_provider=(
                    preferred_provider
                ),
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

        def verification_success(
            message: str,
            *,
            test_command: str | None = None,
        ) -> str | StepHandlerResult:
            # Backward compatibility:
            # older/minimal orchestrator callers
            # may not expose model_client.
            if verifier_route is None:
                return message

            return StepHandlerResult(
                output=message,
                agent_name=(
                    verifier_route.agent.name
                ),
                provider_name=(
                    verifier_route
                    .provider
                    .provider_name
                ),
                checkpoint_payload={
                    "execution_mode": "tool",
                    "verification": {
                        "passed": True,
                        "compile_command": (
                            compile_command
                        ),
                        "test_command": (
                            test_command
                        ),
                    },
                },
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

            return verification_success(
                (
                    "Scoped dogrulama tamamlandi. "
                    "Python dosyalari derlendi ve "
                    "ilgili pytest testleri basarili."
                ),
                test_command=test_command,
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

            return verification_success(
                (
                    "Dogrulama tamamlandi. "
                    "Python compile ve pytest basarili."
                ),
                test_command=test_command,
            )

        # Explicit scope var fakat o scope'ta
        # pytest dosyasi yoksa scoped compile
        # yeterli kabul edilir.
        return verification_success(
            (
                "Scoped dogrulama tamamlandi. "
                "Python dosyalari derlendi; "
                "scope icinde pytest dosyasi yok."
            )
        )
