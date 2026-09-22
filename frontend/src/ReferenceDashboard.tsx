import { useEffect, useState, type FormEvent } from "react"
import type {
  AgentExecution,
  ControlCenterStatus,
  Task,
  TaskPipeline,
} from "./api"

import type {
  PipelineStation,
  PipelineStationState,
} from "./components/ops/FactoryPipeline"

import { DashboardHeader } from "./components/ops/DashboardHeader"
import { ControlPanelOverview } from "./components/ops/ControlPanelOverview"
import { ControlPanelSystemRail } from "./components/ops/ControlPanelSystemRail"
import {
  TeddyFactoryPipeline,
} from "./components/factory/TeddyFactoryPipeline"
import { OpsIcon, type OpsIconName } from "./components/ops/opsIcons"
import { TaskHistoryPanel } from "./components/ops/TaskHistoryPanel"
import { TaskLiveActivityPanel } from "./components/ops/TaskLiveActivityPanel"
import { WorldControlPanels } from "./components/world/WorldControlPanels"
import { WorldRightRail } from "./components/world/WorldRightRail"
import "./components/factory/FactoryVisuals.css"
import "./ReferenceDashboard.css"

type PipelineStage = {
  id: string
  label: string
  status: string
}

type Props = {
  controlCenter: ControlCenterStatus | null
  selectedTask: Task | null
  actionLoading: boolean
  onApproveTask: () => void
  onRejectTask: () => void
  taskReadResult: string | null
  pipeline: TaskPipeline | null
  pipelineStages: PipelineStage[]
  runningTasks: Task[]
  tasks: Task[]
  liveLogs: string[]
  agentExecutions: AgentExecution[]
  availableModels: string[]
  onSelectTask: (taskId: string) => void
  onTasks: () => void
  onSettings: () => void
  onModels: () => void
  projects: Array<{ project_id: string; name: string; path: string }>
  selectedTaskId: string | null
  selectedProjectId: string | null
  prompt: string
  maxAttempts: number
  taskModelChoice: string
  submitting: boolean
  newProjectName: string
  newProjectPath: string
  projectSubmitting: boolean
  projectCreateError: string | null
  projectSettingsName: string
  projectSettingsPath: string
  projectSettingsSaving: boolean
  onSelectProject: (projectId: string) => void
  onPromptChange: (value: string) => void
  onMaxAttemptsChange: (value: number) => void
  onTaskModelChoiceChange: (value: string) => void
  onCreateTask: (event: FormEvent<HTMLFormElement>) => void
  onNewProjectNameChange: (value: string) => void
  onNewProjectPathChange: (value: string) => void
  onCreateProject: (event: FormEvent<HTMLFormElement>) => void
  onProjectSettingsNameChange: (value: string) => void
  onProjectSettingsPathChange: (value: string) => void
  onSaveProjectSettings: (event: FormEvent<HTMLFormElement>) => void
}

type NavKey =
  | "overview"
  | "tasks"
  | "projects"
  | "models"
  | "agents"
  | "memory"
  | "settings"

type CC = ControlCenterStatus & {
  providers?: { total?: number; healthy?: number }
  agents?: { total?: number; ready?: number }
  project_memory?: { active?: number; total?: number }
  health?: { status?: string }
  tasks?: {
    total?: number
    running?: number
    approval?: number
    failed?: number
    approved?: number
  }
}

const NAV_ITEMS: Array<{
  key: NavKey
  label: string
  icon: OpsIconName
  target: string
}> = [
  { key: "overview", label: "Kontrol Paneli", icon: "dashboard", target: "factory-home" },
  { key: "tasks", label: "Görevler", icon: "tasks", target: "world-tasks" },
  { key: "projects", label: "Projeler", icon: "projects", target: "world-projects" },
  { key: "models", label: "Modeller", icon: "models", target: "world-models" },
  { key: "agents", label: "Ajanlar", icon: "agents", target: "world-agents" },
  { key: "memory", label: "Hafıza", icon: "memory", target: "world-memory" },
  { key: "settings", label: "Ayarlar", icon: "settings", target: "world-settings" },
]

function statusState(raw: string | undefined): PipelineStationState {
  if (raw === "completed" || raw === "success") return "completed"
  if (raw === "active" || raw === "running") return "active"
  if (raw === "waiting" || raw === "ready_for_approval") return "waiting"
  if (raw === "failed" || raw === "rejected") return "failed"
  if (raw === "skipped" || raw === "not_required") return "skipped"
  return "pending"
}

function displayStatus(raw: string | null | undefined) {
  if (!raw) return null
  const map: Record<string, string> = {
    pending: "Sırada",
    queued: "Sırada",
    active: "Çalışıyor",
    running: "Çalışıyor",
    completed: "Tamamlandı",
    success: "Tamamlandı",
    waiting: "Onay Bekliyor",
    ready_for_approval: "Onay Bekliyor",
    failed: "Hata",
    rejected: "Reddedildi",
    approved: "Tamamlandı",
    skipped: "Gerekmiyor",
    not_required: "Gerekmiyor",
  }
  return map[raw] ?? raw
}


export function ReferenceDashboard({
  controlCenter,
  selectedTask,
  actionLoading,
  onApproveTask,
  onRejectTask,
  taskReadResult,
  pipeline,
  pipelineStages,
  runningTasks,
  tasks,
  liveLogs,
    agentExecutions,
  availableModels,
  onSelectTask,
  onTasks,
  onSettings,
  onModels,
  projects,
  selectedTaskId,
  selectedProjectId,
  prompt,
  maxAttempts,
  taskModelChoice,
  submitting,
  newProjectName,
  newProjectPath,
  projectSubmitting,
  projectCreateError,
  projectSettingsName,
  projectSettingsPath,
  projectSettingsSaving,
  onSelectProject,
  onPromptChange,
  onMaxAttemptsChange,
  onTaskModelChoiceChange,
  onCreateTask,
  onNewProjectNameChange,
  onNewProjectPathChange,
  onCreateProject,
  onProjectSettingsNameChange,
  onProjectSettingsPathChange,
  onSaveProjectSettings,
}: Props) {
  void onTasks
  void onSettings
  void onModels

  const [activeNav, setActiveNav] = useState<NavKey>("overview")
  const [composerRequestId, setComposerRequestId] = useState(0)
  const [clock, setClock] = useState(() =>
    new Intl.DateTimeFormat("tr-TR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date()),
  )

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClock(
        new Intl.DateTimeFormat("tr-TR", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }).format(new Date()),
      )
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  const cc = controlCenter as CC | null

  // BACKEND_DRIVEN_TEDDY_PIPELINE_V1
  //
  // UI kendi pipeline'ını uydurmaz.
  // Backend'in /pipeline cevabındaki task_kind + stages kaynak kabul edilir.
  const backendStages =
    pipeline?.stages?.length
      ? pipeline.stages
      : pipelineStages

  const taskKind =
    (
      pipeline as
        | (TaskPipeline & {
            task_kind?: string | null
          })
        | null
    )?.task_kind ??
    null

  const isReadTask =
    taskKind === "read"

  const findBackendStages = (
    names: string[],
  ) =>
    backendStages.filter((stage) =>
      names.some(
        (name) =>
          stage.id === name ||
          stage.id.includes(name),
      ),
    )

  const stateForStages = (
    names: string[],
  ): PipelineStationState => {
    const matches =
      findBackendStages(names)

    if (matches.length === 0) {
      return "pending"
    }

    const states =
      matches.map((stage) =>
        statusState(stage.status),
      )

    if (states.some((state) => state === "failed")) {
      return "failed"
    }

    if (states.some((state) => state === "active")) {
      return "active"
    }

    if (states.some((state) => state === "waiting")) {
      return "waiting"
    }

    if (states.every((state) => state === "skipped")) {
      return "skipped"
    }

    if (
      states.every(
        (state) =>
          state === "completed" ||
          state === "skipped",
      )
    ) {
      return "completed"
    }

    return "pending"
  }

  const labelForStages = (
    names: string[],
  ) => {
    const matches =
      findBackendStages(names)

    if (matches.length === 0) {
      return null
    }

    return matches
      .map((stage) => stage.label)
      .filter(Boolean)
      .join(" + ")
  }

  const runningExec =
    agentExecutions.find(
      (item) =>
        item.status === "running",
    ) ?? null

  const lineOrWait = (
    ...parts: Array<
      string | null | undefined
    >
  ) => {
    const cleaned = parts
      .map(
        (part) =>
          (part ?? "").trim(),
      )
      .filter(Boolean)

    return cleaned.length > 0
      ? cleaned
      : ["Bekliyor"]
  }

  const readStations: PipelineStation[] = [
    {
      key: "read-task",
      label: "GÖREV",
      lines: lineOrWait(
        selectedTask?.task_id,
        labelForStages(["task"]),
        displayStatus(
          findBackendStages(["task"])[0]
            ?.status,
        ),
      ),
      state: stateForStages(["task"]),
      accent: "amber",
      icon: "idea",
    },
    {
      key: "read-analysis",
      label: "PROJE ANALİZİ",
      lines: lineOrWait(
        labelForStages(["repo_analysis"]),
        displayStatus(
          findBackendStages(["repo_analysis"])[0]
            ?.status,
        ),
      ),
      state: stateForStages(["repo_analysis"]),
      accent: "blue",
      icon: "flow",
    },
    {
      key: "read-model",
      label: "YANIT ÜRETİMİ",
      lines: lineOrWait(
        selectedTask?.model ??
          runningExec?.model_name,
        labelForStages(["model"]),
        displayStatus(
          findBackendStages(["model"])[0]
            ?.status,
        ),
      ),
      state: stateForStages(["model"]),
      accent: "violet",
      icon: "code",
    },
    {
      key: "read-result",
      label: "SONUÇ",
      lines: lineOrWait(
        labelForStages(["completed"]),
        selectedTask?.state === "completed"
          ? "Yanıt hazır"
          : null,
        displayStatus(
          findBackendStages(["completed"])[0]
            ?.status,
        ),
      ),
      state:
        selectedTask?.state === "completed"
          ? "completed"
          : stateForStages(["completed"]),
      accent: "green",
      icon: "verify",
    },
  ]

  const writeStations: PipelineStation[] = [
    {
      key: "write-plan",
      label: "PLANLAYICI",
      lines: lineOrWait(
        selectedTask?.task_id,
        labelForStages(["task", "worktree"]),
      ),
      state: stateForStages(["task", "worktree"]),
      accent: "amber",
      icon: "idea",
    },
    {
      key: "write-analysis",
      label: "ANALİST",
      lines: lineOrWait(
        labelForStages(["repo_analysis", "analysis"]),
      ),
      state: stateForStages(["repo_analysis", "analysis"]),
      accent: "blue",
      icon: "flow",
    },
    {
      key: "write-code",
      label: "KODLAYICI",
      lines: lineOrWait(
        selectedTask?.model ??
          runningExec?.model_name,
        labelForStages(["model", "write", "code"]),
      ),
      state: stateForStages(["model", "write", "code"]),
      accent: "violet",
      icon: "code",
    },
    {
      key: "write-review",
      label: "İNCELEYİCİ",
      lines: lineOrWait(
        labelForStages(["patch", "diff", "review"]),
      ),
      state: stateForStages(["patch", "diff", "review"]),
      accent: "orange",
      icon: "review",
    },
    {
      key: "write-verify",
      label: "DOĞRULAYICI",
      lines: lineOrWait(
        labelForStages(["tests", "test", "verify"]),
        selectedTask?.test_result,
      ),
      state: stateForStages(["tests", "test", "verify"]),
      accent: "green",
      icon: "verify",
    },
    {
      key: "write-approval",
      label: "ONAY & BİRLEŞTİRME",
      lines: lineOrWait(
        labelForStages(["approval", "merge"]),
        selectedTask?.state === "ready_for_approval"
          ? "Kullanıcı onayı bekleniyor"
          : null,
      ),
      state:
        selectedTask?.state === "ready_for_approval"
          ? "waiting"
          : selectedTask?.state === "approved"
            ? "completed"
            : stateForStages(["approval", "merge"]),
      accent: "cyan",
      icon: "deploy",
    },
  ]

  const stations: PipelineStation[] =
    isReadTask
      ? readStations
      : writeStations

  const activeAgentCount = agentExecutions.filter(
    (item) => item.status === "running",
  ).length
  const totalAgents = Number(
    cc?.agents?.total ?? Math.max(agentExecutions.length, 0),
  )

  const selectedProject =
    projects.find((project) => project.project_id === selectedProjectId) ??
    null

  const systemOnline =
    !!controlCenter?.services.ollama.online ||
    !!controlCenter?.services.docker.online ||
    !!controlCenter?.git.available


  const handleNav = (key: NavKey, _target: string) => {
    setActiveNav(key)

    window.requestAnimationFrame(() => {
      const workspace = document.querySelector(
        ".reference-workspace",
      )

      if (workspace instanceof HTMLElement) {
        workspace.scrollTo({
          top: 0,
          behavior: "smooth",
        })
      }
    })
  }

  const openNewTask = () => {
    setComposerRequestId((value) => value + 1)
    handleNav("tasks", "world-tasks")
  }

  return (
    <section
      className="reference-dashboard-root"
      id="factory-home"
      data-active-view={activeNav}
    >
      <aside className="reference-sidebar">
        <div className="ref-brand">
          <div className="ref-brand-mark" aria-hidden="true">
            <span />
            <i />
            <b />
          </div>
          <div>
            <strong>AI Software Factory</strong>
            <span>Operations Center</span>
          </div>
        </div>

        <nav className="ref-nav" aria-label="Ana menü">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={activeNav === item.key ? "active" : ""}
              onClick={() => handleNav(item.key, item.target)}
            >
              <OpsIcon name={item.icon} />
              <span>{item.label}</span>
              {item.key === "tasks" && runningTasks.length > 0 && (
                <em className="ref-nav-badge">{runningTasks.length}</em>
              )}
            </button>
          ))}
        </nav>

        <div className="ref-sidebar-spacer" />

        <div className="ref-system-status">
          <i className={systemOnline ? "online" : "offline"} />
          <div>
            <strong>
              {systemOnline ? "Sistem Çalışıyor" : "Sistem Beklemede"}
            </strong>
            <span>
              {systemOnline
                ? "Tüm servisler aktif"
                : "Servis durumu kontrol edilmeli"}
            </span>
          </div>
        </div>
      </aside>

      <main className="reference-workspace">

        <DashboardHeader
          runningCount={runningTasks.length}
          onNewTask={openNewTask}
          onNotifyClick={() => handleNav("tasks", "world-tasks")}
        />

        {activeNav === "overview" && (
          <div className="control-panel-dashboard-layout">
            <div className="control-panel-dashboard-main">
              <ControlPanelOverview
                          tasks={tasks}
                          projects={projects}
                          stations={stations}
                          agentExecutions={agentExecutions}
                          activeAgentCount={activeAgentCount}
                          totalAgents={totalAgents}
                          selectedTaskId={selectedTaskId}
                          onSelectTask={onSelectTask}
                          onSeeAllTasks={() =>
                            handleNav("tasks", "world-tasks")
                          }
                        />
            </div>

            <aside className="control-panel-dashboard-rail">
              <ControlPanelSystemRail
                controlCenter={controlCenter}
                availableModels={availableModels}
              />
            </aside>
          </div>
        )}

        {activeNav === "tasks" && (
          <div className="reference-view-page reference-view-tasks">
            <div className="reference-page-heading">
              <div>
                <span>GÖREV YÖNETİMİ</span>
                <h1>Görevler</h1>
                <p>
                  Aktif işleri, onay bekleyen görevleri ve sonuçlanan
                  görevleri tek yerde yönet.
                </p>
              </div>
            </div>

        <TeddyFactoryPipeline
          stations={stations}
          hasAiResponse={Boolean(taskReadResult)}
        />
        {/* TASK_LIVE_ACTIVITY_PANEL_V1 */}
                <div className="task-operations-row">
          <div className="task-operations-live">
<TaskLiveActivityPanel
          selectedTask={selectedTask}
          pipeline={pipeline}
          liveLogs={liveLogs}
          agentExecutions={agentExecutions}
        />
          </div>

          <div className="task-operations-center">
<WorldControlPanels
          activePanel={activeNav}
          tasks={tasks}
          projects={projects}
          selectedTaskId={selectedTaskId}
          selectedProjectId={selectedProjectId}
          availableModels={availableModels}
          agentExecutions={agentExecutions}
          controlCenter={controlCenter}
          prompt={prompt}
          maxAttempts={maxAttempts}
          taskModelChoice={taskModelChoice}
          submitting={submitting}
          newProjectName={newProjectName}
          newProjectPath={newProjectPath}
          projectSubmitting={projectSubmitting}
          projectCreateError={projectCreateError}
          projectSettingsName={projectSettingsName}
          projectSettingsPath={projectSettingsPath}
          projectSettingsSaving={projectSettingsSaving}
          composerRequestId={composerRequestId}
          onSelectTask={onSelectTask}
          onSelectProject={onSelectProject}
          onPromptChange={onPromptChange}
          onMaxAttemptsChange={onMaxAttemptsChange}
          onTaskModelChoiceChange={onTaskModelChoiceChange}
          onCreateTask={onCreateTask}
          onNewProjectNameChange={onNewProjectNameChange}
          onNewProjectPathChange={onNewProjectPathChange}
          onCreateProject={onCreateProject}
          onProjectSettingsNameChange={onProjectSettingsNameChange}
          onProjectSettingsPathChange={onProjectSettingsPathChange}
          onSaveProjectSettings={onSaveProjectSettings}
        />
          </div>
        </div>
        {/* TASK_APPROVAL_ACTIONS_V1 */}
        {selectedTask?.state === "ready_for_approval" && (
          <section className="task-approval-panel">
            <div className="task-approval-copy">
              <span>İNSAN ONAYI GEREKİYOR</span>
              <h2>Değişiklikler onayınızı bekliyor</h2>
              <p>
                {selectedTask.task_id} kod üretimi ve doğrulama aşamalarını
                tamamladı. Değişiklikleri ana dala birleştirmek için onaylayın
                veya worktree değişikliklerini reddedin.
              </p>
            </div>

            <div className="task-approval-actions">
              <button
                type="button"
                className="task-reject-button"
                disabled={actionLoading}
                onClick={onRejectTask}
              >
                {actionLoading ? "İşleniyor..." : "Reddet"}
              </button>

              <button
                type="button"
                className="task-approve-button"
                disabled={actionLoading}
                onClick={onApproveTask}
              >
                {actionLoading ? "İşleniyor..." : "Onayla ve Birleştir"}
              </button>
            </div>
          </section>
        )}



        {/* READ_TASK_RESULT_PANEL_V1 */}
        {(
          pipeline?.task_kind === "read" ||
          selectedTask?.task_kind === "read"
        ) &&
          selectedTask?.state === "completed" && (
            <section
              id="task-ai-response"
              className="read-task-result-card"
              aria-label="Görev sonucu"
            >
              <div className="read-task-result-head">
                <div>
                  <span>GÖREV SONUCU</span>
                  <h2>AI Yanıtı</h2>
                </div>

                <div className="read-task-result-status">
                  TAMAMLANDI
                </div>
              </div>

              <div className="read-task-result-body">
                {taskReadResult ? (
                  <pre>{taskReadResult}</pre>
                ) : (
                  <p>
                    Sonuç backend’den yükleniyor...
                  </p>
                )}
              </div>
            </section>
          )}




            <TaskHistoryPanel
              selectedTask={selectedTask}
              pipelineStages={pipelineStages}
              agentExecutions={agentExecutions}
              liveLogs={liveLogs}
            />
          </div>
        )}

        {activeNav !== "overview" && activeNav !== "tasks" && (
          <div
            className={`reference-view-page reference-view-${activeNav}`}
          >
            <div className="reference-page-heading">
              <div>
                <span>
                  {activeNav === "projects"
                    ? "ÇALIŞMA ALANI"
                    : activeNav === "models"
                      ? "MODEL AĞI"
                      : activeNav === "agents"
                        ? "AJAN ORKESTRASYONU"
                        : activeNav === "memory"
                          ? "PROJE HAFIZASI"
                          : "PROJE AYARLARI"}
                </span>

                <h1>
                  {activeNav === "projects"
                    ? "Projeler"
                    : activeNav === "models"
                      ? "Modeller"
                      : activeNav === "agents"
                        ? "Ajanlar & Sistem"
                        : activeNav === "memory"
                          ? "Hafıza"
                          : "Ayarlar"}
                </h1>

                <p>
                  {activeNav === "projects"
                    ? "Aktif repository’lerini yönet, sağlığını izle ve projeyi tek tıkla aç."
                    : activeNav === "models"
                      ? "Kurulu modelleri ve model sağlayıcılarını izle."
                      : activeNav === "agents"
                        ? "Ajanların durumunu, modelini ve son aktivitelerini incele."
                        : activeNav === "memory"
                          ? "Proje hafızasını ve kalıcı bağlam kayıtlarını yönet."
                          : "Aktif projenin temel ayarlarını düzenle."}
                </p>
              </div>
            </div>

        <WorldControlPanels
          activePanel={activeNav}
          tasks={tasks}
          projects={projects}
          selectedTaskId={selectedTaskId}
          selectedProjectId={selectedProjectId}
          availableModels={availableModels}
          agentExecutions={agentExecutions}
          controlCenter={controlCenter}
          prompt={prompt}
          maxAttempts={maxAttempts}
          taskModelChoice={taskModelChoice}
          submitting={submitting}
          newProjectName={newProjectName}
          newProjectPath={newProjectPath}
          projectSubmitting={projectSubmitting}
          projectCreateError={projectCreateError}
          projectSettingsName={projectSettingsName}
          projectSettingsPath={projectSettingsPath}
          projectSettingsSaving={projectSettingsSaving}
          composerRequestId={composerRequestId}
          onSelectTask={onSelectTask}
          onSelectProject={onSelectProject}
          onPromptChange={onPromptChange}
          onMaxAttemptsChange={onMaxAttemptsChange}
          onTaskModelChoiceChange={onTaskModelChoiceChange}
          onCreateTask={onCreateTask}
          onNewProjectNameChange={onNewProjectNameChange}
          onNewProjectPathChange={onNewProjectPathChange}
          onCreateProject={onCreateProject}
          onProjectSettingsNameChange={onProjectSettingsNameChange}
          onProjectSettingsPathChange={onProjectSettingsPathChange}
          onSaveProjectSettings={onSaveProjectSettings}
        />
          </div>
        )}
      </main>

      <WorldRightRail
        selectedTask={selectedTask}
        selectedProject={selectedProject}
        pipeline={pipeline}
        pipelineStages={pipelineStages}
        controlCenter={controlCenter}
        agentExecutions={agentExecutions}
        clock={clock}
      />
    </section>
  )
}
