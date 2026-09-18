import os
from factory.tools.git_ops import GitWorktreeManager, BranchAlreadyExistsError, WorktreeAlreadyExistsError

def run_git_tests():
    # Test için kendi bilgisayarındaki geçerli bir git repo yolunu yazabilirsin
    project_path = os.getcwd() 
    worktree_root = r"C:\AI-Worktrees"
    
    print(f"Test Repo Kökü: {project_path}")
    
    manager = GitWorktreeManager(
        project_path=project_path,
        worktree_root=worktree_root
    )
    
    print(f"Repository Doğrulama: {manager.validate_repository()}")
    
    task_id = "TASK-0001"
    try:
        print(f"Worktree oluşturuluyor ({task_id})...")
        result = manager.create_worktree(task_id=task_id)
        print(f"Başarılı!")
        print(f"  - Path: {result.path}")
        print(f"  - Branch: {result.branch}")
        print(f"  - Repo Root: {result.repository_root}")
        
        # Git Status Testi
        status = manager.get_status(result.path)
        print(f"  - Git Status (Porcelain): '{status}' (Boş olmalı)")
        
        # Aynı task tekrar denenirse hata vermeli (WorktreeAlreadyExistsError)
        print("\nAynı task ikinci kez deneniyor (Hata bekleniyor)...")
        manager.create_worktree(task_id=task_id)
        
    except WorktreeAlreadyExistsError as e:
        print(f"Beklenen Worktree Çakışma Hatası Yakalandı: {e}")
    except BranchAlreadyExistsError as e:
        print(f"Beklenen Branch Çakışma Hatası Yakalandı: {e}")
    except Exception as e:
        print(f"Beklenmeyen Hata: {e}")

if __name__ == "__main__":
    run_git_tests()
