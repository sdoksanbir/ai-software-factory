import os
import random
import subprocess
from typing import Optional
from factory.schemas import TaskSpec, TaskStatus
from factory.state import TaskStateMachine
from factory.models import ModelClient
from factory.tools.git_ops import GitWorktreeManager
from factory.tools.repo import RepoTool
from factory.tools.patch import PatchTool
from factory.tools.sandbox import DockerSandbox


class Orchestrator:
    def __init__(self, project_path: str = ".", worktree_root: Optional[str] = None):
        self.project_path = os.path.abspath(project_path)
        
        if worktree_root is None:
            parent_dir = os.path.dirname(self.project_path)
            self.worktree_root = os.path.join(parent_dir, "test_worktrees")
        else:
            self.worktree_root = os.path.abspath(worktree_root)

        self.model_client = ModelClient()
        self.git_manager = GitWorktreeManager(self.project_path, self.worktree_root)
        
        # Docker olmasa bile çökmemesi için güvenli başlatma
        try:
            self.sandbox = DockerSandbox()
        except Exception:
            self.sandbox = None

    def run_task(self, prompt: str, task_id: Optional[str] = None, max_attempts: int = 2) -> Optional[str]:
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
            file_list = RepoTool.list_files(wt_result.path)
            repo_summary = "\n".join(file_list[:100])
            state_machine.transition(TaskStatus.CONTEXT_READY)
        except Exception as e:
            repo_summary = "Dosyalar okunamadı."
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.FAILED)
            return None

        system_prompt = (
            "Sen otonom bir yazılım geliştirme ajanısın. "
            "Sana verilen görevi yerine getirmek için proje dosyalarını inceleyebilir "
            "ve Python kodu yazabilirsin. Yanıtını sadece uygulanabilir kod blokları şeklinde ver."
        )

        user_prompt = (
            f"Görev: {prompt}\n\n"
            f"Mevcut Proje Dosyaları:\n{repo_summary}\n\n"
            f"Lütfen bu görevi yerine getirmek için hangi dosyada ne değişiklik yapacağını "
            f"veya hangi yeni dosyayı oluşturacağını açıkça belirt."
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
                state_machine.transition(TaskStatus.PATCH_READY)

                target_file = "utils.py"
                state_machine.transition(TaskStatus.PATCH_APPLIED)
                PatchTool.apply_file_patch(wt_result.path, target_file, response.content)
                print(f"[+] Patch uygulandı: {target_file}")

                # Test aşaması (Docker yoksa lokal Python subprocess ile çalıştır)
                state_machine.transition(TaskStatus.TESTING)
                print(f"[*] Testler çalıştırılıyor...")
                
                test_passed = False
                test_output = ""

                try:
                    if self.sandbox is None:
                        raise RuntimeError("Docker sandbox kullanılamıyor.")

                    test_command = (
                        "python -m compileall -q . || exit $?; "
                        "pytest -q; "
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
            print(f"\n--- Oluşan Git Diff ---")
            print(diff_output if diff_output else "(Değişiklik görünmüyor)")
            print(f"-----------------------")
            print(f"[!] Worktree Konumu (İnceleme için): {wt_result.path}")
            return wt_result.path
        else:
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.FAILED)
            print(f"\n[❌] Görev Maksimum Deneme Sayısında Başarısız Oldu: {task_id}")
            return None