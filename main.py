import sys
from factory.orchestrator import Orchestrator

# LEGACY CLI entrypoint.
# Production API uses structured execution
# (execute_write_task / run_multi_step_task) and does
# not call Orchestrator.run_task().
# This path remains for direct CLI usage only.

def main():
    if len(sys.argv) < 2:
        print("[-] Hata: Lütfen bir görev belirtin.")
        print("Kullanım Örneği:")
        print("  python main.py \"Bana math.py içinde iki sayıyı toplayan bir fonksiyon yaz ve testini ekle\"")
        sys.exit(1)

    prompt = sys.argv[1]

    # LEGACY: CLI still drives the old run_task loop.
    orchestrator = Orchestrator()
    worktree_path = orchestrator.run_task(prompt)
    
    if worktree_path:
        print(f"\n[i] Sonraki Adım: Worktree klasörünü inceleyip onaylayabilirsin.")

if __name__ == "__main__":
    main()