import {
  useEffect,
  useMemo,
  useState,
} from "react"

import type {
  AgentExecution,
  ControlCenterStatus,
  Task,
} from "../../api"

import { AgentsWorkersGrid } from "../ops/AgentsWorkersGrid"
import { ProjectsWorkspace } from "../ops/ProjectsWorkspace"

import "./WorldControlPanels.css"

type ProjectItem = {
  project_id: string
  name: string
  path: string
}

type WorldPanelKey =
  | "tasks"
  | "projects"
  | "models"
  | "agents"
  | "memory"
  | "settings"

type Props = {
  activePanel: WorldPanelKey
  tasks: Task[]
  projects: ProjectItem[]
  selectedTaskId: string | null
  selectedProjectId: string | null
  availableModels: string[]
  agentExecutions: AgentExecution[]
  controlCenter: ControlCenterStatus | null
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
  composerRequestId?: number
  onSelectTask: (taskId: string) => void
  onSelectProject: (projectId: string) => void
  onPromptChange: (value: string) => void
  onMaxAttemptsChange: (value: number) => void
  onTaskModelChoiceChange: (value: string) => void
  onCreateTask: (event: React.FormEvent<HTMLFormElement>) => void
  onNewProjectNameChange: (value: string) => void
  onNewProjectPathChange: (value: string) => void
  onCreateProject: (event: React.FormEvent<HTMLFormElement>) => void
  onProjectSettingsNameChange: (value: string) => void
  onProjectSettingsPathChange: (value: string) => void
  onSaveProjectSettings: (event: React.FormEvent<HTMLFormElement>) => void
}

function taskStateLabel(state: string) {
  const labels: Record<string, string> = {
    running: "Çalışıyor",
    queued: "Sırada",
    ready_for_approval: "Onay bekliyor",
    approved: "Tamamlandı",
    completed: "Tamamlandı",
    rejected: "Reddedildi",
    failed: "Başarısız",
  }

  return labels[state] ?? state
}

export function WorldControlPanels({
  activePanel,
  tasks,
  projects,
  selectedTaskId,
  selectedProjectId,
  availableModels,
  agentExecutions,
  controlCenter,
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
  composerRequestId = 0,
  onSelectTask,
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
  const [showTaskComposer, setShowTaskComposer] =
    useState(false)

  useEffect(() => {
    if (composerRequestId > 0) {
      setShowTaskComposer(true)
    }
  }, [composerRequestId])

  const cc = controlCenter as unknown as {
    project_memory?: {
      active?: number
      archived?: number
      superseded?: number
      protected_active?: number
      retention_pressure?: boolean
      recent?: Array<{
        memory_id?: string
        title?: string
        kind?: string
        importance?: number
      }>
    }
    agents?: {
      ready?: number
      total?: number
      unavailable?: number
      items?: Array<{
        name?: string
        provider?: string
        provider_status?: string
        capabilities?: string[]
      }>
    }
    providers?: {
      healthy?: number
      total?: number
      unavailable?: number
      items?: Array<{
        name?: string
        status?: string
      }>
    }
    git?: {
      branch?: string
      commit?: string
      clean?: boolean
    }
  } | null

  const groups = useMemo(
    () => [
      {
        title: "Çalışan",
        tone: "active",
        items: tasks.filter(
          (task) =>
            task.state === "running" ||
            task.state === "queued",
        ),
      },
      {
        title: "Onay Bekleyen",
        tone: "approval",
        items: tasks.filter(
          (task) =>
            task.state === "ready_for_approval",
        ),
      },
      {
        title: "Sonuçlanan",
        tone: "done",
        items: tasks.filter(
          (task) =>
            task.state === "approved" ||
            task.state === "completed" ||
            task.state === "failed" ||
            task.state === "rejected",
        ),
      },
    ],
    [tasks],
  )

  return (
    <div className="world-control-stack">
      {activePanel === "tasks" && (
        <section
          className="world-panel"
          id="world-tasks"
        >
          <div className="world-panel-head">
            <div>
              <span>GÖREV MERKEZİ</span>
              <h2>Görevler</h2>
              <p>
                Görev oluştur, seç ve ajan dünyasının
                seçili görev için nasıl çalıştığını izle.
              </p>
            </div>

            <button
              type="button"
              className="world-primary-button"
              onClick={() =>
                setShowTaskComposer(
                  (current) => !current,
                )
              }
              disabled={!selectedProjectId}
            >
              {showTaskComposer
                ? "Kapat"
                : "+ Yeni Görev"}
            </button>
          </div>

          {showTaskComposer && (
            <form
              className="world-form world-task-form"
              onSubmit={onCreateTask}
            >
              <label className="world-form-wide">
                <span>Görev</span>

                <textarea
                  rows={4}
                  value={prompt}
                  onChange={(event) =>
                    onPromptChange(
                      event.target.value,
                    )
                  }
                  placeholder="Ajan ekibinin yapmasını istediğin işi yaz..."
                />
              </label>

              <label>
                <span>Model</span>

                <select
                  value={taskModelChoice}
                  onChange={(event) =>
                    onTaskModelChoiceChange(
                      event.target.value,
                    )
                  }
                >
                  <option value="">
                    Otomatik seçim
                  </option>

                  {availableModels.map(
                    (model) => (
                      <option
                        key={model}
                        value={model}
                      >
                        {model}
                      </option>
                    ),
                  )}
                </select>
              </label>

              <label>
                <span>Deneme</span>

                <select
                  value={maxAttempts}
                  onChange={(event) =>
                    onMaxAttemptsChange(
                      Number(event.target.value),
                    )
                  }
                >
                  {[1, 2, 3, 4, 5].map(
                    (value) => (
                      <option
                        key={value}
                        value={value}
                      >
                        {value}
                      </option>
                    ),
                  )}
                </select>
              </label>

              <button
                type="submit"
                className="world-submit"
                disabled={
                  submitting ||
                  !prompt.trim() ||
                  !selectedProjectId
                }
              >
                {submitting
                  ? "Başlatılıyor..."
                  : "Görevi Başlat"}
              </button>
            </form>
          )}

          <div className="world-task-columns">
            {groups.map((group) => (
              <div
                className={`world-task-column tone-${group.tone}`}
                key={group.title}
              >
                <div className="world-task-column-head">
                  <strong>{group.title}</strong>
                  <span>{group.items.length}</span>
                </div>

                <div className="world-task-column-list">
                  {group.items.length === 0 ? (
                    <div className="world-empty">
                      Bu bölümde görev yok.
                    </div>
                  ) : (
                    group.items
                      .slice(0, 12)
                      .map((task) => (
                        <button
                          type="button"
                          className={`world-task-card ${
                            selectedTaskId ===
                            task.task_id
                              ? "selected"
                              : ""
                          }`}
                          key={task.task_id}
                          onClick={() =>
                            onSelectTask(
                              task.task_id,
                            )
                          }
                        >
                          <div>
                            <strong>
                              {task.task_id}
                            </strong>

                            <span
                              className={`world-task-state state-${task.state}`}
                            >
                              {taskStateLabel(
                                task.state,
                              )}
                            </span>
                          </div>

                          <p>{task.prompt}</p>

                          <small>
                            {task.model ??
                              "Otomatik model"}
                          </small>
                        </button>
                      ))
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {activePanel === "projects" && (
        <section
          className="world-panel world-projects-panel"
          id="world-projects"
        >
          <ProjectsWorkspace
            projects={projects}
            tasks={tasks}
            selectedProjectId={selectedProjectId}
            controlCenter={controlCenter}
            newProjectName={newProjectName}
            newProjectPath={newProjectPath}
            projectSubmitting={projectSubmitting}
          projectCreateError={projectCreateError}
            projectSettingsName={projectSettingsName}
            projectSettingsPath={projectSettingsPath}
            projectSettingsSaving={projectSettingsSaving}
            onSelectProject={onSelectProject}
            onNewProjectNameChange={onNewProjectNameChange}
            onNewProjectPathChange={onNewProjectPathChange}
            onCreateProject={onCreateProject}
            onProjectSettingsNameChange={onProjectSettingsNameChange}
            onProjectSettingsPathChange={onProjectSettingsPathChange}
            onSaveProjectSettings={onSaveProjectSettings}
          />
        </section>
      )}

      {activePanel === "models" && (
        <section
          className="world-panel"
          id="world-models"
        >
          <div className="world-panel-head">
            <div>
              <span>MODEL AĞI</span>
              <h2>Modeller</h2>
              <p>
                Kurulu yerel modelleri ve Ollama
                durumunu tek noktada izle.
              </p>
            </div>

            <div className="world-head-stat">
              <strong>{availableModels.length}</strong>
              <span>
                {controlCenter?.services.ollama.online
                  ? "Ollama çalışıyor"
                  : "Ollama kapalı"}
              </span>
            </div>
          </div>

          <div className="world-model-grid">
            {availableModels.length === 0 ? (
              <div className="world-empty">
                Kurulu model bulunamadı.
              </div>
            ) : (
              availableModels.map((model, index) => (
                <article
                  className="world-model-card"
                  key={model}
                >
                  <div className="world-model-orb">●</div>

                  <div>
                    <strong>{model}</strong>
                    <small>
                      {index === 0
                        ? "Aktif / öncelikli"
                        : "Hazır"}
                    </small>
                  </div>

                  <span
                    className={
                      controlCenter?.services.ollama.online
                        ? "world-online"
                        : "world-offline"
                    }
                  >
                    <i />
                    {controlCenter?.services.ollama.online
                      ? "Hazır"
                      : "Kapalı"}
                  </span>
                </article>
              ))
            )}
          </div>
        </section>
      )}

      {activePanel === "agents" && (
        <section
          className="world-panel world-agents-panel"
          id="world-agents"
        >
          <AgentsWorkersGrid
            agentExecutions={agentExecutions}
            agentItems={cc?.agents?.items ?? []}
            controlCenter={controlCenter}
            availableModels={availableModels}
            memoryActive={cc?.project_memory?.active ?? 0}
          />
        </section>
      )}

      {activePanel === "memory" && (
        <section
          className="world-panel"
          id="world-memory"
        >
          <div className="world-panel-head">
            <div>
              <span>PROJE HAFIZASI</span>
              <h2>Hafıza</h2>
              <p>
                Kararlar, kurallar ve geçmiş
                görevlerden kalan proje bilgileri.
              </p>
            </div>

            <div className="world-head-stat">
              <strong>
                {cc?.project_memory?.active ??
                  0}
              </strong>
              <span>aktif hafıza</span>
            </div>
          </div>

          <div className="world-memory-grid">
            <div>
              <small>Aktif</small>
              <strong>
                {cc?.project_memory?.active ?? 0}
              </strong>
            </div>

            <div>
              <small>Korunan</small>
              <strong>
                {cc?.project_memory?.protected_active ?? 0}
              </strong>
            </div>

            <div>
              <small>Arşiv</small>
              <strong>
                {cc?.project_memory?.archived ?? 0}
              </strong>
            </div>

            <div>
              <small>Retention</small>
              <strong>
                {cc?.project_memory?.retention_pressure
                  ? "Dikkat"
                  : "Normal"}
              </strong>
            </div>
          </div>

          {(cc?.project_memory?.recent ?? []).length > 0 ? (
            <div className="world-memory-recent">
              {(cc?.project_memory?.recent ?? [])
                .slice(0, 6)
                .map((item, index) => (
                  <article key={item.memory_id ?? index}>
                    <strong>{item.title ?? "Kayıt"}</strong>
                    <small>
                      {item.kind ?? "memory"}
                      {item.importance != null
                        ? ` · önem ${item.importance}`
                        : ""}
                    </small>
                  </article>
                ))}
            </div>
          ) : (
            <div className="world-empty">
              Henüz proje hafızası kaydı yok.
            </div>
          )}
        </section>
      )}

      {activePanel === "settings" && (
        <section
          className="world-panel"
          id="world-settings"
        >
          <div className="world-panel-head">
            <div>
              <span>PROJE AYARLARI</span>
              <h2>Ayarlar</h2>
              <p>
                Aktif projenin adını ve
                repository yolunu düzenle.
              </p>
            </div>

            <div className="world-git-status">
              <span>Dal</span>
              <strong>
                {cc?.git?.branch ?? "—"}
              </strong>
            </div>
          </div>

          <form
            className="world-form world-settings-form"
            onSubmit={onSaveProjectSettings}
          >
            <label>
              <span>Proje adı</span>
              <input
                value={projectSettingsName}
                onChange={(event) =>
                  onProjectSettingsNameChange(
                    event.target.value,
                  )
                }
              />
            </label>

            <label className="world-form-wide">
              <span>Proje yolu</span>
              <input
                value={projectSettingsPath}
                onChange={(event) =>
                  onProjectSettingsPathChange(
                    event.target.value,
                  )
                }
              />
            </label>

            <button
              className="world-submit"
              type="submit"
              disabled={projectSettingsSaving}
            >
              {projectSettingsSaving
                ? "Kaydediliyor..."
                : "Ayarları Kaydet"}
            </button>
          </form>
        </section>
      )}
    </div>
  )
}
