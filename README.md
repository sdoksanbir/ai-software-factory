# AI Software Factory

AI Software Factory, farklı yapay zekâ ajanlarını ve yerel/cloud modelleri tek bir kontrollü yürütme katmanında yöneten bir geliştirme ortamıdır.

Bu depo artık projenin **aktif ve devam edilecek ana sürümünü** temsil eder.

## Temel mimari

Sistem şu ana bileşenlerden oluşur:

- **Agent Router / Provider Adapter**
  - Ollama
  - OpenRouter
  - Codex / Gemini gibi ek sağlayıcı adaptörleri
- **READ / WRITE / EXECUTE görev ayrımı**
- **Agent Terminal Loop**
  - güvenli komut seçimi
  - hata sonrası yeniden planlama
  - komut geçmişi
- **Git + worktree izolasyonu**
  - WRITE görevleri ana çalışma dizininde doğrudan değişiklik yapmaz
- **Docker sandbox**
  - proje kodu güvenli sınır içinde çalıştırılır
  - terminal görevleri için kalıcı Python dependency volume desteği vardır
- **Handoff / Checkpoint**
  - ajanlar arası görev devri ve durum kaydı
- **İnsan onayı**
  - WRITE görevi doğrulanmadan ana dala uygulanmaz
- **FastAPI backend**
- **React + TypeScript + Vite frontend**
- **SQLite**
  - görev, plan, komut, checkpoint ve diğer çalışma kayıtları

## Güncel doğrulama durumu

Bu sürümde:

- Backend testleri: **1022 passed, 12 skipped**
- Frontend production build: başarılı
- Frontend lint: **0 error**
- Git çalışma ağacı: temiz

---

# Başka bir bilgisayara kurulum

Aşağıdaki adımlar Windows 11 + PowerShell içindir.

## 1. Gerekli programlar

Bilgisayarda şunlar kurulu olmalıdır:

### Git

Kontrol:

~~~powershell
git --version
~~~

### Python

Bu proje **Python 3.14.x** ile test edilmiştir.

Kontrol:

~~~powershell
python --version
~~~

Windows Python Launcher kullanıyorsanız:

~~~powershell
py --version
~~~

### Node.js + npm

Frontend Vite 8 kullanır.

Vite 8 için en az:

- Node.js 20.19+
- veya Node.js 22.12+

Kontrol:

~~~powershell
node --version
npm --version
~~~

### Docker Desktop

Docker Desktop açık ve çalışıyor olmalıdır.

Kontrol:

~~~powershell
docker version
~~~

### Ollama

Yerel modelleri kullanmak için Ollama kurulmalıdır.

Kontrol:

~~~powershell
ollama --version
~~~

---

## 2. Projeyi GitHub'dan klonla

~~~powershell
git clone https://github.com/sdoksanbir/ai-software-factory.git
cd ai-software-factory
~~~

Kontrol:

~~~powershell
git status
~~~

---

## 3. Python sanal ortamını oluştur

İlk kurulumda önce sanal ortam oluşturulmalıdır.

~~~powershell
python -m venv .venv
~~~

Python Launcher ile:

~~~powershell
py -3.14 -m venv .venv
~~~

Aktifleştir:

~~~powershell
.\.venv\Scripts\Activate.ps1
~~~

PowerShell script çalıştırmayı engellerse yalnızca mevcut terminal için:

~~~powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
~~~

---

## 4. Backend bağımlılıklarını kur

Önce pip'i güncelle:

~~~powershell
python -m pip install --upgrade pip
~~~

Sonra:

~~~powershell
python -m pip install -r requirements.txt
~~~

### requirements.txt içeriği

Ana bağımlılıklar:

- pydantic
- litellm
- PyYAML
- python-dotenv
- fastapi
- uvicorn
- httpx
- psutil
- docker
- rich
- pytest

---

## 5. Frontend bağımlılıklarını kur

Projede frontend/package-lock.json bulunduğu için temiz ve tekrar üretilebilir kurulumda npm ci kullanılır:

~~~powershell
npm --prefix frontend ci
~~~

Kontrol:

~~~powershell
npm --prefix frontend run build
~~~

---

## 6. Docker sandbox imajını oluştur

AI Software Factory varsayılan olarak şu Docker image adını kullanır:

~~~text
ai-factory-python-test
~~~

Repoda bunun için Dockerfile vardır.

Proje kökünde:

~~~powershell
docker build `
  -f docker/ai-factory-python-test.Dockerfile `
  -t ai-factory-python-test `
  .
~~~

Kontrol:

~~~powershell
docker image inspect ai-factory-python-test
~~~

Bu image WRITE doğrulama sandbox'ı ve terminal yürütme altyapısı için temel Python ortamını sağlar.

---

## 7. Ollama modellerini kur

Mevcut config.yaml içindeki yerel fallback modelleri:

~~~text
qwen2.5-coder:14b
qwen3:14b
~~~

İndir:

~~~powershell
ollama pull qwen2.5-coder:14b
ollama pull qwen3:14b
~~~

Kontrol:

~~~powershell
ollama list
~~~

Ollama servisi çalışmıyorsa:

~~~powershell
ollama serve
~~~

Windows'ta Ollama uygulaması zaten arka planda çalışıyorsa ayrıca ollama serve açmanız gerekmez.

Varsayılan adres:

~~~text
http://127.0.0.1:11434
~~~

---

## 8. OpenRouter kullanacaksan API anahtarı ekle

config.yaml içinde OpenRouter rotaları da vardır.

OpenRouter kullanacaksan proje kökünde bir .env dosyası oluştur:

~~~text
OPENROUTER_API_KEY=buraya_api_anahtari
~~~

.env Git tarafından takip edilmez.

API anahtarlarını hiçbir zaman repoya commit etmeyin.

---

# Programı çalıştırma

İki ayrı PowerShell terminali açın.

## Terminal 1 — Backend

~~~powershell
cd C:\PROJE_YOLU\ai-software-factory
.\.venv\Scripts\Activate.ps1

python -m uvicorn api.app:app `
  --host 127.0.0.1 `
  --port 8000
~~~

Backend:

~~~text
http://127.0.0.1:8000
~~~

## Terminal 2 — Frontend

~~~powershell
cd C:\PROJE_YOLU\ai-software-factory

npm --prefix frontend run dev
~~~

Vite varsayılan olarak genellikle:

~~~text
http://localhost:5173
~~~

adresini kullanır.

Frontend /api isteklerini otomatik olarak http://127.0.0.1:8000 adresindeki backend'e yönlendirir.

---

# Kurulum sonrası sağlık kontrolü

## Backend bağımlılıkları

~~~powershell
python -c "import fastapi, uvicorn, litellm, psutil, dotenv; print('Python dependencies OK')"
~~~

## Docker

~~~powershell
docker version
docker image inspect ai-factory-python-test
~~~

## Ollama

~~~powershell
ollama list
~~~

## Frontend

~~~powershell
npm --prefix frontend run build
npm --prefix frontend run lint
~~~

---

# Testler

Tüm backend testleri:

~~~powershell
python -m pytest -q --tb=short
~~~

Önemli approval / WRITE testleri:

~~~powershell
python -m pytest `
  tests/test_approval_merge_invariant.py `
  tests/test_multi_step_task_runner.py `
  -q
~~~

Frontend:

~~~powershell
npm --prefix frontend run build
npm --prefix frontend run lint
~~~

---

# Proje verileri

SQLite veritabanı varsayılan olarak proje içindeki data/ alanında oluşturulur.

Veritabanı dosyaları Git'e gönderilmez:

~~~text
data/*.db
data/*.db-wal
data/*.db-shm
~~~

Bu nedenle başka bilgisayara temiz kurulum yaptığınızda kaynak kod gelir fakat eski yerel görev veritabanı otomatik olarak gelmez.

Eski görev geçmişini de taşımak isterseniz ilgili SQLite dosyasını ayrıca kopyalamanız gerekir.

---

# Güvenlik yaklaşımı

- Model doğrudan shell yetkisi almaz.
- Terminal komutları controller tarafından sınıflandırılır.
- Dangerous komutlar reddedilir.
- Proje kodu gereken durumlarda Docker sandbox içinde çalışır.
- WRITE görevleri ayrı Git worktree içinde yürütülür.
- Gizli bilgiler modelin serbestçe belirlediği env değişkenleri olarak verilmez.
- Approval öncesi final Git diff boşsa WRITE görevi başarısız sayılır.
- Approval sırasında merge sonucu Git ancestry ile doğrulanır.

---

# Günlük kullanım

Backend:

~~~powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
~~~

Frontend:

~~~powershell
npm --prefix frontend run dev
~~~

Ollama:

~~~powershell
ollama list
~~~

Docker:

~~~powershell
docker ps
~~~

---

# Güncelleme

Başka bilgisayarda projeyi daha sonra güncellemek için:

~~~powershell
git pull
python -m pip install -r requirements.txt
npm --prefix frontend ci
~~~

Eğer sandbox Dockerfile veya Python bağımlılıkları değiştiyse image'ı yeniden oluşturun:

~~~powershell
docker build `
  -f docker/ai-factory-python-test.Dockerfile `
  -t ai-factory-python-test `
  .
~~~

---

# Repository

https://github.com/sdoksanbir/ai-software-factory

Bu depo AI Software Factory'nin aktif geliştirme sürümüdür.
