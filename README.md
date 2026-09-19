# AI Software Factory

AI Software Factory, yerel ve harici yapay zekâ modellerini kullanarak yazılım geliştirme görevlerini planlayan, izole Git worktree'lerinde çalıştıran, test eden ve insan onayından sonra ana dala birleştiren bir **AI kodlama ajanı orkestrasyon sistemi**dir.

Amaç klasik bir kod editörü yapmak değil; farklı AI ajanlarının ortak bir görev sistemi üzerinden güvenli biçimde çalışmasını sağlamaktır.

---

## Temel Fikir

Bir görev verdiğinizde sistem genel olarak şu akışı izler:

```text
Kullanıcı Görevi
      ↓
Task Router
      ↓
READ / WRITE ayrımı
      ↓
Model Router
      ↓
Task Planner
      ↓
Adımlar
      ↓
Git Worktree
      ↓
AI Agent
      ↓
Patch
      ↓
Test / Verify
      ↓
İnsan Onayı
      ↓
Git Merge
```

Her WRITE görevi doğrudan ana proje üzerinde çalışmaz.

Bunun yerine görev için ayrı bir Git worktree ve branch oluşturulur.

Örnek:

```text
Ana proje:
C:\Users\sdoks\Documents\ai-software-factory

Görev worktree:
C:\AI-Worktrees\ai-software-factory\task-1234

Branch:
agent/task-1234
```

Bu sayede AI tarafından yapılan değişiklikler ana projeden izole tutulur.

---

# Özellikler

## READ Görevleri

Kod üzerinde değişiklik yapmadan repository'yi analiz eder.

Örneğin:

```text
Bu projedeki authentication sistemi nasıl çalışıyor?
```

veya:

```text
factory/orchestrator.py dosyasının görevini açıkla.
```

READ görevleri:

* repository context oluşturur,
* ilgili dosyaları analiz eder,
* gerekirse iki aşamalı evidence + synthesis kullanır,
* herhangi bir dosyayı değiştirmez.

---

## WRITE Görevleri

Kod üretme veya değiştirme görevleridir.

Örneğin:

```text
math_utils.py dosyasına factorial(n) fonksiyonu ekle.
Negatif sayılarda ValueError versin.
```

WRITE görevleri:

1. Görevi analiz eder.
2. Gerekirse çok adımlı plan oluşturur.
3. Ayrı Git worktree açar.
4. Kod üretir.
5. Patch uygular.
6. Testleri çalıştırır.
7. Sonucu kullanıcı onayına sunar.
8. Onaylanırsa `master` branch'ine merge eder.

---

# Multi-Step Task Sistemi

Karmaşık görevler tek seferde modele gönderilmez.

Task Planner görevi daha küçük adımlara bölebilir.

Örnek:

```text
1. READ
   İlgili dosyaları incele

2. WRITE
   Fonksiyonu oluştur

3. WRITE
   Testleri oluştur

4. VERIFY
   Python dosyalarını doğrula

5. VERIFY
   Pytest çalıştır
```

Her adım SQLite veritabanında saklanır.

Bu nedenle görev yarıda kalırsa sistem tamamlanan adımları tekrar çalıştırmadan devam edebilir.

---

# Retry / Resume

Multi-step bir görev hata verdiğinde worktree hemen silinmez.

Örneğin:

```text
Step 1 → completed
Step 2 → completed
Step 3 → completed
Step 4 → failed
```

Retry yapıldığında:

```text
Step 1 → atlanır
Step 2 → atlanır
Step 3 → atlanır
Step 4 → tekrar çalıştırılır
```

Önceden tamamlanan işler korunur.

---

# Requirement Guard

AI tarafından oluşturulan testlerin kullanıcı tarafından istenmeyen davranışlar uydurmasını azaltmak için WRITE ajanında requirement guard bulunur.

Örneğin kullanıcı:

```text
Baştaki ve sondaki boşlukları temizle.
Sonucu küçük harfe çevir.
```

dediyse model kendi kendine:

```text
İç boşlukları da teke indir.
```

gibi ek bir gereksinim oluşturmamalıdır.

Testler yalnızca:

```text
ORIGINAL USER TASK
+
CURRENT WRITE STEP
```

içinde açıkça belirtilen davranışları doğrulamalıdır.

---

# Task Scope Guard

Kullanıcı belirli dosyalar verdiyse AI'ın görev kapsamı dışındaki dosyalara müdahale etmesi engellenir.

Örneğin:

```text
string_utils.py dosyasını değiştir.
tests/test_string_utils.py testini ekle.
```

Görev sırasında başka bir altyapı dosyasını değiştirmeye çalışırsa patch reddedilir.

---

# Kullanılan Teknolojiler

Backend:

```text
Python
FastAPI
SQLite
Git Worktree
Ollama
LiteLLM
Docker
Pytest
```

Frontend:

```text
React
TypeScript
Vite
```

AI modelleri:

```text
qwen2.5-coder:14b
llama3.1:8b
```

Sistem ileride başka sağlayıcıları da destekleyecek şekilde tasarlanmıştır.

Örneğin:

```text
Gemini CLI
OpenAI Codex
Cloud modeller
Diğer local modeller
```

---

# Proje Yapısı

Ana klasör:

```text
ai-software-factory/
```

Önemli bölümler:

```text
api/
    app.py
```

FastAPI backend API.

---

```text
factory/
```

AI Factory'nin ana sistemi.

Önemli dosyalar:

```text
orchestrator.py
```

Temel görev orkestrasyonu.

```text
task_router.py
```

Görevin READ veya WRITE olduğuna karar verir.

```text
model_router.py
```

Görev için kullanılacak modeli seçer.

```text
task_planner.py
```

Karmaşık görevleri adımlara böler.

```text
task_plan_store.py
```

Planları ve adımları SQLite üzerinde saklar.

```text
task_step_executor.py
```

Plan adımlarını sırayla yürütür.

```text
task_step_handlers.py
```

READ, WRITE ve VERIFY adımlarının gerçek davranışlarını uygular.

```text
multi_step_task_runner.py
```

Çok adımlı görevlerin genel yaşam döngüsünü yönetir.

```text
task_execution_dispatcher.py
```

Legacy single-step ve yeni multi-step çalıştırma sistemleri arasında yönlendirme yapar.

```text
read_task_runner.py
```

Repository analiz görevlerini yürütür.

```text
repository_context.py
architecture_digest.py
```

Repository hakkında modele verilecek bağlamı hazırlar.

---

```text
factory/tools/
```

Alt seviye araçlar.

Örnek:

```text
git_ops.py
```

Git branch ve worktree işlemleri.

```text
patch.py
```

Model çıktısını dosyalara uygular.

```text
sandbox.py
```

Kod ve testleri izole ortamda çalıştırır.

```text
repo.py
```

Repository dosyalarını okumak ve context oluşturmak için kullanılır.

---

```text
frontend/
```

React kullanıcı arayüzü.

Önemli dosyalar:

```text
frontend/src/App.tsx
frontend/src/api.ts
```

---

```text
tests/
```

AI Software Factory'nin kendi pytest testleri.

---

```text
data/factory.db
```

Görev, plan ve çalışma durumlarının tutulduğu SQLite veritabanı.

---

# Kurulum

## 1. Repository'yi Klonla

```powershell
git clone https://github.com/sdoksanbir/ai-software-factory.git

cd ai-software-factory
```

---

# Python Ortamı

Windows PowerShell:

```powershell
python -m venv .venv
```

Virtual environment'ı aktifleştir:

```powershell
.\.venv\Scripts\Activate.ps1
```

Terminal başında şunu görmelisiniz:

```text
(.venv)
```

Python bağımlılıklarını yükleyin:

```powershell
pip install -r requirements.txt
```

---

# Ollama

AI Software Factory local modeller için Ollama kullanır.

Ollama'nın çalıştığını kontrol edin:

```powershell
ollama list
```

Kullanılan temel modeller:

```powershell
ollama pull qwen2.5-coder:14b
```

ve:

```powershell
ollama pull llama3.1:8b
```

Ollama servisi varsayılan olarak:

```text
http://127.0.0.1:11434
```

adresinde çalışır.

---

# Backend'i Çalıştırma

Proje kökünde:

```powershell
cd C:\Users\sdoks\Documents\ai-software-factory
```

Virtual environment aktif değilse:

```powershell
.\.venv\Scripts\Activate.ps1
```

Backend'i başlat:

```powershell
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Backend:

```text
http://127.0.0.1:8000
```

adresinde çalışır.

Windows ortamında şu aşamada özellikle:

```text
--reload
```

kullanmamak daha güvenlidir.

---

# Frontend'i Çalıştırma

Yeni bir PowerShell terminali açın.

```powershell
cd C:\Users\sdoks\Documents\ai-software-factory\frontend
```

İlk kurulumsa:

```powershell
npm install
```

Frontend'i başlatın:

```powershell
npm run dev
```

Vite terminalde kullanılacak adresi gösterecektir.

Genellikle:

```text
http://localhost:5173
```

üzerinden açılır.

---

# Günlük Çalıştırma Sırası

Projeyi normal olarak kullanmak için üç bileşen gerekir.

### Terminal 1 — Ollama

Ollama uygulamasının çalıştığından emin olun.

Kontrol:

```powershell
ollama list
```

---

### Terminal 2 — Backend

```powershell
cd C:\Users\sdoks\Documents\ai-software-factory

.\.venv\Scripts\Activate.ps1

python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

---

### Terminal 3 — Frontend

```powershell
cd C:\Users\sdoks\Documents\ai-software-factory\frontend

npm run dev
```

Ardından tarayıcıdan frontend'i açın.

---

# Backend Portu Meşgulse

Port `8000` üzerinde eski bir backend süreci kalmış olabilir.

PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
Select-Object -ExpandProperty OwningProcess -Unique |
ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
}
```

Ardından backend'i tekrar başlatın.

---

# Testleri Çalıştırma

Belirli bir test:

```powershell
python -m pytest tests/test_task_step_handlers.py -q
```

Multi-step altyapısının önemli testleri:

```powershell
python -m pytest `
    tests/test_task_execution_dispatcher.py `
    tests/test_multi_step_task_runner.py `
    tests/test_task_step_executor.py `
    tests/test_task_step_handlers.py `
    -q
```

---

# Frontend Build Kontrolü

```powershell
cd frontend
npm run build
cd ..
```

Build başarılıysa frontend TypeScript/Vite tarafında temel derleme problemi bulunmuyor demektir.

---

# Git Worktree Kontrolü

Aktif AI görevlerinin worktree'lerini görmek için:

```powershell
git worktree list
```

Normal, boş durumda yalnızca ana proje görünmelidir:

```text
C:/Users/sdoks/Documents/ai-software-factory ... [master]
```

Aktif görev varsa örneğin:

```text
C:/AI-Worktrees/ai-software-factory/task-1234 ... [agent/task-1234]
```

gibi ikinci bir kayıt görünür.

---

# Git Durumu

Çalışmaya başlamadan ve commit atmadan önce:

```powershell
git status
```

Temiz durumda:

```text
nothing to commit, working tree clean
```

görülmelidir.

---

# GitHub'a Gönderme

Remote repository:

```text
https://github.com/sdoksanbir/ai-software-factory.git
```

Yeni commit oluşturmak için:

```powershell
git add .
git commit -m "Aciklayici commit mesaji"
```

GitHub'a göndermek için:

```powershell
git push
```

---

# Sistem Güvenliği

AI doğrudan `master` üzerinde değişiklik yapmaz.

Temel prensip:

```text
AI kod üretir
        ↓
izole worktree
        ↓
test
        ↓
diff
        ↓
insan onayı
        ↓
merge
```

Bu nedenle AI'ın yaptığı değişiklikler kullanıcı tarafından onaylanmadan ana projeye alınmamalıdır.

---

# Task Durumları

Bir görev yaşam döngüsü boyunca farklı durumlara geçebilir.

Örneğin:

```text
queued
running
failed
ready_for_approval
approved
rejected
```

Multi-step plan içindeki adımlar ise:

```text
pending
running
completed
failed
skipped
```

durumlarını kullanabilir.

---

# İnsan Onayı

Başarılı WRITE görevleri otomatik olarak `master` branch'ine merge edilmez.

Önce:

```text
ready_for_approval
```

durumuna gelir.

Kullanıcı diff'i kontrol eder.

Onay verilirse:

```text
task branch
      ↓
commit
      ↓
master merge
      ↓
worktree cleanup
```

gerçekleşir.

Reddedilirse görev branch'i ve worktree temizlenir.

---

# Dynamic Task Plan UI

Frontend multi-step görev planını backend'den dinamik olarak alır.

Endpoint:

```text
GET /tasks/{task_id}/plan
```

UI her plan adımını ayrı olarak gösterebilir.

Örneğin:

```text
✓ Repository Analizi
✓ Fonksiyon Oluştur
✓ Test Dosyası Oluştur
● Testleri Çalıştır
○ Son Doğrulama
```

Plan sabit frontend aşamalarına bağlı değildir; backend tarafından oluşturulan gerçek görev planını kullanır.

---

# Mevcut Stabil Checkpoint

FAZ 17 sonunda sistemde:

```text
Multi-step planning
Multi-step execution
Persistent task plans
Per-step retry
Resume
Scoped verification
Requirement guard
Human approval
Dynamic plan UI
```

çalışır durumdadır.

Önemli checkpoint commit'leri:

```text
6ecb973 Add dynamic task plan UI
d08af76 Add resumable multi-step task execution
97fbb8b Merge agent/task-6928
a47ea57 Scope multi-step verification to task files
0aae687 Constrain multi-step writes to step scope
c3bef1f Make room for mandatory read step in full plans
```

---

# Projenin Uzun Vadeli Hedefi

AI Software Factory'nin hedefi tek bir AI modeline bağlı bir kodlama aracı olmak değildir.

Hedef mimari:

```text
                 AI SOFTWARE FACTORY

                       Task
                        │
                        ▼
                  Agent Router
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       Local AI      Gemini CLI     Codex
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                  Shared Context
                        │
                 Task / Checkpoint
                        │
                    Git Worktree
                        │
                  Test / Verify
                        │
                  Human Approval
```

Farklı AI ajanlarının aynı görevi devralabilmesi hedeflenmektedir.

Bir ajan:

```text
analiz
```

yapabilir.

Başka bir ajan:

```text
kodlama
```

yapabilir.

Başka bir ajan:

```text
review / verification
```

yapabilir.

Hepsi ortak:

```text
Git
Task State
Plan
Checkpoint
Test Result
Repository Context
```

üzerinden çalışacaktır.

---

# Geliştirme Prensipleri

Projede mümkün olduğunca şu prensipler korunmalıdır:

* AI ana branch üzerinde doğrudan çalışmamalı.
* Her WRITE görevi izole worktree kullanmalı.
* Model çıktısı uygulanmadan önce doğrulanmalı.
* Dosya kapsamı mümkün olduğunca sınırlandırılmalı.
* Testler kullanıcı gereksinimlerinden yeni davranış uydurmamalı.
* Tamamlanmış multi-step adımlar retry sırasında tekrar çalıştırılmamalı.
* Task state ve plan bilgileri kalıcı tutulmalı.
* Merge öncesinde insan onayı bulunmalı.
* Local modeller mümkün olduğunca kullanılabilmeli.
* Provider bağımlılığı minimum tutulmalı.

---

# Hızlı Başlangıç

Projeyi daha önce kurduysanız günlük kullanım için:

**Backend:**

```powershell
cd C:\Users\sdoks\Documents\ai-software-factory
.\.venv\Scripts\Activate.ps1
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

**Frontend:**

```powershell
cd C:\Users\sdoks\Documents\ai-software-factory\frontend
npm run dev
```

**Ollama kontrol:**

```powershell
ollama list
```

Bu üçü çalışıyorsa AI Software Factory kullanılmaya hazırdır.

---

## Repository

```text
https://github.com/sdoksanbir/ai-software-factory
```

---

## Durum

**Aktif geliştirme aşamasındadır.**

Şu anki stabil temel:

```text
FAZ 17
```

sonrası mimaridir.
