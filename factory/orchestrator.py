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
            "Yanıtın yalnızca geçerli bir JSON nesnesi olmalı. "
            "Markdown, açıklama metni veya kod bloğu kullanma. "
            "JSON yapısı tam olarak şu biçimde olmalı: "
            '{"files":[{"path":"relative/path.py","content":"dosyanın tam içeriği"}],"explanation":"kısa açıklama"}. '
            "Her dosya için content alanında dosyanın değişiklik sonrası TAM içeriğini ver. "
            "Görev çalıştırılabilir Python kodunda yeni davranış ekliyor veya mevcut davranışı değiştiriyorsa "
            "uygun pytest test dosyasını da files dizisine ekle veya güncelle. "
            "Testler gerçek davranışı doğrulamalı; yalnızca import veya smoke test yeterli değildir."
        )

        user_prompt = (
            f"Görev: {prompt}\n\n"
            f"Mevcut Proje Dosyaları:\n{repo_summary}\n\n"
            "Görevi tamamlamak için değiştirilmesi veya oluşturulması gereken tüm dosyaları "
            "files dizisinde belirt. Değişmeyen dosyaları ekleme. "
            "path alanları proje köküne göre relative olmalı. "
            "Her content alanı ilgili dosyanın son halinin tamamını içermeli. "
            "Python davranışı ekleniyor veya değiştiriliyorsa ilgili pytest testlerini de oluştur veya güncelle."
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
        else:
            if not state_machine.is_terminal:
                state_machine.transition(TaskStatus.FAILED)
            print(f"\n[❌] Görev Maksimum Deneme Sayısında Başarısız Oldu: {task_id}")
            return None
