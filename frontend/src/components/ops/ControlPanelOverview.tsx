import type {
  AgentExecution,
  Task,
} from "../../api"

import type {
  PipelineStation,
} from "./FactoryPipeline"

import {
  OpsIcon,
} from "./opsIcons"

import {
  TeddyFactoryPipeline,
} from "../factory/TeddyFactoryPipeline"

import "./ControlPanelOverview.css"

type ProjectItem = {
  project_id: string
  name: string
  path: string
}

type Props = {
  tasks: Task[]
  projects: ProjectItem[]
  stations: PipelineStation[]
  agentExecutions: AgentExecution[]
  activeAgentCount: number
  totalAgents: number
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onSeeAllTasks: () => void
}

type TaskWithProject = Task & {
  project_id?: string | null
}

function stateLabel(state: string) {
  const map: Record<string, string> = {
    queued: "Sırada",
    running: "Çalışıyor",
    ready_for_approval: "Onay Bekliyor",
    approved: "Tamamlandı",
    completed: "Tamamlandı",
    rejected: "Reddedildi",
    failed: "Başarısız",
  }

  return map[state] ?? state
}

function relativeTime(value: string | null | undefined) {
  if (!value) return "—"

  const time = new Date(value).getTime()

  if (!Number.isFinite(time)) {
    return "—"
  }

  const diffMinutes = Math.max(
    0,
    Math.round((Date.now() - time) / 60000),
  )

  if (diffMinutes < 1) {
    return "şimdi"
  }

  if (diffMinutes < 60) {
    return `${diffMinutes} dk önce`
  }

  const hours = Math.floor(diffMinutes / 60)

  if (hours < 24) {
    return `${hours} saat önce`
  }

  return `${Math.floor(hours / 24)} gün önce`
}

function completedTask(task: Task) {
  return (
    task.state === "approved" ||
    task.state === "completed"
  )
}

export function ControlPanelOverview({
  tasks,
  projects,
  stations,
  agentExecutions,
  activeAgentCount,
  totalAgents,
  selectedTaskId,
  onSelectTask,
  onSeeAllTasks,
}: Props) {
  const totalTasks = tasks.length

  const completedTasks =
    tasks.filter(completedTask).length

  const successRate =
    totalTasks > 0
      ? Math.round(
          (completedTasks / totalTasks) * 100,
        )
      : 0

  const activeProjects = projects.length

  const recentTasks = tasks
    .slice()
    .sort((a, b) => {
      const aTime = new Date(
        a.started_at ?? 0,
      ).getTime()

      const bTime = new Date(
        b.started_at ?? 0,
      ).getTime()

      return bTime - aTime
    })
    .slice(0, 5)

  const projectName = (task: Task) => {
    const projectId =
      (task as TaskWithProject).project_id

    return (
      projects.find(
        (project) =>
          project.project_id === projectId,
      )?.name ??
      "AI Software Factory"
    )
  }

  const liveAgents =
    activeAgentCount > 0
      ? activeAgentCount
      : agentExecutions.filter(
          (execution) =>
            execution.status === "running",
        ).length

  return (
    <div className="control-panel-overview">
      <header className="control-panel-title">
        <div>
          <h1>Kontrol Paneli</h1>
          <p>
            AI ekibiniz bugün de sizin için çalışıyor.
            Fikirlerden çalışan yazılıma, otomatik ve
            verimli bir şekilde.
          </p>
        </div>

        <blockquote>
          "Küçük adımlar,
          <br />
          büyük yazılımlar üretir."
        </blockquote>
      </header>

      <section className="control-panel-kpis">
        <article className="control-kpi tone-blue">
          <div className="control-kpi-icon">
            <OpsIcon name="tasks" />
          </div>

          <div className="control-kpi-copy">
            <span>Toplam Görev</span>
            <strong>{totalTasks}</strong>
            <small>Kayıtlı görevler</small>
          </div>
        </article>

        <article className="control-kpi tone-green">
          <div className="control-kpi-icon">
            <OpsIcon name="verify" />
          </div>

          <div className="control-kpi-copy">
            <span>Tamamlanan Görev</span>
            <div className="control-kpi-value-row">
              <strong>{completedTasks}</strong>
              <em>Başarı %{successRate}</em>
            </div>
            <small>Tamamlanan işler</small>
          </div>
        </article>

        <article className="control-kpi tone-violet">
          <div className="control-kpi-icon">
            <OpsIcon name="projects" />
          </div>

          <div className="control-kpi-copy">
            <span>Aktif Proje</span>
            <strong>{activeProjects}</strong>
            <small>Toplam {projects.length} proje</small>
          </div>
        </article>

        <article className="control-kpi tone-amber">
          <div className="control-kpi-icon">
            <OpsIcon name="agents" />
          </div>

          <div className="control-kpi-copy">
            <span>Aktif Ajan</span>
            <strong>{liveAgents}</strong>
            <small>
              {totalAgents > 0
                ? `${liveAgents}/${totalAgents} yürütme`
                : "Aktif yürütme"}
            </small>
          </div>
        </article>
      </section>

      <section className="control-production-card">
        <div className="control-section-heading">
          <div className="control-section-icon">
            <OpsIcon name="flow" />
          </div>

          <div>
            <h2>AI Üretim Hattı</h2>
            <p>
              Fikirden koda, otomatik yazılım üretim hattı.
            </p>
          </div>

          <div className="control-active-agents">
            <i />
            <strong>{liveAgents}</strong>
            <span>ajan aktif</span>
          </div>
        </div>

        <div className="control-production-pipeline">
          <TeddyFactoryPipeline
            stations={stations}
          />
        </div>
      </section>

      <section className="control-recent-tasks">
        <div className="control-section-heading">
          <div className="control-section-icon document">
            <OpsIcon name="tasks" />
          </div>

          <div>
            <h2>Son Görevler</h2>
            <p>
              Son oluşturulan ve güncellenen görevler.
            </p>
          </div>

          <button
            type="button"
            className="control-see-all"
            onClick={onSeeAllTasks}
          >
            Tüm Görevler
            <span>→</span>
          </button>
        </div>

        <div className="control-task-table">
          {recentTasks.length === 0 ? (
            <div className="control-task-empty">
              Henüz görev bulunmuyor.
            </div>
          ) : (
            recentTasks.map((task) => (
              <button
                type="button"
                key={task.task_id}
                className={`control-task-row ${
                  selectedTaskId === task.task_id
                    ? "selected"
                    : ""
                }`}
                onClick={() =>
                  onSelectTask(task.task_id)
                }
              >
                <div className="control-task-doc">
                  <OpsIcon name="tasks" />
                </div>

                <strong className="control-task-id">
                  {task.task_id}
                </strong>

                <span className="control-task-prompt">
                  {task.prompt}
                </span>

                <span
                  className={`control-task-status state-${task.state}`}
                >
                  {stateLabel(task.state)}
                </span>

                <span className="control-task-project">
                  {projectName(task)}
                </span>

                <time>
                  {relativeTime(
                    task.started_at,
                  )}
                </time>

                <span className="control-task-more">
                  •••
                </span>
              </button>
            ))
          )}
        </div>
      </section>
    </div>
  )
}
