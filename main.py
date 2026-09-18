import sys
from factory.orchestrator import Orchestrator

def main():
    if len(sys.argv) < 2:
        print("[-] Hata: Lütfen bir görev belirtin.")
        print("Kullanım Örneği:")
        print("  python main.py \"Bana math.py içinde iki sayıyı toplayan bir fonksiyon yaz ve testini ekle\"")
        sys.exit(1)

    prompt = sys.argv[1]
    
    # Fabrikayı başlat ve görevi çalıştır
    orchestrator = Orchestrator()
    worktree_path = orchestrator.run_task(prompt)
    
    if worktree_path:
        print(f"\n[i] Sonraki Adım: Worktree klasörünü inceleyip onaylayabilirsin.")

if __name__ == "__main__":
    main()