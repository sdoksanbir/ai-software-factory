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
  createProject,
  getTaskDiff,
  getTaskPipeline,
  getControlCenterStatus,
  listTasks,
  listProjects,
  rejectTask,
  retryTask,
  type Project,
  type TaskPipeline,
  type ControlCenterStatus,
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
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
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
  const [liveLogs, setLiveLogs] = useState<string[]>([])
  const [controlCenter, setControlCenter] =
    useState<ControlCenterStatus | null>(null)
  const [pipeline, setPipeline] =
    useState<TaskPipeline | null>(null)
  const [projectFormOpen, setProjectFormOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState("")
  const [newProjectPath, setNewProjectPath] = useState("")
  const [projectSubmitting, setProjectSubmitting] = useState(false)

  const loadProjects = useCallback(async () => {
    try {
      const data = await listProjects()

      setProjects(data)

      setSelectedProjectId((current) => {
        if (
          current &&
          data.some(
            (project) =>
              project.project_id === current,
          )
        ) {
          return current
        }

        return data[0]?.project_id ?? null
      })
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Projeler y\u00fcklenemedi.",
      )
    }
  }, [])

  const loadTasks = useCallback(async () => {
    if (!selectedProjectId) {
      setTasks([])
      return
    }

    try {
      const data = await listTasks(
        selectedProjectId,
      )

      setTasks(data.slice().reverse())
      setBackendOnline(true)
      setError(null)
    } catch (err) {
      setBackendOnline(false)
      setError(
        err instanceof Error
          ? err.message
          : "Backend ba\u011flant\u0131s\u0131 kurulamad\u0131.",
      )
    }
  }, [selectedProjectId])

  useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  useEffect(() => {
    void loadTasks()

    const timer = window.setInterval(() => {
      void loadTasks()
    }, 2000)

    return () => window.clearInterval(timer)
  }, [loadTasks])

  useEffect(() => {
    setSelectedTaskId(null)
    setDiff("")
    setLiveLogs([])
  }, [selectedProjectId])

  const loadControlCenter = useCallback(async () => {
    if (!selectedProjectId) {
      setControlCenter(null)
      return
    }

    try {
      const data = await getControlCenterStatus(
        selectedProjectId,
      )

      setControlCenter(data)
    } catch {
      setControlCenter(null)
    }
  }, [selectedProjectId])

  useEffect(() => {
    void loadControlCenter()

    const timer = window.setInterval(() => {
      void loadControlCenter()
    }, 5000)

    return () => window.clearInterval(timer)
  }, [loadControlCenter])

  const loadPipeline = useCallback(async () => {
    if (!selectedTaskId) {
      setPipeline(null)
      return
    }

    try {
      const data = await getTaskPipeline(
        selectedTaskId,
      )

      setPipeline(data)
    } catch {
      setPipeline(null)
    }
  }, [selectedTaskId])

  useEffect(() => {
    void loadPipeline()

    if (!selectedTaskId) {
      return
    }

    const timer = window.setInterval(() => {
      void loadPipeline()
    }, 2000)

    return () => window.clearInterval(timer)
  }, [loadPipeline, selectedTaskId])

  const selectedProject = useMemo(
    () =>
      projects.find(
        (project) =>
          project.project_id === selectedProjectId,
      ) ?? null,
    [projects, selectedProjectId],
  )

  const selectedTask = useMemo(
    () => tasks.find((task) => task.task_id === selectedTaskId) ?? null,
    [tasks, selectedTaskId],
  )

  useEffect(() => {
    if (!selectedTaskId) {
      setLiveLogs([])
      return
    }

    setLiveLogs([])

    const source = new EventSource(
      `/api/tasks/${selectedTaskId}/events`,
    )

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as {
          message?: string
        }

        if (payload.message) {
          setLiveLogs((current) => [
            ...current,
            payload.message as string,
          ])
        }
      } catch {
        // Ignore malformed log events.
      }
    }

    source.addEventListener("done", () => {
      source.close()
    })

    source.onerror = () => {
      source.close()
    }

    return () => {
      source.close()
    }
  }, [selectedTaskId, selectedTask?.started_at])

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

  async function handleProjectCreate(
    event: FormEvent,
  ) {
    event.preventDefault()

    const cleanName = newProjectName.trim()
    const cleanPath = newProjectPath.trim()

    if (!cleanName || !cleanPath) {
      setError(
        "Proje ad\u0131 ve proje klas\u00f6r\u00fc zorunludur.",
      )
      return
    }

    setProjectSubmitting(true)
    setError(null)

    try {
      const project = await createProject(
        cleanName,
        cleanPath,
      )

      await loadProjects()

      setSelectedProjectId(
        project.project_id,
      )

      setNewProjectName("")
      setNewProjectPath("")
      setProjectFormOpen(false)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Proje olu\u015fturulamad\u0131.",
      )
    } finally {
      setProjectSubmitting(false)
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()

    const cleanPrompt = prompt.trim()

    if (!cleanPrompt) return

    setSubmitting(true)
    setError(null)

    try {
      if (!selectedProject) {
        setError(
          "\u00d6nce bir proje se\u00e7melisin.",
        )
        return
      }

      const task = await createTask(
        cleanPrompt,
        maxAttempts,
        selectedProject.project_id,
      )
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

  function scrollToSection(sectionId: string) {
    document
      .getElementById(sectionId)
      ?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      })
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
          <span className="nav-section-label">
            Kontrol
          </span>

          <button
            className="nav-item active"
            type="button"
            onClick={() =>
              scrollToSection("control-center")
            }
          >
            <span>?</span>
            Kontrol Merkezi
          </button>

          <button
            className="nav-item"
            type="button"
            onClick={() =>
              scrollToSection("tasks")
            }
          >
            <span>?</span>
            G?revler
          </button>

          <button
            className="nav-item"
            type="button"
            onClick={() =>
              scrollToSection("projects")
            }
          >
            <span>?</span>
            Projeler
          </button>

          <button
            className="nav-item"
            type="button"
            onClick={() =>
              scrollToSection("models")
            }
          >
            <span>AI</span>
            Modeller
          </button>
        </nav>

        <section className="project-selector" id="projects">
          <div className="project-selector-heading">
            <span>Projeler</span>

            <div className="project-selector-actions">
              <small>{projects.length}</small>

              <button
                type="button"
                className="project-add-button"
                title="Yeni proje ekle"
                onClick={() =>
                  setProjectFormOpen(
                    (current) => !current,
                  )
                }
              >
                +
              </button>
            </div>
          </div>

          {projectFormOpen && (
            <form
              className="project-create-form"
              onSubmit={handleProjectCreate}
            >
              <input
                value={newProjectName}
                onChange={(event) =>
                  setNewProjectName(
                    event.target.value,
                  )
                }
                placeholder="Proje ad?"
                autoFocus
              />

              <input
                value={newProjectPath}
                onChange={(event) =>
                  setNewProjectPath(
                    event.target.value,
                  )
                }
                placeholder="C:\\Projects\\EduTest"
              />

              <div className="project-create-actions">
                <button
                  type="button"
                  className="project-cancel-button"
                  disabled={projectSubmitting}
                  onClick={() => {
                    setProjectFormOpen(false)
                    setNewProjectName("")
                    setNewProjectPath("")
                  }}
                >
                  ?ptal
                </button>

                <button
                  type="submit"
                  className="project-save-button"
                  disabled={
                    projectSubmitting ||
                    !newProjectName.trim() ||
                    !newProjectPath.trim()
                  }
                >
                  {projectSubmitting
                    ? "Ekleniyor..."
                    : "Projeyi Ekle"}
                </button>
              </div>
            </form>
          )}

          <div className="project-list">
            {projects.length === 0 && (
              <div className="project-empty">
                Henüz proje yok.
              </div>
            )}

            {projects.map((project) => (
              <button
                key={project.project_id}
                type="button"
                className={`project-item ${
                  selectedProjectId === project.project_id
                    ? "active"
                    : ""
                }`}
                title={project.path}
                onClick={() =>
                  setSelectedProjectId(project.project_id)
                }
              >
                <span className="project-mark">
                  {project.name
                    .trim()
                    .charAt(0)
                    .toUpperCase()}
                </span>

                <span className="project-info">
                  <strong>{project.name}</strong>
                  <small>{project.path}</small>
                </span>

                {selectedProjectId === project.project_id && (
                  <span
                    className="project-active-dot"
                    aria-label="Aktif proje"
                  />
                )}
              </button>
            ))}
          </div>
        </section>

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
          <div className="topbar-main">
            <div className="topbar-copy">
              <p className="eyebrow">
                AI SOFTWARE FACTORY
              </p>

              <div className="topbar-title-row">
                <h1>
                  {selectedProject?.name ??
                    "Control Center"}
                </h1>

                <span
                  className={`runtime-pill ${
                    backendOnline
                      ? "online"
                      : "offline"
                  }`}
                >
                  <span />
                  {backendOnline
                    ? "Sistem Aktif"
                    : "Ba?lant? Yok"}
                </span>
              </div>

              <p className="subtitle">
                Yerel AI geli?tirme hatt?n?,
                g?revleri ve servisleri tek
                merkezden y?net.
              </p>
            </div>

            <button
              className="refresh-button"
              type="button"
              onClick={() => {
                void loadTasks()
                void loadControlCenter()
              }}
            >
              ? Yenile
            </button>
          </div>

          <nav className="top-navigation">
            <button
              type="button"
              className="top-nav-item active"
              onClick={() =>
                scrollToSection(
                  "control-center",
                )
              }
            >
              Kontrol Paneli
            </button>

            <button
              type="button"
              className="top-nav-item"
              onClick={() =>
                scrollToSection("tasks")
              }
            >
              G?revler
            </button>

            <button
              type="button"
              className="top-nav-item"
              onClick={() =>
                scrollToSection("projects")
              }
            >
              Projeler
            </button>

            <button
              type="button"
              className="top-nav-item"
              onClick={() =>
                scrollToSection("models")
              }
            >
              Modeller
            </button>
          </nav>
        </header>

        {error && (
          <div className="error-banner">
            <strong>İşlem hatası</strong>
            <span>{error}</span>
            <button onClick={() => setError(null)}>?</button>
          </div>
        )}

        <section className="control-center" id="control-center">
          <div className="control-center-heading">
            <div>
              <span className="section-kicker">
                CONTROL CENTER
              </span>
              <h2>Sistem ve Ajan Durumu</h2>
            </div>

            <div className="control-project-badge">
              <span className="connection-dot online" />
              <span>
                {selectedProject?.name ??
                  "Proje seçilmedi"}
              </span>
            </div>
          </div>

          <div className="control-status-grid">
            <article className="control-status-card">
              <div className="control-card-title">
                <span>Sistem</span>
                <small>
                  {controlCenter?.system.platform ?? "—"}
                </small>
              </div>

              <div className="resource-grid">
                <div className="resource-item">
                  <span>CPU</span>
                  <strong>
                    {controlCenter?.system.cpu.used_percent !=
                    null
                      ? `${Math.round(
                          controlCenter.system.cpu
                            .used_percent,
                        )}%`
                      : "—"}
                  </strong>
                  <small>
                    {controlCenter?.system.cpu.logical_count ??
                      "—"}{" "}
                    mantıksal çekirdek
                  </small>
                </div>

                <div className="resource-item">
                  <span>RAM</span>
                  <strong>
                    {controlCenter?.system.memory
                      .used_percent != null
                      ? `${Math.round(
                          controlCenter.system.memory
                            .used_percent,
                        )}%`
                      : "—"}
                  </strong>
                  <small>Bellek kullanımı</small>
                </div>

                <div className="resource-item">
                  <span>Disk</span>
                  <strong>
                    {controlCenter?.system.disk
                      .used_percent != null
                      ? `${Math.round(
                          controlCenter.system.disk
                            .used_percent,
                        )}%`
                      : "—"}
                  </strong>
                  <small>Disk kullanımı</small>
                </div>

                <div className="resource-item">
                  <span>Git</span>
                  <strong>
                    {controlCenter?.git.branch ?? "—"}
                  </strong>
                  <small>
                    {controlCenter?.git.clean === true
                      ? "Temiz"
                      : controlCenter?.git.clean === false
                        ? "Değişiklik var"
                        : "Bilinmiyor"}
                  </small>
                </div>
              </div>
            </article>

            <article className="control-status-card">
              <div className="control-card-title">
                <span>Servisler</span>
                <small>Local Runtime</small>
              </div>

              <div className="service-list">
                <div className="service-row">
                  <span
                    className={`service-dot ${
                      controlCenter?.services.docker
                        .online
                        ? "online"
                        : "offline"
                    }`}
                  />
                  <div>
                    <strong>Docker</strong>
                    <small>
                      {controlCenter?.services.docker
                        .online
                        ? "Online"
                        : "Offline"}
                    </small>
                  </div>
                </div>

                <div className="service-row">
                  <span
                    className={`service-dot ${
                      controlCenter?.services.ollama
                        .online
                        ? "online"
                        : "offline"
                    }`}
                  />
                  <div>
                    <strong>Ollama</strong>
                    <small>
                      {controlCenter?.services.ollama
                        .online
                        ? "Online"
                        : "Offline"}
                    </small>
                  </div>
                </div>

                <div className="service-row git-service-row">
                  <span
                    className={`service-dot ${
                      controlCenter?.git.available
                        ? "online"
                        : "offline"
                    }`}
                  />
                  <div>
                    <strong>Git Repository</strong>
                    <small>
                      {controlCenter?.git.commit
                        ? `Commit ${controlCenter.git.commit}`
                        : "Durum alınamadı"}
                    </small>
                  </div>
                </div>
              </div>
            </article>

            <article className="control-status-card model-card" id="models">
              <div className="control-card-title">
                <span>Local Modeller</span>
                <small>
                  {controlCenter?.services.ollama.models
                    .length ?? 0}{" "}
                  model
                </small>
              </div>

              <div className="model-list">
                {controlCenter?.services.ollama.models
                  .slice(0, 5)
                  .map((model) => (
                    <div
                      className="model-row"
                      key={model.name}
                    >
                      <span className="model-icon">
                        AI
                      </span>

                      <span>{model.name}</span>
                    </div>
                  ))}

                {controlCenter &&
                  controlCenter.services.ollama.models
                    .length === 0 && (
                    <div className="model-empty">
                      Yüklü model bulunamadı.
                    </div>
                  )}
              </div>
            </article>
          </div>

          <article className="pipeline-card">
            <div className="pipeline-header">
              <div>
                <span className="section-kicker">
                  AGENT PIPELINE
                </span>

                <strong>
                  {selectedTask
                    ? selectedTask.task_id
                    : "Görev seç"}
                </strong>
              </div>

              <div className="pipeline-progress-text">
                {pipeline
                  ? `${pipeline.progress_percent}%`
                  : "—"}
              </div>
            </div>

            <div className="pipeline-track">
              {pipeline ? (
                pipeline.stages.map(
                  (stage, index) => (
                    <div
                      className="pipeline-stage-wrap"
                      key={stage.id}
                    >
                      <div
                        className={`pipeline-stage pipeline-${stage.status}`}
                      >
                        <span className="pipeline-stage-dot">
                          {stage.status === "success"
                            ? "✓"
                            : stage.status === "failed"
                              ? "!"
                              : stage.status === "rejected"
                                ? "×"
                                : index + 1}
                        </span>

                        <span className="pipeline-stage-label">
                          {stage.label}
                        </span>
                      </div>

                      {index <
                        pipeline.stages.length - 1 && (
                        <span
                          className={`pipeline-connector ${
                            stage.status ===
                              "success"
                              ? "complete"
                              : ""
                          }`}
                        />
                      )}
                    </div>
                  ),
                )
              ) : (
                <div className="pipeline-empty">
                  Pipeline durumunu görmek için
                  bir görev seç.
                </div>
              )}
            </div>
          </article>
        </section>

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
                  disabled={
                    submitting ||
                    !prompt.trim() ||
                    !selectedProject
                  }
                >
                  {submitting ? "Başlatılıyor..." : "Görevi Başlat"}
                </button>
              </div>
            </form>

            <section className="task-list-panel" id="tasks">
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
                    <strong>Henüz görev yok.</strong>
                    <span>
                      Yukarıdaki alandan ilk görevi oluşturabilirsin.
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
                  Ayrıntıları, diff çıktısını ve işlem butonlarını
                  görmek için listeden bir görev seç.
                </span>
              </div>
            )}

            {selectedTask && (
              <>
                <div className="task-summary-panel">
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

                </div>

                <div className="task-output-panel">
                  <div className="output-panel-heading">
                    <div>
                      <span className="section-kicker">
                        LIVE EXECUTION
                      </span>
                      <h2>Agent ?al??ma Alan?</h2>
                    </div>

                    <span
                      className={`status status-${selectedTask.state}`}
                    >
                      {stateLabels[selectedTask.state] ??
                        selectedTask.state}
                    </span>
                  </div>

                  <div className="live-log-section">
                  <div className="diff-heading">
                    <div>
                      <span>Canlı Log</span>
                      <small>AI ajanının anlık işlem adımları</small>
                    </div>
                  </div>

                  <pre className="live-log-view">
                    {liveLogs.length > 0
                      ? liveLogs.join("\n")
                      : "Henüz log kaydı yok."}
                  </pre>
                </div>

                <div className="diff-section">
                  <div className="diff-heading">
                    <div>
                      <span>Git Diff</span>
                      <small>AI tarafından oluşturulan değişiklikler</small>
                    </div>

                    <button
                      className="secondary-button"
                      disabled={
                        ![
                          "ready_for_approval",
                          "approved",
                          "rejected",
                        ].includes(selectedTask.state) ||
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
                      ([
                        "ready_for_approval",
                        "approved",
                        "rejected",
                      ].includes(selectedTask.state)
                        ? "Diff görüntülemek için butona bas."
                        : "Bu görev için kullanılabilir diff yok.")}
                  </pre>
                </div>
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
