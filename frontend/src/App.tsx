import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react"

import {
  approveTask,
  createProject,
  createTask,
  getControlCenterStatus,
  getTaskDiff,
  getTaskPipeline,
  listProjects,
  listTasks,
  openProject,
  openProjectTerminal,
  rejectTask,
  retryTask,
  updateProject,
  testModel,
  type ControlCenterStatus,
  type Project,
  type Task,
  type TaskPipeline,
} from "./api"

import { UiIcon } from "./UiIcon"

import "./App.css"

const stateLabels: Record<string, string> = {
  queued: "S\u0131rada",
  running: "\u0130\u015fleniyor",
  ready_for_approval: "Onay Bekliyor",
  approved: "Tamamland\u0131",
  rejected: "Reddedildi",
  failed: "Ba\u015far\u0131s\u0131z",
}

const defaultPipeline = [
  { id: "task", label: "Kullan\u0131c\u0131 G\u00f6revi" },
  { id: "worktree", label: "Worktree" },
  { id: "repo_analysis", label: "Repo Analizi" },
  { id: "model", label: "Lokal Model" },
  { id: "patch", label: "Patch Olu\u015fturma" },
  { id: "tests", label: "Docker Test" },
  { id: "diff", label: "Diff Olu\u015fturma" },
  { id: "approval", label: "\u0130nsan Onay\u0131" },
]

const pipelineTools: Record<string, string> = {
  task: "Orchestrator",
  worktree: "Git Worktree",
  repo_analysis: "Kod Analizi",
  model: "Ollama",
  patch: "Patch Do\u011frulama",
  tests: "Docker Sandbox",
  diff: "Git Diff",
  approval: "Manuel Onay",
}

function formatTime(value: string | null) {
  if (!value) return "\u2014"

  return new Intl.DateTimeFormat("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value))
}

function formatDate(value: string | null) {
  if (!value) return "\u2014"

  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function formatBytes(value: number | null) {
  if (value == null) return "\u2014"

  const gb = value / 1024 / 1024 / 1024

  return `${gb.toFixed(gb >= 10 ? 0 : 1)} GB`
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] =
    useState<string | null>(null)

  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedTaskId, setSelectedTaskId] =
    useState<string | null>(null)

  const [prompt, setPrompt] = useState("")
  const [maxAttempts, setMaxAttempts] = useState(2)

  const [showTaskComposer, setShowTaskComposer] =
    useState(false)

  const [showProjectComposer, setShowProjectComposer] =
    useState(false)

  const [newProjectName, setNewProjectName] =
    useState("")

  const [newProjectPath, setNewProjectPath] =
    useState("")

  const [submitting, setSubmitting] =
    useState(false)

  const [projectSubmitting, setProjectSubmitting] =
    useState(false)

  const [actionLoading, setActionLoading] =
    useState(false)

  const [loadingDiff, setLoadingDiff] =
    useState(false)

  const [error, setError] =
    useState<string | null>(null)

  const [backendOnline, setBackendOnline] =
    useState(true)

  const [liveLogs, setLiveLogs] =
    useState<string[]>([])

  const [logQuery, setLogQuery] =
    useState("")

  const [diff, setDiff] =
    useState("")

  const [controlCenter, setControlCenter] =
    useState<ControlCenterStatus | null>(null)

  const [pipeline, setPipeline] =
    useState<TaskPipeline | null>(null)

  const [activeProjectTab, setActiveProjectTab] =
    useState<"overview" | "running" | "history" | "settings">(
      "overview",
    )

  const [activeMainView, setActiveMainView] =
    useState<"dashboard" | "models">(
      "dashboard",
    )

  const [selectedModel, setSelectedModel] =
    useState<string | null>(null)


  const [modelTestPrompt, setModelTestPrompt] =
    useState(
      "Python ile basit bir fibonacci fonksiyonu yaz ve k\u0131saca a\u00e7\u0131kla.",
    )

  const [modelTestResponse, setModelTestResponse] =
    useState("")

  const [modelTestDuration, setModelTestDuration] =
    useState<number | null>(null)

  const [modelTestRunning, setModelTestRunning] =
    useState(false)

  const [modelTestError, setModelTestError] =
    useState<string | null>(null)

  const [projectSettingsName, setProjectSettingsName] =
    useState("")

  const [projectSettingsPath, setProjectSettingsPath] =
    useState("")

  const [projectSettingsSaving, setProjectSettingsSaving] =
    useState(false)

  const selectedProject = useMemo(
    () =>
      projects.find(
        (project) =>
          project.project_id === selectedProjectId,
      ) ?? null,
    [projects, selectedProjectId],
  )

  useEffect(() => {
    setProjectSettingsName(
      selectedProject?.name ?? "",
    )

    setProjectSettingsPath(
      selectedProject?.path ?? "",
    )

    setActiveProjectTab("overview")
  }, [selectedProject])

  const selectedTask = useMemo(
    () =>
      tasks.find(
        (task) =>
          task.task_id === selectedTaskId,
      ) ?? null,
    [tasks, selectedTaskId],
  )

  const availableModels = useMemo<string[]>(
    () =>
      (
        controlCenter?.services.ollama.models ?? []
      ).map((model) => model.name),
    [controlCenter?.services.ollama.models],
  )

  useEffect(() => {
    if (availableModels.length === 0) {
      setSelectedModel(null)
      return
    }

    if (
      !selectedModel ||
      !availableModels.includes(selectedModel)
    ) {
      const preferredModels = [
        "qwen2.5-coder:14b",
        "llama3.1:8b",
      ]

      const preferredModel =
        preferredModels.find((model) =>
          availableModels.includes(model),
        ) ?? availableModels[0]

      setSelectedModel(preferredModel)
    }
  }, [availableModels, selectedModel])

  const runningTasks = useMemo(
    () =>
      tasks.filter((task) =>
        [
          "queued",
          "running",
          "ready_for_approval",
        ].includes(task.state),
      ),
    [tasks],
  )

  const historyTasks = useMemo(
    () =>
      tasks.filter((task) =>
        [
          "approved",
          "rejected",
          "failed",
        ].includes(task.state),
      ),
    [tasks],
  )

  const filteredLogs = useMemo(() => {
    const query = logQuery.trim().toLowerCase()

    if (!query) {
      return liveLogs
    }

    return liveLogs.filter((log) =>
      log.toLowerCase().includes(query),
    )
  }, [liveLogs, logQuery])

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

      setBackendOnline(true)
    } catch (err) {
      setBackendOnline(false)

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
      setSelectedTaskId(null)
      return
    }

    try {
      const data = await listTasks(
        selectedProjectId,
      )

      const ordered = data.slice().reverse()

      setTasks(ordered)

      setSelectedTaskId((current) => {
        if (
          current &&
          ordered.some(
            (task) =>
              task.task_id === current,
          )
        ) {
          return current
        }

        return ordered[0]?.task_id ?? null
      })

      setBackendOnline(true)
    } catch (err) {
      setBackendOnline(false)

      setError(
        err instanceof Error
          ? err.message
          : "G\u00f6revler y\u00fcklenemedi.",
      )
    }
  }, [selectedProjectId])

  const loadControlCenter =
    useCallback(async () => {
      if (!selectedProjectId) {
        setControlCenter(null)
        return
      }

      try {
        const data =
          await getControlCenterStatus(
            selectedProjectId,
          )

        setControlCenter(data)
      } catch {
        setControlCenter(null)
      }
    }, [selectedProjectId])

  const loadPipeline =
    useCallback(async () => {
      if (!selectedTaskId) {
        setPipeline(null)
        return
      }

      try {
        const data =
          await getTaskPipeline(
            selectedTaskId,
          )

        setPipeline(data)
      } catch {
        setPipeline(null)
      }
    }, [selectedTaskId])

  useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  useEffect(() => {
    void loadTasks()

    const timer = window.setInterval(() => {
      void loadTasks()
    }, 2000)

    return () =>
      window.clearInterval(timer)
  }, [loadTasks])

  useEffect(() => {
    void loadControlCenter()

    const timer = window.setInterval(() => {
      void loadControlCenter()
    }, 5000)

    return () =>
      window.clearInterval(timer)
  }, [loadControlCenter])

  useEffect(() => {
    void loadPipeline()

    if (!selectedTaskId) {
      return
    }

    const timer = window.setInterval(() => {
      void loadPipeline()
    }, 2000)

    return () =>
      window.clearInterval(timer)
  }, [loadPipeline, selectedTaskId])

  useEffect(() => {
    setDiff("")
    setLiveLogs([])
    setLogQuery("")

    if (!selectedTaskId) {
      return
    }

    const source = new EventSource(
      `/api/tasks/${selectedTaskId}/events`,
    )

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(
          event.data,
        ) as {
          message?: string
        }

        if (payload.message) {
          setLiveLogs((current) => [
            ...current,
            payload.message as string,
          ])
        }
      } catch {
        // Ignore malformed events.
      }
    }

    source.addEventListener(
      "done",
      () => {
        source.close()
      },
    )

    source.onerror = () => {
      source.close()
    }

    return () => {
      source.close()
    }
  }, [
    selectedTaskId,
    selectedTask?.started_at,
  ])

  async function handleProjectSettingsSave(
    event: FormEvent,
  ) {
    event.preventDefault()

    if (!selectedProject) {
      return
    }

    const cleanName =
      projectSettingsName.trim()

    const cleanPath =
      projectSettingsPath.trim()

    if (!cleanName || !cleanPath) {
      setError(
        "Proje ad\u0131 ve yolu zorunludur.",
      )
      return
    }

    setProjectSettingsSaving(true)
    setError(null)

    try {
      await updateProject(
        selectedProject.project_id,
        cleanName,
        cleanPath,
      )

      await loadProjects()
      await loadControlCenter()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Proje ayarlar\u0131 kaydedilemedi.",
      )
    } finally {
      setProjectSettingsSaving(false)
    }
  }

  async function handleModelTest() {
    if (!selectedModel) {
      return
    }

    const prompt = modelTestPrompt.trim()

    if (!prompt) {
      setModelTestError(
        "Test promptu bo\u015f olamaz.",
      )
      return
    }

    setModelTestRunning(true)
    setModelTestError(null)
    setModelTestResponse("")
    setModelTestDuration(null)

    try {
      const result = await testModel(
        selectedModel,
        prompt,
      )

      setModelTestResponse(
        result.response,
      )

      setModelTestDuration(
        result.duration_ms,
      )
    } catch (err) {
      const rawMessage =
        err instanceof Error
          ? err.message
          : "Model testi ba\u015far\u0131s\u0131z oldu."

      const normalized =
        rawMessage.toLowerCase()

      const resourceFailure =
        normalized.includes("cuda") ||
        normalized.includes("out of memory") ||
        normalized.includes("llama-server process has terminated") ||
        normalized.includes("stack-based buffer") ||
        normalized.includes("shared object initialization failed")

      if (resourceFailure) {
        const fallbackModel =
          availableModels.find(
            (model) =>
              model !== selectedModel &&
              model.includes("14b"),
          ) ??
          availableModels.find(
            (model) =>
              model !== selectedModel &&
              model.includes("8b"),
          ) ??
          availableModels.find(
            (model) =>
              model !== selectedModel,
          )

        setModelTestError(
          fallbackModel
            ? `Model ba\u015flat\u0131lamad\u0131. GPU/CUDA veya bellek s\u0131n\u0131r\u0131na tak\u0131lm\u0131\u015f olabilir. Alternatif olarak ${fallbackModel} modelini deneyebilirsin.`
            : "Model ba\u015flat\u0131lamad\u0131. GPU/CUDA veya bellek s\u0131n\u0131r\u0131na tak\u0131lm\u0131\u015f olabilir.",
        )
      } else {
        setModelTestError(rawMessage)
      }
    } finally {
      setModelTestRunning(false)
    }
  }

  async function handleCreateTask(
    event: FormEvent,
  ) {
    event.preventDefault()

    const cleanPrompt = prompt.trim()

    if (
      !cleanPrompt ||
      !selectedProject
    ) {
      return
    }

    setSubmitting(true)
    setError(null)

    try {
      const task = await createTask(
        cleanPrompt,
        maxAttempts,
        selectedProject.project_id,
      )

      setPrompt("")
      setShowTaskComposer(false)
      setSelectedTaskId(task.task_id)

      await loadTasks()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "G\u00f6rev olu\u015fturulamad\u0131.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCreateProject(
    event: FormEvent,
  ) {
    event.preventDefault()

    const cleanName =
      newProjectName.trim()

    const cleanPath =
      newProjectPath.trim()

    if (!cleanName || !cleanPath) {
      return
    }

    setProjectSubmitting(true)
    setError(null)

    try {
      const project =
        await createProject(
          cleanName,
          cleanPath,
        )

      await loadProjects()

      setSelectedProjectId(
        project.project_id,
      )

      setNewProjectName("")
      setNewProjectPath("")
      setShowProjectComposer(false)
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

  async function handleDiff() {
    if (!selectedTask) return

    setLoadingDiff(true)
    setError(null)

    try {
      const result =
        await getTaskDiff(
          selectedTask.task_id,
        )

      setDiff(
        result.diff ||
          "De\u011fi\u015fiklik bulunamad\u0131.",
      )
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Diff al\u0131namad\u0131.",
      )
    } finally {
      setLoadingDiff(false)
    }
  }

  async function handleAction(
    action:
      | "approve"
      | "reject"
      | "retry",
  ) {
    if (!selectedTask) return

    setActionLoading(true)
    setError(null)

    try {
      if (action === "approve") {
        await approveTask(
          selectedTask.task_id,
        )
      }

      if (action === "reject") {
        await rejectTask(
          selectedTask.task_id,
        )
      }

      if (action === "retry") {
        await retryTask(
          selectedTask.task_id,
        )
      }

      await loadTasks()
      await loadControlCenter()
      await loadPipeline()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "\u0130\u015flem tamamlanamad\u0131.",
      )
    } finally {
      setActionLoading(false)
    }
  }

  function scrollToLogs() {
    const container = document.querySelector(
      ".center-stage",
    ) as HTMLElement | null

    const target = document.getElementById(
      "live-logs",
    )

    if (!container || !target) {
      return
    }

    const containerRect =
      container.getBoundingClientRect()

    const targetRect =
      target.getBoundingClientRect()

    const targetTop =
      container.scrollTop +
      targetRect.top -
      containerRect.top -
      12

    container.scrollTo({
      top: targetTop,
      behavior: "smooth",
    })
  }

  const pipelineStages =
    pipeline?.stages ??
    defaultPipeline.map((stage) => ({
      ...stage,
      status: "pending" as const,
    }))

  const systemHealthy =
    backendOnline &&
    controlCenter?.services.docker.online &&
    controlCenter?.services.ollama.online

  const ramUsed =
    controlCenter?.system.memory.total_bytes != null &&
    controlCenter?.system.memory.available_bytes != null
      ? controlCenter.system.memory.total_bytes -
        controlCenter.system.memory.available_bytes
      : null

  return (
    <div className="factory-shell">
      <header className="factory-topbar">
        <div className="factory-brand">
          <div className="factory-logo"><UiIcon name="factory" /></div>

          <div className="factory-brand-copy">
            <strong>
              AI Software Factory
            </strong>

            <small>
              Local-First
              <i>{"\u2022"}</i>
              Build More
              <i>{"\u2022"}</i>
              Your Machine, Your Rules
            </small>
          </div>
        </div>

        <nav className="main-nav">
          <button
            className={
              activeMainView === "dashboard"
                ? "active"
                : ""
            }
            onClick={() =>
              setActiveMainView("dashboard")
            }
          >
            <UiIcon name="dashboard" />
            {"Kontrol Paneli"}
          </button>

          <button
            onClick={() => {
              setActiveMainView("dashboard")
              setActiveProjectTab("running")
            }}
          >
            <UiIcon name="tasks" />
            {"G\u00f6revler"}
          </button>

          <button
            onClick={() =>
              setActiveMainView("dashboard")
            }
          >
            <UiIcon name="projects" />
            {"Projeler"}
          </button>

          <button
            className={
              activeMainView === "models"
                ? "active"
                : ""
            }
            onClick={() =>
              setActiveMainView("models")
            }
          >
            <UiIcon name="models" />
            {"Modeller"}
          </button>

          <button
            onClick={() => {
              setActiveMainView("dashboard")
              setActiveProjectTab("settings")
            }}
          >
            <UiIcon name="settings" />
            {"Ayarlar"}
          </button>
        </nav>

        <div
          className={`system-pill ${
            systemHealthy
              ? "healthy"
              : "warning"
          }`}
        >
          <span className="system-light" />

          <div>
            <strong>
              {systemHealthy
                ? "Sistem \u00c7al\u0131\u015f\u0131yor"
                : "Sistem Kontrol Ediliyor"}
            </strong>

            <small>
              {systemHealthy
                ? "T\u00fcm servisler haz\u0131r"
                : "Servis durumlar\u0131n\u0131 kontrol et"}
            </small>
          </div>
        </div>
      </header>

      <aside className="left-sidebar">
        <section className="rail-section">
          <div className="rail-heading">
            <h2>{"Projeler"}</h2>

            <button
              className="rail-add-button"
              onClick={() =>
                setShowProjectComposer(
                  (current) =>
                    !current,
                )
              }
            >
              + {"Yeni Proje"}
            </button>
          </div>

          {showProjectComposer && (
            <form
              className="rail-form"
              onSubmit={
                handleCreateProject
              }
            >
              <input
                value={newProjectName}
                onChange={(event) =>
                  setNewProjectName(
                    event.target.value,
                  )
                }
                placeholder="Proje ad\u0131"
              />

              <input
                value={newProjectPath}
                onChange={(event) =>
                  setNewProjectPath(
                    event.target.value,
                  )
                }
                placeholder="C:\Projects\EduTest"
              />

              <button
                type="submit"
                disabled={
                  projectSubmitting
                }
              >
                {projectSubmitting
                  ? "Ekleniyor..."
                  : "Projeyi Ekle"}
              </button>
            </form>
          )}

          <div className="project-rail-list">
            {projects.map(
              (project) => (
                <button
                  key={
                    project.project_id
                  }
                  className={`project-rail-card ${
                    selectedProjectId ===
                    project.project_id
                      ? "active"
                      : ""
                  }`}
                  onClick={() =>
                    setSelectedProjectId(
                      project.project_id,
                    )
                  }
                >
                  <span className="project-folder"><UiIcon name="folder" /></span>

                  <span className="project-rail-copy">
                    <strong>
                      {project.name}
                    </strong>

                    <small>
                      {project.path}
                    </small>
                  </span>
                </button>
              ),
            )}
          </div>
        </section>

        <section
          className="rail-section task-rail-section"
          id="task-list"
        >
          <div className="rail-heading">
            <h2>{"G\u00f6revler"}</h2>

            <button
              className="rail-add-button"
              onClick={() =>
                setShowTaskComposer(
                  (current) =>
                    !current,
                )
              }
              disabled={
                !selectedProject
              }
            >
              + {"Yeni G\u00f6rev"}
            </button>
          </div>

          {showTaskComposer && (
            <form
              className="rail-form"
              onSubmit={
                handleCreateTask
              }
            >
              <textarea
                value={prompt}
                onChange={(event) =>
                  setPrompt(
                    event.target.value,
                  )
                }
                rows={4}
                placeholder="AI ajan\u0131na g\u00f6revini yaz..."
              />

              <div className="rail-form-row">
                <select
                  value={maxAttempts}
                  onChange={(event) =>
                    setMaxAttempts(
                      Number(
                        event.target
                          .value,
                      ),
                    )
                  }
                >
                  {[1, 2, 3, 4, 5].map(
                    (value) => (
                      <option
                        key={value}
                        value={value}
                      >
                        {value} deneme
                      </option>
                    ),
                  )}
                </select>

                <button
                  type="submit"
                  disabled={
                    submitting ||
                    !prompt.trim()
                  }
                >
                  {submitting
                    ? "Ba\u015flat\u0131l\u0131yor"
                    : "Ba\u015flat"}
                </button>
              </div>
            </form>
          )}

          <div className="task-rail-list">
            {tasks.length === 0 && (
              <div className="rail-empty">
                {"Hen\u00fcz g\u00f6rev yok."}
              </div>
            )}

            {tasks.map((task) => (
              <button
                key={task.task_id}
                className={`task-rail-card ${
                  selectedTaskId ===
                  task.task_id
                    ? "active"
                    : ""
                }`}
                onClick={() =>
                  setSelectedTaskId(
                    task.task_id,
                  )
                }
              >
                <span
                  className={`task-state-light state-${task.state}`}
                />

                <span className="task-rail-copy">
                  <strong>
                    {task.task_id}
                  </strong>

                  <span>
                    {task.prompt}
                  </span>

                  <small>
                    {stateLabels[
                      task.state
                    ] ?? task.state}
                    <i>{"\u2022"}</i>
                    {formatTime(
                      task.started_at,
                    )}
                  </small>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="rail-section quick-actions">
          <h2>
            {"H\u0131zl\u0131 \u0130\u015flemler"}
          </h2>

          <button
            disabled={!selectedProject}
            onClick={() => {
              if (!selectedProject) return

              void openProjectTerminal(
                selectedProject.project_id,
              ).catch((err) => {
                setError(
                  err instanceof Error
                    ? err.message
                    : "Terminal a\u00e7\u0131lamad\u0131.",
                )
              })
            }}
          >
            <UiIcon name="terminal" />
            {"Terminali A\u00e7"}
          </button>

          <button onClick={scrollToLogs}>
            <UiIcon name="logs" />
            {"Loglar\u0131 G\u00f6r\u00fcnt\u00fcle"}
          </button>

          <button>
            <UiIcon name="settings" />
            {"Ayarlar\u0131 D\u00fczenle"}
          </button>

          <button>
            <UiIcon name="models" />
            {"Model Testi Yap"}
          </button>
        </section>
      </aside>

      <main
        className={`center-stage ${
          activeMainView === "models"
            ? "models-active"
            : "dashboard-active"
        }`}
      >

        {activeMainView === "models" && (
          <section className="models-page">
            <div className="models-page-header">
              <div>
                <span className="models-page-kicker">
                  LOCAL AI MODELS
                </span>

                <h1>
                  {"Yerel AI Modelleri"}
                </h1>

                <p>
                  {"Ollama \u00fczerinden bu makinede kullan\u0131labilir modeller."}
                </p>
              </div>

              <div
                className={`ollama-health ${
                  controlCenter?.services.ollama.online
                    ? "online"
                    : "offline"
                }`}
              >
                <span />

                <strong>
                  {controlCenter?.services.ollama.online
                    ? "Ollama \u00c7al\u0131\u015f\u0131yor"
                    : "Ollama Kapal\u0131"}
                </strong>
              </div>
            </div>

            <div className="models-summary-grid">
              <div>
                <span>{"Kurulu Model"}</span>
                <strong>
                  {availableModels.length}
                </strong>
              </div>

              <div>
                <span>Ollama</span>
                <strong>
                  {controlCenter?.services.ollama.online
                    ? "ONLINE"
                    : "OFFLINE"}
                </strong>
              </div>

              <div>
                <span>{"Se\u00e7ili Model"}</span>
                <strong>
                  {selectedModel ?? "\u2014"}
                </strong>
              </div>
            </div>

            <div className="models-layout">
              <section className="model-library-panel">
                <div className="model-section-title">
                  <div>
                    <UiIcon name="models" />

                    <div>
                      <strong>
                        {"Model K\u00fct\u00fcphanesi"}
                      </strong>

                      <small>
                        {"Bu bilgisayarda kurulu modeller"}
                      </small>
                    </div>
                  </div>

                  <span>
                    {availableModels.length}
                  </span>
                </div>

                <div className="model-library-list">
                  {availableModels.length === 0 && (
                    <div className="models-empty">
                      {controlCenter?.services.ollama.online
                        ? "Kurulu Ollama modeli bulunamad\u0131."
                        : "Ollama servisine ula\u015f\u0131lam\u0131yor."}
                    </div>
                  )}

                  {availableModels.map((model) => (
                    <button
                      key={model}
                      className={`model-library-item ${
                        selectedModel === model
                          ? "selected"
                          : ""
                      }`}
                      onClick={() =>
                        setSelectedModel(model)
                      }
                    >
                      <div className="model-library-icon">
                        <UiIcon name="model" />
                      </div>

                      <div className="model-library-copy">
                        <strong>{model}</strong>

                        <span>
                          Ollama Local Model
                        </span>
                      </div>

                      <span
                        className="model-online-dot"
                        title="Online"
                      />
                    </button>
                  ))}
                </div>
              </section>

              <section className="selected-model-panel">
                {!selectedModel ? (
                  <div className="selected-model-empty">
                    <UiIcon name="models" />

                    <strong>
                      {"Model se\u00e7ilmedi"}
                    </strong>

                    <span>
                      {"Detaylar\u0131 g\u00f6rmek i\u00e7in listeden bir model se\u00e7."}
                    </span>
                  </div>
                ) : (
                  <>
                    <div className="selected-model-heading">
                      <div className="selected-model-logo">
                        <UiIcon name="model" />
                      </div>

                      <div>
                        <span>
                          SELECTED MODEL
                        </span>

                        <h2>
                          {selectedModel}
                        </h2>
                      </div>
                    </div>

                    <div className="selected-model-status">
                      <div>
                        <span>{"Sa\u011fl\u0131k"}</span>

                        <strong>
                          {controlCenter?.services.ollama.online
                            ? "Haz\u0131r"
                            : "Kapal\u0131"}
                        </strong>
                      </div>

                      <div>
                        <span>Provider</span>
                        <strong>Ollama</strong>
                      </div>

                      <div>
                        <span>{"\u00c7al\u0131\u015fma"}</span>
                        <strong>Local</strong>
                      </div>
                    </div>

                    <div className="model-test-panel">
                      <div className="model-test-title">
                        <UiIcon name="terminal" />

                        <div>
                          <strong>
                            {"Model Testi"}
                          </strong>

                          <span>
                            {"Se\u00e7ili modele do\u011frudan prompt g\u00f6nder."}
                          </span>
                        </div>
                      </div>

                      <textarea
                        className="model-test-input"
                        value={modelTestPrompt}
                        onChange={(event) =>
                          setModelTestPrompt(
                            event.target.value,
                          )
                        }
                        placeholder={
                          "Modele g\u00f6ndermek istedi\u011fin prompt..."
                        }
                        rows={6}
                      />

                      <div className="model-test-actions">
                        <button
                          type="button"
                          className="model-test-button"
                          disabled={
                            modelTestRunning ||
                            !selectedModel
                          }
                          onClick={() =>
                            void handleModelTest()
                          }
                        >
                          <UiIcon name="running" />

                          {modelTestRunning
                            ? "Model \u00e7al\u0131\u015f\u0131yor..."
                            : "Testi Ba\u015flat"}
                        </button>

                        {modelTestDuration != null && (
                          <span className="model-test-duration">
                            {(modelTestDuration / 1000).toFixed(2)}
                            {" sn"}
                          </span>
                        )}
                      </div>

                      {modelTestError && (
                        <div className="model-test-error">
                          {modelTestError}
                        </div>
                      )}

                      {modelTestResponse && (
                        <div className="model-test-result">
                          <div className="model-test-result-head">
                            <strong>
                              MODEL RESPONSE
                            </strong>

                            <span>
                              {selectedModel}
                            </span>
                          </div>

                          <pre>
                            {modelTestResponse}
                          </pre>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </section>
            </div>
          </section>
        )}

        {error && (
          <div className="error-banner">
            <strong>
              {"\u0130\u015flem Hatas\u0131"}
            </strong>

            <span>{error}</span>

            <button
              onClick={() =>
                setError(null)
              }
            >
              ?
            </button>
          </div>
        )}

        <section className="project-header-card">
          <div className="project-header-top">
            <div className="project-header-main">
              <span className="project-large-icon"><UiIcon name="projects" /></span>

              <div>
                <h1>
                  {selectedProject?.name ??
                    "Proje Se\u00e7"}
                </h1>

                <p>
                  {selectedProject?.path ??
                    "Sol panelden bir proje se\u00e7."}
                </p>
              </div>
            </div>

            <button
              className="open-project-button"
              type="button"
              disabled={!selectedProject}
              onClick={() => {
                if (!selectedProject) return

                void openProject(
                  selectedProject.project_id,
                ).catch((err) => {
                  setError(
                    err instanceof Error
                      ? err.message
                      : "Proje a??lamad?.",
                  )
                })
              }}
            >
              <UiIcon name="open" />
              {"Projeyi A\u00e7"}
            </button>
          </div>

          <nav className="project-tabs">
            <button
              className={
                activeProjectTab === "overview"
                  ? "active"
                  : ""
              }
              onClick={() =>
                setActiveProjectTab("overview")
              }
            >
              <UiIcon name="overview" />
              {"Genel Bak\u0131\u015f"}
            </button>

            <button
              className={
                activeProjectTab === "running"
                  ? "active"
                  : ""
              }
              onClick={() =>
                setActiveProjectTab("running")
              }
            >
              <UiIcon name="running" />
              {"\u00c7al\u0131\u015fan G\u00f6rev"}
            </button>

            <button
              className={
                activeProjectTab === "history"
                  ? "active"
                  : ""
              }
              onClick={() =>
                setActiveProjectTab("history")
              }
            >
              <UiIcon name="history" />
              {"Ge\u00e7mi\u015f"}
            </button>

            <button
              className={
                activeProjectTab === "settings"
                  ? "active"
                  : ""
              }
              onClick={() =>
                setActiveProjectTab("settings")
              }
            >
              <UiIcon name="settings" />
              {"Proje Ayarlar\u0131"}
            </button>
          </nav>
        </section>

        {activeProjectTab === "overview" && (
          <>
        <section
          className={`active-task-card ${
            activeProjectTab !== "overview"
              ? "tab-hidden"
              : ""
          }`}
        >
          <div className="active-task-head">
            <div>
              <span className="task-id-title"><UiIcon name="task" />{" "}
                {selectedTask?.task_id ??
                  "G\u00f6rev Se\u00e7ilmedi"}
              </span>

              <h2>
                {selectedTask?.prompt ??
                  "Pipeline durumunu g\u00f6rmek i\u00e7in bir g\u00f6rev se\u00e7."}
              </h2>
            </div>

            <div className="active-task-state">
              <span
                className={`state-badge state-${selectedTask?.state ?? "queued"}`}
              >
                {stateLabels[
                  selectedTask?.state ??
                    "queued"
                ] ??
                  selectedTask?.state}
              </span>

              <small>
                {"Ba\u015flang\u0131\u00e7:"}{" "}
                {formatTime(
                  selectedTask?.started_at ??
                    null,
                )}
              </small>
            </div>
          </div>

          <div className="pipeline-flow">
            {pipelineStages.map(
              (stage) => (
                <div
                  className="pipeline-node-wrap"
                  key={stage.id}
                >
                  <div
                    className={`pipeline-node stage-${stage.status}`}
                  >
                    <span className="pipeline-node-icon">
                      <UiIcon
                        name={
                          stage.status === "success"
                            ? "check"
                            : stage.id
                        }
                      />
                    </span>

                    <strong>
                      {stage.label}
                    </strong>
                  </div>

                  <small className="pipeline-caption">
                    {stage.status ===
                    "success"
                      ? "Tamamland\u0131"
                      : stage.status ===
                          "active"
                        ? "\u00c7al\u0131\u015f\u0131yor..."
                        : stage.status ===
                            "waiting"
                          ? "Onay Bekliyor"
                          : stage.status ===
                              "failed"
                            ? "Ba\u015far\u0131s\u0131z"
                            : stage.status ===
                                "rejected"
                              ? "Reddedildi"
                              : "Bekliyor"}
                  </small>
                </div>
              ),
            )}
          </div>

          <div className="pipeline-tools">
            {pipelineStages.map((stage) => (
              <div
                key={stage.id}
                className="pipeline-tool"
              >
                <UiIcon name={stage.id} />

                <div>
                  <strong>
                    {pipelineTools[stage.id] ??
                      stage.label}
                  </strong>

                  <small>
                    {stage.id === "task"
                      ? "(Python)"
                      : stage.id === "worktree"
                        ? "(İzolasyon)"
                        : stage.id === "repo_analysis"
                          ? "(Repo Context)"
                          : stage.id === "model"
                            ? selectedTask?.model ??
                              "Local Model"
                            : stage.id === "patch"
                              ? "(Güvenlik Kontrolü)"
                              : stage.id === "tests"
                                ? "(Test / Build / Lint)"
                                : stage.id === "diff"
                                  ? "(Değişiklikler)"
                                  : stage.id === "approval"
                                    ? "(Merge)"
                                    : ""}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section
          className={`lower-workspace ${
            activeProjectTab !== "overview"
              ? "tab-hidden"
              : ""
          }`}
        >
          <article
            className="console-card"
            id="live-logs"
          >
            <div className="panel-titlebar">
              <div>
                <UiIcon name="logs" />
                <strong>
                  {"Canl\u0131 Loglar"}
                </strong>
              </div>

              <label className="autosave-label">
                <span className="toggle on" />
                {"Otomatik Kayd\u0131rma"}
              </label>
            </div>

            <div className="console-body">
              {filteredLogs.length >
              0 ? (
                filteredLogs.map(
                  (log, index) => (
                    <div
                      className="console-line"
                      key={`${index}-${log}`}
                    >
                      <span className="console-time">
                        [
                        {String(
                          index + 1,
                        ).padStart(
                          2,
                          "0",
                        )}
                        ]
                      </span>

                      <span className="console-tag">
                        INFO
                      </span>

                      <span className="console-message">
                        {log}
                      </span>
                    </div>
                  ),
                )
              ) : (
                <div className="console-empty">
                  {selectedTask
                    ? "Hen\u00fcz log kayd\u0131 yok."
                    : "Canl\u0131 loglar i\u00e7in bir g\u00f6rev se\u00e7."}
                </div>
              )}
            </div>

            <div className="console-search">
              <input
                value={logQuery}
                onChange={(event) =>
                  setLogQuery(
                    event.target.value,
                  )
                }
                placeholder="Loglarda ara..."
              />

              <UiIcon name="search" /></div>

            {diff && (
              <pre className="inline-diff">
                {diff}
              </pre>
            )}
          </article>

          <article className="result-card">
            <div className="panel-titlebar">
              <div>
                <UiIcon name="result" />
                <strong>
                  {"G\u00f6rev Sonucu"}
                </strong>
              </div>

              <span
                className={`result-status state-${selectedTask?.state ?? "queued"}`}
              >
                {selectedTask?.state ===
                "ready_for_approval"
                  ? "Onay Bekliyor"
                  : stateLabels[
                      selectedTask?.state ??
                        "queued"
                    ] ??
                    "\u2014"}
              </span>
            </div>

            <div className="result-details">
              <div>
                <span>
                  {"Testler"}
                </span>

                <strong
                  className={
                    selectedTask?.test_result ===
                    "passed"
                      ? "good"
                      : ""
                  }
                >
                  {selectedTask?.test_result ??
                    "\u2014"}
                </strong>
              </div>

              <div>
                <span>
                  {"Deneme"}
                </span>

                <strong>
                  {selectedTask
                    ? `${selectedTask.attempt}/${selectedTask.max_attempts}`
                    : "\u2014"}
                </strong>
              </div>

              <div>
                <span>
                  {"Pipeline"}
                </span>

                <strong>
                  {pipeline
                    ? `${pipeline.progress_percent}%`
                    : "\u2014"}
                </strong>
              </div>

              <div>
                <span>
                  {"Model Kullan\u0131m\u0131"}
                </span>

                <strong>
                  {selectedTask?.model ??
                    "\u2014"}
                </strong>
              </div>

              <div>
                <span>
                  {"Git Branch"}
                </span>

                <strong>
                  {controlCenter?.git
                    .branch ?? "\u2014"}
                </strong>
              </div>

              <div>
                <span>
                  {"Commit"}
                </span>

                <strong>
                  {controlCenter?.git
                    .commit ?? "\u2014"}
                </strong>
              </div>
            </div>

            <div className="result-actions">
              <button
                className="diff-action"
                onClick={() =>
                  void handleDiff()
                }
                disabled={
                  !selectedTask ||
                  loadingDiff
                }
              >
                {loadingDiff
                  ? "Y\u00fckleniyor..."
                  : "Diff'i G\u00f6r\u00fcnt\u00fcle"}
              </button>

              {selectedTask?.state ===
                "ready_for_approval" && (
                <>
                  <button
                    className="approve-action"
                    disabled={
                      actionLoading
                    }
                    onClick={() =>
                      void handleAction(
                        "approve",
                      )
                    }
                  >
                    {"Onayla ve Birle\u015ftir"}
                  </button>

                  <button
                    className="reject-action"
                    disabled={
                      actionLoading
                    }
                    onClick={() =>
                      void handleAction(
                        "reject",
                      )
                    }
                  >
                    {"Reddet"}
                  </button>
                </>
              )}

              {selectedTask?.state ===
                "failed" && (
                <button
                  className="approve-action"
                  disabled={
                    actionLoading
                  }
                  onClick={() =>
                    void handleAction(
                      "retry",
                    )
                  }
                >
                  {"Tekrar Dene"}
                </button>
              )}
            </div>
          </article>
        </section>
          </>
        )}


        {activeProjectTab === "running" && (
          <section className="project-tab-page running-page">
            <div className="tab-page-heading">
              <div>
                <span className="tab-page-kicker">
                  LIVE TASKS
                </span>
                <h2>
                  {"\u00c7al\u0131\u015fan G\u00f6revler"}
                </h2>
              </div>

              <span className="tab-page-count">
                {runningTasks.length}
              </span>
            </div>

            <div className="tab-task-list">
              {runningTasks.length === 0 && (
                <div className="tab-empty">
                  {"Aktif veya onay bekleyen g\u00f6rev bulunmuyor."}
                </div>
              )}

              {runningTasks.map((task) => (
                <button
                  key={task.task_id}
                  className="tab-task-card"
                  onClick={() => {
                    setSelectedTaskId(task.task_id)
                    setActiveProjectTab("overview")
                  }}
                >
                  <span
                    className={`task-state-light state-${task.state}`}
                  />

                  <div>
                    <strong>{task.task_id}</strong>
                    <p>{task.prompt}</p>
                    <small>
                      {stateLabels[task.state] ??
                        task.state}
                      {" \u2022 "}
                      {formatTime(task.started_at)}
                    </small>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {activeProjectTab === "history" && (
          <section className="project-tab-page history-page">
            <div className="tab-page-heading">
              <div>
                <span className="tab-page-kicker">
                  TASK HISTORY
                </span>
                <h2>
                  {"G\u00f6rev Ge\u00e7mi\u015fi"}
                </h2>
              </div>

              <span className="tab-page-count">
                {historyTasks.length}
              </span>
            </div>

            <div className="tab-task-list">
              {historyTasks.length === 0 && (
                <div className="tab-empty">
                  {"Hen\u00fcz tamamlanm\u0131\u015f g\u00f6rev yok."}
                </div>
              )}

              {historyTasks.map((task) => (
                <button
                  key={task.task_id}
                  className="tab-task-card"
                  onClick={() => {
                    setSelectedTaskId(task.task_id)
                    setActiveProjectTab("overview")
                  }}
                >
                  <span
                    className={`task-state-light state-${task.state}`}
                  />

                  <div>
                    <strong>{task.task_id}</strong>
                    <p>{task.prompt}</p>
                    <small>
                      {stateLabels[task.state] ??
                        task.state}
                      {" \u2022 "}
                      {formatDate(task.started_at)}
                    </small>
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {activeProjectTab === "settings" && (
          <section className="project-tab-page settings-page">
            <div className="tab-page-heading">
              <div>
                <span className="tab-page-kicker">
                  PROJECT SETTINGS
                </span>
                <h2>
                  {"Proje Ayarlar\u0131"}
                </h2>
              </div>
            </div>

            {!selectedProject ? (
              <div className="tab-empty">
                {"Ayarlar i\u00e7in bir proje se\u00e7."}
              </div>
            ) : (
              <form
                className="project-settings-form"
                onSubmit={
                  handleProjectSettingsSave
                }
              >
                <label>
                  <span>{"Proje Ad\u0131"}</span>

                  <input
                    value={projectSettingsName}
                    onChange={(event) =>
                      setProjectSettingsName(
                        event.target.value,
                      )
                    }
                  />
                </label>

                <label>
                  <span>{"Proje Yolu"}</span>

                  <input
                    value={projectSettingsPath}
                    onChange={(event) =>
                      setProjectSettingsPath(
                        event.target.value,
                      )
                    }
                  />
                </label>

                <div className="settings-info-grid">
                  <div>
                    <span>Project ID</span>
                    <strong>
                      {selectedProject.project_id}
                    </strong>
                  </div>

                  <div>
                    <span>Git Branch</span>
                    <strong>
                      {controlCenter?.git.branch ??
                        "\u2014"}
                    </strong>
                  </div>

                  <div>
                    <span>Commit</span>
                    <strong>
                      {controlCenter?.git.commit ??
                        "\u2014"}
                    </strong>
                  </div>

                  <div>
                    <span>Repository</span>
                    <strong>
                      {controlCenter?.git.available
                        ? "Git"
                        : "\u2014"}
                    </strong>
                  </div>
                </div>

                <button
                  className="settings-save-button"
                  type="submit"
                  disabled={
                    projectSettingsSaving
                  }
                >
                  {projectSettingsSaving
                    ? "Kaydediliyor..."
                    : "Ayarlar\u0131 Kaydet"}
                </button>
              </form>
            )}
          </section>
        )}

      </main>

      <aside className="right-sidebar">
        <section className="right-panel resource-panel">
          <div className="right-panel-title">
            <strong>
              {"Sistem Kaynaklar\u0131"}
            </strong>

            <span className="live-badge"><i className="live-dot" />{"Canl\u0131"}
            </span>
          </div>

          <div className="hardware-main">
            <span className="hardware-icon"><UiIcon name="cpu" /></span>

            <div>
              <strong>
                {controlCenter
                  ? `${controlCenter.system.cpu.logical_count ?? "\u2014"} Mant\u0131ksal CPU`
                  : "Sistem CPU"}
              </strong>

              <small>
                {controlCenter?.system.platform ??
                  "\u2014"}{" "}
                {controlCenter?.system.platform_release ??
                  ""}
              </small>
            </div>
          </div>

          <div className="metric-block">
            <div>
              <span>
                {"CPU Kullan\u0131m\u0131"}
              </span>

              <strong>
                {controlCenter?.system.cpu
                  .used_percent != null
                  ? `${Math.round(
                      controlCenter
                        .system.cpu
                        .used_percent,
                    )}%`
                  : "\u2014"}
              </strong>
            </div>

            <div className="meter">
              <span
                style={{
                  width: `${Math.min(
                    controlCenter?.system
                      .cpu.used_percent ??
                      0,
                    100,
                  )}%`,
                }}
              />
            </div>
          </div>

          <div className="metric-block">
            <div>
              <span>
                {"RAM Kullan\u0131m\u0131"}
              </span>

              <strong>
                {ramUsed != null
                  ? `${formatBytes(
                      ramUsed,
                    )} / ${formatBytes(
                      controlCenter?.system
                        .memory
                        .total_bytes ??
                        null,
                    )}`
                  : "\u2014"}
              </strong>
            </div>

            <div className="meter blue">
              <span
                style={{
                  width: `${Math.min(
                    controlCenter?.system
                      .memory.used_percent ??
                      0,
                    100,
                  )}%`,
                }}
              />
            </div>
          </div>

          <div className="metric-block">
            <div>
              <span>
                {"Disk Kullan\u0131m\u0131"}
              </span>

              <strong>
                {controlCenter?.system.disk
                  .used_percent != null
                  ? `${Math.round(
                      controlCenter
                        .system.disk
                        .used_percent,
                    )}%`
                  : "\u2014"}
              </strong>
            </div>

            <div className="meter violet">
              <span
                style={{
                  width: `${Math.min(
                    controlCenter?.system
                      .disk.used_percent ??
                      0,
                    100,
                  )}%`,
                }}
              />
            </div>
          </div>
        </section>

        <section className="right-panel">
          <div className="right-panel-title">
            <strong>
              {"Model Durumu"}
            </strong>
          </div>

          <h3>
            {"Lokal Modeller"}
          </h3>

          <div className="model-status-list">
            {controlCenter?.services
              .ollama.models.length ? (
              controlCenter.services.ollama.models
                .slice(0, 5)
                .map(
                  (
                    model,
                    index,
                  ) => (
                    <div
                      className="model-status-row"
                      key={model.name}
                    >
                      <span className="model-provider"><UiIcon name="models" /></span>

                      <span>
                        {model.name}
                      </span>

                      <i
                        className={
                          controlCenter
                            .services
                            .ollama.online
                            ? "online"
                            : ""
                        }
                      />

                      <small>
                        {index === 0
                          ? "Aktif"
                          : "Haz\u0131r"}
                      </small>
                    </div>
                  ),
                )
            ) : (
              <div className="panel-empty">
                {"Model bulunamad\u0131."}
              </div>
            )}
          </div>

          <div className="cost-row">
            <span>
              {"Maliyet (Bu Ay)"}
            </span>

            <strong>$0.00</strong>
          </div>
        </section>

        <section className="right-panel">
          <div className="right-panel-title">
            <strong>
              {"Servis Durumu"}
            </strong>
          </div>

          <div className="service-status-list">
            <div>
              <UiIcon name="models" />
              <strong>
                Ollama (Local LLM)
              </strong>
              <i
                className={
                  controlCenter?.services
                    .ollama.online
                    ? "online"
                    : "offline"
                }
              />
              <small>
                {controlCenter?.services
                  .ollama.online
                  ? "\u00c7al\u0131\u015f\u0131yor"
                  : "Kapal\u0131"}
              </small>
            </div>

            <div>
              <UiIcon name="tests" />
              <strong>
                Docker Sandbox
              </strong>
              <i
                className={
                  controlCenter?.services
                    .docker.online
                    ? "online"
                    : "offline"
                }
              />
              <small>
                {controlCenter?.services
                  .docker.online
                  ? "\u00c7al\u0131\u015f\u0131yor"
                  : "Kapal\u0131"}
              </small>
            </div>

            <div>
              <UiIcon name="worktree" />
              <strong>
                Git (Worktree)
              </strong>
              <i
                className={
                  controlCenter?.git
                    .available
                    ? "online"
                    : "offline"
                }
              />
              <small>
                {controlCenter?.git
                  .available
                  ? "\u00c7al\u0131\u015f\u0131yor"
                  : "Kapal\u0131"}
              </small>
            </div>

            <div>
              <UiIcon name="sqlite" />
              <strong>
                SQLite
              </strong>
              <i className="online" />
              <small>
                {"\u00c7al\u0131\u015f\u0131yor"}
              </small>
            </div>

            <div>
              <UiIcon name="dashboard" />
              <strong>
                Factory API
              </strong>
              <i
                className={
                  backendOnline
                    ? "online"
                    : "offline"
                }
              />
              <small>
                {backendOnline
                  ? "\u00c7al\u0131\u015f\u0131yor"
                  : "Kapal\u0131"}
              </small>
            </div>
          </div>
        </section>

        <section className="right-panel quick-info">
          <div className="right-panel-title">
            <strong>
              {"H\u0131zl\u0131 Bilgiler"}
            </strong>
          </div>

          <div>
            <span>
              {"Proje Yolu"}
            </span>

            <strong>
              {selectedProject?.path ??
                "\u2014"}
            </strong>
          </div>

          <div>
            <span>
              {"Aktif G\u00f6rev"}
            </span>

            <strong className="accent">
              {selectedTask?.task_id ??
                "\u2014"}
            </strong>
          </div>

          <div>
            <span>
              {"Olu\u015fturulma"}
            </span>

            <strong>
              {formatDate(
                selectedTask?.started_at ??
                  null,
              )}
            </strong>
          </div>

          <div>
            <span>
              {"Ortam"}
            </span>

            <strong>
              {controlCenter
                ? `${controlCenter.system.platform} ${controlCenter.system.platform_release}`
                : "\u2014"}
            </strong>
          </div>
        </section>
      </aside>

      <footer className="factory-footer">
        <span>
          AI Software Factory v0.1.0
          <i>|</i>
          Local-First Development Platform
        </span>

        <span>
          {"Daha iyi yaz\u0131l\u0131mlar, daha \u00f6zg\u00fcr geli\u015ftiriciler."}
        </span>
      </footer>
    </div>
  )
}

export default App
