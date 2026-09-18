import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react"

import {
  approveTask,
  createTask,
  getTaskDiff,
  listTasks,
  rejectTask,
  retryTask,
  type Task,
} from "./api"

import "./App.css"

const stateLabels: Record<string, string> = {
  queued: "Sırada",
  running: "Çalışıyor",
  ready_for_approval: "Onay Bekliyor",
  approved: "Onaylandı",
  rejected: "Reddedildi",
  failed: "Başarısız",
}

function formatDate(value: string | null) {
  if (!value) return "?"

  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value))
}

function App() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [prompt, setPrompt] = useState("")
  const [maxAttempts, setMaxAttempts] = useState(3)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [diff, setDiff] = useState("")
  const [loadingDiff, setLoadingDiff] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [backendOnline, setBackendOnline] = useState(true)

  const loadTasks = useCallback(async () => {
    try {
      const data = await listTasks()
      setTasks(data.slice().reverse())
      setBackendOnline(true)
      setError(null)
    } catch (err) {
      setBackendOnline(false)
      setError(
        err instanceof Error
          ? err.message
          : "Backend bağlantısı kurulamadı.",
      )
    }
  }, [])

  useEffect(() => {
    void loadTasks()

    const timer = window.setInterval(() => {
      void loadTasks()
    }, 2000)

    return () => window.clearInterval(timer)
  }, [loadTasks])

  const selectedTask = useMemo(
    () => tasks.find((task) => task.task_id === selectedTaskId) ?? null,
    [tasks, selectedTaskId],
  )

  const stats = useMemo(() => {
    return {
      total: tasks.length,
      running: tasks.filter(
        (task) => task.state === "running" || task.state === "queued",
      ).length,
      approval: tasks.filter(
        (task) => task.state === "ready_for_approval",
      ).length,
      failed: tasks.filter(
        (task) => task.state === "failed",
      ).length,
    }
  }, [tasks])

  async function handleCreate(event: FormEvent) {
    event.preventDefault()

    const cleanPrompt = prompt.trim()

    if (!cleanPrompt) return

    setSubmitting(true)
    setError(null)

    try {
      const task = await createTask(cleanPrompt, maxAttempts)
      setPrompt("")
      setSelectedTaskId(task.task_id)
      setDiff("")
      await loadTasks()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Görev oluşturulamadı.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDiff(taskId: string) {
    setSelectedTaskId(taskId)
    setLoadingDiff(true)
    setDiff("")
    setError(null)

    try {
      const result = await getTaskDiff(taskId)
      setDiff(result.diff || "Değişiklik bulunamadı.")
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Diff alınamadı.",
      )
    } finally {
      setLoadingDiff(false)
    }
  }

  async function handleAction(
    action: "approve" | "reject" | "retry",
  ) {
    if (!selectedTask) return

    setActionLoading(true)
    setError(null)

    try {
      if (action === "approve") {
        await approveTask(selectedTask.task_id)
      }

      if (action === "reject") {
        await rejectTask(selectedTask.task_id)
      }

      if (action === "retry") {
        await retryTask(selectedTask.task_id)
      }

      setDiff("")
      await loadTasks()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "İşlem tamamlanamadı.",
      )
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AF</div>
          <div>
            <strong>AI Factory</strong>
            <span>Software Agent</span>
          </div>
        </div>

        <nav className="nav">
          <button className="nav-item active">Dashboard</button>
          <button className="nav-item" disabled>Projects</button>
          <button className="nav-item" disabled>Models</button>
          <button className="nav-item" disabled>Settings</button>
        </nav>

        <div className="sidebar-footer">
          <span
            className={`connection-dot ${
              backendOnline ? "online" : "offline"
            }`}
          />
          <div>
            <strong>
              {backendOnline ? "Backend Online" : "Backend Offline"}
            </strong>
            <span>Local Factory API</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <p className="eyebrow">LOCAL DEVELOPMENT CONTROL</p>
            <h1>AI Software Factory</h1>
            <p className="subtitle">
              Görev olu?tur, AI ajan?n? ?al??t?r, testleri izle ve
              de?i?iklikleri onayla.
            </p>
          </div>

          <button className="refresh-button" onClick={() => void loadTasks()}>
            Yenile
          </button>
        </header>

        {error && (
          <div className="error-banner">
            <strong>İşlem hatası</strong>
            <span>{error}</span>
            <button onClick={() => setError(null)}>?</button>
          </div>
        )}

        <section className="stats-grid">
          <article className="stat-card">
            <span>Toplam Görev</span>
            <strong>{stats.total}</strong>
          </article>

          <article className="stat-card">
            <span>Aktif</span>
            <strong>{stats.running}</strong>
          </article>

          <article className="stat-card">
            <span>Onay Bekleyen</span>
            <strong>{stats.approval}</strong>
          </article>

          <article className="stat-card">
            <span>Başarısız</span>
            <strong>{stats.failed}</strong>
          </article>
        </section>

        <section className="workspace">
          <div className="left-column">
            <form className="task-composer" onSubmit={handleCreate}>
              <div className="section-heading">
                <div>
                  <span className="section-kicker">NEW TASK</span>
                  <h2>Yeni görev oluştur</h2>
                </div>
              </div>

              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Örn: math_utils.py dosyasında factorial(n) fonksiyonu oluştur..."
                rows={5}
              />

              <div className="composer-footer">
                <label>
                  Maksimum deneme
                  <select
                    value={maxAttempts}
                    onChange={(event) =>
                      setMaxAttempts(Number(event.target.value))
                    }
                  >
                    {[1, 2, 3, 4, 5].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>

                <button
                  className="primary-button"
                  type="submit"
                  disabled={submitting || !prompt.trim()}
                >
                  {submitting ? "Başlatılıyor..." : "Görevi Başlat"}
                </button>
              </div>
            </form>

            <section className="task-list-panel">
              <div className="section-heading">
                <div>
                  <span className="section-kicker">TASK QUEUE</span>
                  <h2>Görevler</h2>
                </div>

                <span className="task-count">
                  {tasks.length} görev
                </span>
              </div>

              <div className="task-list">
                {tasks.length === 0 && (
                  <div className="empty-state">
                    <strong>Hen?z görev yok.</strong>
                    <span>
                      Yukar?daki alandan ilk görevi olu?turabilirsin.
                    </span>
                  </div>
                )}

                {tasks.map((task) => (
                  <button
                    key={task.task_id}
                    className={`task-row ${
                      selectedTaskId === task.task_id ? "selected" : ""
                    }`}
                    onClick={() => {
                      setSelectedTaskId(task.task_id)
                      setDiff("")
                    }}
                  >
                    <div className="task-main">
                      <div className="task-id-line">
                        <strong>{task.task_id}</strong>
                        <span className={`status status-${task.state}`}>
                          {stateLabels[task.state] ?? task.state}
                        </span>
                      </div>

                      <p>{task.prompt}</p>
                    </div>

                    <div className="task-meta">
                      <span>{task.model ?? "?"}</span>
                      <span>{formatDate(task.started_at)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </section>
          </div>

          <aside className="detail-panel">
            {!selectedTask && (
              <div className="detail-empty">
                <div className="detail-icon">?</div>
                <strong>Görev seç</strong>
                <span>
                  Ayr?nt?lar?, diff ??kt?s?n? ve i?lem butonlar?n?
                  g?rmek i?in listeden bir görev se?.
                </span>
              </div>
            )}

            {selectedTask && (
              <>
                <div className="detail-header">
                  <div>
                    <span className="section-kicker">TASK DETAIL</span>
                    <h2>{selectedTask.task_id}</h2>
                  </div>

                  <span className={`status status-${selectedTask.state}`}>
                    {stateLabels[selectedTask.state] ?? selectedTask.state}
                  </span>
                </div>

                <div className="detail-grid">
                  <div>
                    <span>Model</span>
                    <strong>{selectedTask.model ?? "?"}</strong>
                  </div>
                  <div>
                    <span>Deneme</span>
                    <strong>
                      {selectedTask.attempt}/{selectedTask.max_attempts}
                    </strong>
                  </div>
                  <div>
                    <span>Test</span>
                    <strong>{selectedTask.test_result ?? "?"}</strong>
                  </div>
                  <div>
                    <span>Başlangıç</span>
                    <strong>{formatDate(selectedTask.started_at)}</strong>
                  </div>
                </div>

                <div className="prompt-box">
                  <span>Görev</span>
                  <p>{selectedTask.prompt}</p>
                </div>

                {selectedTask.state === "ready_for_approval" && (
                  <div className="approval-actions">
                    <button
                      className="primary-button"
                      disabled={actionLoading}
                      onClick={() => void handleAction("approve")}
                    >
                      Onayla
                    </button>

                    <button
                      className="danger-button"
                      disabled={actionLoading}
                      onClick={() => void handleAction("reject")}
                    >
                      Reddet
                    </button>
                  </div>
                )}

                {selectedTask.state === "failed" && (
                  <button
                    className="primary-button full"
                    disabled={actionLoading}
                    onClick={() => void handleAction("retry")}
                  >
                    Tekrar Dene
                  </button>
                )}

                <div className="diff-section">
                  <div className="diff-heading">
                    <div>
                      <span>Git Diff</span>
                      <small>AI tarafından oluşturulan değişiklikler</small>
                    </div>

                    <button
                      className="secondary-button"
                      disabled={
                        selectedTask.state !== "ready_for_approval" ||
                        loadingDiff
                      }
                      onClick={() =>
                        void handleDiff(selectedTask.task_id)
                      }
                    >
                      {loadingDiff ? "Yükleniyor..." : "Diff Göster"}
                    </button>
                  </div>

                  <pre className="diff-view">
                    {diff ||
                      (selectedTask.state === "ready_for_approval"
                        ? "Diff görüntülemek için butona bas."
                        : "Bu görev i?in kullan?labilir diff yok.")}
                  </pre>
                </div>
              </>
            )}
          </aside>
        </section>
      </main>
    </div>
  )
}

export default App
