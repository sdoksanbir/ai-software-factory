import os
import random
import re
import subprocess
from typing import Optional
from factory.schemas import TaskSpec, TaskStatus
from factory.state import TaskStateMachine
from factory.models import ModelClient
from factory.tools.git_ops import GitWorktreeManager
from factory.tools.repo import RepoTool
from factory.tools.patch import PatchTool, PatchToolError
from factory.tools.sandbox import DockerSandbox


class Orchestrator:
    def __init__(self, project_path: str = ".", worktree_root: Optional[str] = None):
        self.project_path = os.path.abspath(project_path)
        
        if worktree_root is None:
            self.worktree_root = r"C:\AI-Worktrees"
        else:
            self.worktree_root = os.path.abspath(worktree_root)

        self.model_client = ModelClient()
        self.git_manager = GitWorktreeManager(self.project_path, self.worktree_root)
        
        # Docker olmasa bile çökmemesi için güvenli başlatma
        try:
            self.sandbox = DockerSandbox()
        except Exception:
            self.sandbox = None

    @staticmethod
    def _extract_explicit_file_targets(prompt: str) -> list[str]:
        pattern = r"(?<![\w.-])([\w./\\-]+\.(?:py|js|jsx|ts|tsx|json|yaml|yml))(?![\w.-])"

        matches = re.findall(
            pattern,
            prompt,
            flags=re.IGNORECASE,
        )

        targets = []

        for match in matches:
            normalized = match.replace("\\", "/").lstrip("./")

            if normalized not in targets:
                targets.append(normalized)

        return targets

    @staticmethod
    def _validate_explicit_file_scope(
        prompt: str,
        changed_paths: list[str],
    ) -> None:
        explicit_targets = Orchestrator._extract_explicit_file_targets(
            prompt
        )

        if not explicit_targets:
            return

        allowed_paths = set(explicit_targets)

        for target in explicit_targets:
            normalized = target.replace("\\", "/")
            filename = normalized.rsplit("/", 1)[-1]

            if filename.endswith(".py"):
                stem = filename[:-3]
                allowed_paths.add(f"tests/test_{stem}.py")

        normalized_changes = [
            path.replace("\\", "/").lstrip("./")
            for path in changed_paths
        ]

        violations = [
            path
            for path in normalized_changes
            if path not in allowed_paths
        ]

        if violations:
            raise PatchToolError(
                "Model attempted to modify files outside the explicit "
                f"task scope. Allowed: {sorted(allowed_paths)}. "
                f"Rejected: {sorted(violations)}"
            )

    def _handle_cli_approval(
        self,
        task_id,
        state_machine,
        wt_result,
        diff_output,
    ):
        while True:
            print("\n--- İnsan Onayı ---")
            print("[1] Diff'i tekrar göster")
            print("[2] Onayla ve ana dala birleştir")
            print("[3] Reddet ve değişiklikleri sil")

            choice = input("Seçiminiz [1/2/3]: ").strip()

            if choice == "1":
                print("\n--- Oluşan Git Diff ---")
                print(diff_output if diff_output else "(Değişiklik görünmüyor)")
                print("-----------------------")
                continue

            if choice == "2":
                commit_hash = self.git_manager.commit_all(
                    wt_result.path,
                    f"{task_id}: AI generated changes"
                )

                merge_hash = self.git_manager.merge_branch(
                    wt_result.branch
                )

                self.git_manager.remove_worktree(wt_result.path)
                self.git_manager.delete_branch(wt_result.branch)

                state_machine.transition(TaskStatus.APPROVED)

                print("\n[+] Onaylandı.")
                print(f"[+] Task commit: {commit_hash}")
                print(f"[+] Merge commit: {merge_hash}")
                print("[+] Worktree ve görev branch'i temizlendi.")
                return None

            if choice == "3":
                self.git_manager.remove_worktree(
                    wt_result.path,
                    force=True
                )
                self.git_manager.delete_branch(
                    wt_result.branch,
                    force=True
                )

                state_machine.transition(TaskStatus.REJECTED)

                print("\n[-] Görev reddedildi.")
                print("[+] Worktree ve görev branch'i silindi.")
                return None

            print("[-] Geçersiz seçim. 1, 2 veya 3 girin.")

    def run_task(
        self,
        prompt: str,
        task_id: Optional[str] = None,
        max_attempts: int = 2,
        approval_handler=None,
    ) -> Optional[str]:
        if not task_id:
            rand_num = random.randint(1000, 9999)
            task_id = f"TASK-{rand_num}"

        print(f"\n[+] Yeni Görev Başlatıldı: {task_id}")
        print(f"[*] Prompt: {prompt}")

        # 1. TaskSpec ve State Machine
        try:
            task_spec = TaskSpec(
                task_id=task_id,
                project_path=self.project_path,
                request=prompt,
                max_attempts=max_attempts
            )
            state_machine = TaskStateMachine(task_spec)
        except Exception as e:
            print(f"[-] Görev spesifikasyonu oluşturulamadı: {str(e)}")
            return None

        # 2. Git Worktree
        try:
            state_machine.transition(TaskStatus.WORKTREE_CREATING)
            wt_result = self.git_manager.create_worktree(task_id.lower())
            state_machine.transition(TaskStatus.WORKTREE_READY)
            print(f"[+] Worktree açıldı: {wt_result.path} (Branch: {wt_result.branch})")
        except Exception as e:
            print(f"[-] Worktree oluşturulamadı: {str(e)}")
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.FAILED)
            return None

        # 3. Repo Context
        try:
            state_machine.transition(TaskStatus.CONTEXT_BUILDING)

            context_targets = self._extract_explicit_file_targets(prompt)

            if context_targets:
                context_paths = list(context_targets)

                for target in context_targets:
                    normalized = target.replace("\\", "/")
                    filename = normalized.rsplit("/", 1)[-1]

                    if filename.lower().endswith(".py"):
                        stem = filename[:-3]
                        test_path = f"tests/test_{stem}.py"

                        if test_path not in context_paths:
                            context_paths.append(test_path)

                context_parts = []

                for rel_path in context_paths:
                    try:
                        content = RepoTool.read_file(
                            wt_result.path,
                            rel_path,
                        )
                    except Exception:
                        continue

                    context_parts.append(
                        f"===== TARGET FILE: {rel_path} =====\n"
                        f"{content}\n"
                        "===== END TARGET FILE ====="
                    )

                if context_parts:
                    repo_summary = "\n\n".join(context_parts)
                else:
                    repo_summary = (
                        "No existing target files were found. "
                        "Create only the explicitly requested task files."
                    )
            else:
                repo_summary = RepoTool.build_context(
                    wt_result.path
                )

            state_machine.transition(TaskStatus.CONTEXT_READY)
        except Exception:
            repo_summary = "Files could not be read."
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.FAILED)
            return None

        system_prompt = (
            "Sen otonom bir yazılım geliştirme ajanısın. "
            "Yanıtın yalnızca geçerli bir JSON nesnesi olmalı. "
            "Markdown, açıklama metni veya kod bloğu kullanma. "
            "JSON yapısı tam olarak şu biçimde olmalı: "
            '{"files":[{"path":"relative/path.py","content":"dosyanın tam içeriği"}],"explanation":"kısa açıklama"}. '
            "Her dosya için content alanında dosyanın değişiklik sonrası TAM içeriğini ver. "
            "Görev çalıştırılabilir Python kodunda yeni davranış ekliyor veya mevcut davranışı değiştiriyorsa "
            "uygun pytest test dosyasını da files dizisine ekle veya güncelle. "
            "Testler gerçek davranışı doğrulamalı; yalnızca import veya smoke test yeterli değildir. "
            "TASK_SCOPE_GUARD: G\u00f6rev kapsam\u0131 d\u0131\u015f\u0131ndaki dosyalara dokunma. "
            "Kullan\u0131c\u0131 belirli bir dosya veya dosya ad\u0131 verdiyse \u00f6ncelikle yaln\u0131zca o dosyay\u0131 "
            "ve davran\u0131\u015f\u0131 do\u011frulamak i\u00e7in gerekli test dosyas\u0131n\u0131 olu\u015ftur veya de\u011fi\u015ftir. "
            "Mevcut altyap\u0131, orchestrator, sandbox, repo ara\u00e7lar\u0131 veya ba\u015fka ilgisiz dosyalar\u0131 "
            "yaln\u0131zca g\u00f6rev bunu a\u00e7\u0131k\u00e7a gerektiriyorsa de\u011fi\u015ftir."
        )

        explicit_targets = self._extract_explicit_file_targets(prompt)

        allowed_scope_paths = list(explicit_targets)

        for target in explicit_targets:
            normalized = target.replace("\\", "/")
            filename = normalized.rsplit("/", 1)[-1]

            if filename.lower().endswith(".py"):
                stem = filename[:-3]
                test_path = f"tests/test_{stem}.py"

                if test_path not in allowed_scope_paths:
                    allowed_scope_paths.append(test_path)

        scope_contract = ""

        if allowed_scope_paths:
            scope_contract = (
                "MANDATORY TASK SCOPE:\n"
                f"Only these file paths are allowed: {allowed_scope_paths}\n"
                "Do not create or modify any other file. "
                "Do not invent a different task from repository context.\n\n"
            )

        user_prompt = (
            f"TASK:\n{prompt}\n\n"
            f"{scope_contract}"
            f"REPOSITORY CONTEXT - reference only:\n{repo_summary}\n\n"
            "Complete exactly the TASK above. "
            "Do not treat repository context as a new task. "
            "Do not infer functionality from filenames, repository names, existing modules, "
            "or repository context. Implement only the behavior explicitly requested in TASK. "
            "OUTPUT SCHEMA IS MANDATORY: the top-level JSON object must contain a files key. "
            "files must be a JSON array. Every files item must contain path and content. "
            "Use exactly this structure: "
            '{"files":[{"path":"relative/path.py","content":"FULL FILE CONTENT"}],"explanation":"short explanation"}. '
            'Never return a filename-to-content object such as {"file.py":"content"}. '
            "Return exactly one valid JSON object using this schema. "
            "The first character of your response must be { and the last character must be }. "
            "Do not use Markdown, code fences, headings, commentary, or text outside JSON. "
            f"{scope_contract}"
        )

        success = False

        # 4. Model ve Test Döngüsü
        while task_spec.attempt < task_spec.max_attempts:
            try:
                state_machine.register_attempt()
                print(f"\n--- Deneme {task_spec.attempt}/{task_spec.max_attempts} ---")

                state_machine.transition(TaskStatus.MODEL_RUNNING)
                response = self.model_client.complete(
                    model_role="fast_local",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.2
                )
                state_machine.transition(TaskStatus.MODEL_COMPLETED)
                print(f"[+] Model yanıtı alındı.")

                state_machine.transition(TaskStatus.PATCH_VALIDATING)

                multi_file_patch = PatchTool.parse_multi_file_response(
                    response.content
                )

                state_machine.transition(TaskStatus.PATCH_READY)

                changed_paths = [
                    file_change.path
                    for file_change in multi_file_patch.files
                ]

                self._validate_explicit_file_scope(
                    prompt,
                    changed_paths,
                )

                written_files = PatchTool.apply_multi_file_patch(
                    wt_result.path,
                    multi_file_patch
                )

                state_machine.transition(TaskStatus.PATCH_APPLIED)

                print(f"[+] Patch uygulandı: {len(written_files)} dosya")
                for written_file in written_files:
                    relative_path = os.path.relpath(
                        written_file,
                        wt_result.path
                    )
                    print(f"    - {relative_path}")

                # Test aşaması (Docker yoksa lokal Python subprocess ile çalıştır)
                state_machine.transition(TaskStatus.TESTING)
                print(f"[*] Testler çalıştırılıyor...")
                
                test_passed = False
                test_output = ""

                try:
                    if self.sandbox is None:
                        raise RuntimeError("Docker sandbox kullanılamıyor.")

                    test_command = (
                        "python -c \"import pathlib; "
                        "[compile(p.read_text(encoding='utf-8'), str(p), 'exec') "
                        "for p in pathlib.Path('.').rglob('*.py')]\" || exit $?; "
                        "PYTHONDONTWRITEBYTECODE=1 python -m pytest -q; "
                        "code=$?; "
                        "if [ $code -eq 5 ]; then exit 0; else exit $code; fi"
                    )

                    res = self.sandbox.run_command(
                        wt_result.path,
                        test_command
                    )

                    test_passed = res.success
                    test_output = res.stdout + res.stderr

                except Exception as test_err:
                    test_output = str(test_err)
                    test_passed = False

                if test_passed:
                    state_machine.transition(TaskStatus.TEST_PASSED)
                    print(f"[+] Testler başarılı!")
                    success = True
                    break
                else:
                    state_machine.transition(TaskStatus.TEST_FAILED)
                    print(f"[-] Test hatası: {test_output}")
                    user_prompt += f"\n\nÖnceki deneme başarısız oldu. Hata:\n{test_output}\nLütfen düzelt."

            except PatchToolError as e:
                print(f"[-] Patch/JSON hatası: {str(e)}")

                if task_spec.attempt < task_spec.max_attempts:
                    user_prompt += (
                        f"\n\nÖnceki yanıt uygulanamadı. Hata:\n{str(e)}\n"
                        "Yanıtını yalnızca belirtilen JSON şemasına uygun olarak yeniden üret."
                    )
                    continue

                if not state_machine.is_terminal:
                    state_machine.transition(TaskStatus.FAILED)

                break

            except Exception as e:
                print(f"[-] Deneme sırasında hata: {str(e)}")

                if not state_machine.is_terminal:
                    try:
                        state_machine.transition(TaskStatus.FAILED)
                    except Exception:
                        pass

                break

        # 5. Sonuç ve Onay Aşaması
        if success:
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.READY_FOR_APPROVAL)

            diff_output = self.git_manager.get_diff(wt_result.path)

            print(f"\n[✨] Görev Başarıyla Tamamlandı! Task ID: {task_id}")
            print("\n--- Oluşan Git Diff ---")
            print(diff_output if diff_output else "(Değişiklik görünmüyor)")
            print("-----------------------")
            print(f"[!] Worktree Konumu: {wt_result.path}")

            if approval_handler is not None:
                return approval_handler(
                    task_id,
                    state_machine,
                    wt_result,
                    diff_output,
                )

            return self._handle_cli_approval(
                task_id,
                state_machine,
                wt_result,
                diff_output,
            )
        else:
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.FAILED)
            print(f"\n[❌] Görev Maksimum Deneme Sayısında Başarısız Oldu: {task_id}")
            return None
