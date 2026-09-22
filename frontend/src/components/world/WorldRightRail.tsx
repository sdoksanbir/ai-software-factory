import type {
  AgentExecution,
  ControlCenterStatus,
  Task,
  TaskPipeline,
} from "../../api"

import "./WorldRightRail.css"

type ProjectItem = {
  project_id: string
  name: string
  path: string
}

type PipelineStageLite = {
  id: string
  label: string
  status: string
}

type Props = {
  selectedTask: Task | null
  selectedProject: ProjectItem | null
  pipeline: TaskPipeline | null
  pipelineStages: PipelineStageLite[]
  controlCenter: ControlCenterStatus | null
  agentExecutions: AgentExecution[]
  clock: string
}

type CC = {
  git?: { available?: boolean; branch?: string | null }
}

const pct = (v: number | null | undefined) =>
  Math.min(100, Math.max(0, Number(v ?? 0)))

const stateLabel = (s: string | undefined) =>
  (
    ({
      queued: "Sırada",
      running: "Çalışıyor",
      ready_for_approval: "Onay Bekliyor",
      approved: "Tamamlandı",
      completed: "Tamamlandı",
      rejected: "Reddedildi",
      failed: "Başarısız",
    }) as Record<string, string>
  )[s ?? ""] ?? (s || "Bekliyor")


type CheckItem = {
  key: string
  label: string
  mark: "done" | "active" | "todo" | "failed"
}

function buildChecklist(
  selectedTask: Task | null,
  taskKind: string | null,
  stages: PipelineStageLite[],
): CheckItem[] {
  const find = (names: string[]) =>
    stages.find((stage) =>
      names.some(
        (name) =>
          stage.id === name ||
          stage.id.includes(name),
      ),
    )

  const markOf = (raw: string | undefined): CheckItem["mark"] => {
    if (
      raw === "completed" ||
      raw === "success" ||
      raw === "skipped" ||
      raw === "not_required"
    ) {
      return "done"
    }

    if (
      raw === "failed" ||
      raw === "rejected"
    ) {
      return "failed"
    }

    if (
      raw === "active" ||
      raw === "running" ||
      raw === "waiting" ||
      raw === "ready_for_approval"
    ) {
      return "active"
    }

    return "todo"
  }

  const received: CheckItem["mark"] =
    selectedTask ? "done" : "todo"

  if (taskKind === "read") {
    const analysis = find(["repo_analysis"])
    const model = find(["model"])
    const result = find(["completed"])

    const analysisMark = markOf(analysis?.status)
    const modelMark = markOf(model?.status)

    const resultMark: CheckItem["mark"] =
      selectedTask?.state === "completed"
        ? "done"
        : selectedTask?.state === "failed"
          ? "todo"
          : markOf(result?.status)

    return [
      {
        key: "read-intake",
        label: "Görev alındı",
        mark: received,
      },
      {
        key: "read-analysis",
        label:
          analysisMark === "done"
            ? "Proje analiz edildi"
            : analysisMark === "active"
              ? "Proje analiz ediliyor"
              : analysisMark === "failed"
                ? "Proje analizi başarısız"
                : "Proje analizi bekliyor",
        mark: analysisMark,
      },
      {
        key: "read-model",
        label:
          modelMark === "done"
            ? "Yanıt üretildi"
            : modelMark === "active"
              ? "Yanıt üretiliyor"
              : modelMark === "failed"
                ? "Yanıt üretimi başarısız"
                : "Yanıt üretimi bekliyor",
        mark: modelMark,
      },
      {
        key: "read-result",
        label:
          resultMark === "done"
            ? "Sonuç hazır"
            : resultMark === "active"
              ? "Sonuç hazırlanıyor"
              : "Sonuç bekliyor",
        mark: resultMark,
      },
    ]
  }

  if (taskKind === "write") {
    const analyst = find([
      "repo_analysis",
      "worktree",
      "analysis",
    ])
    const coder = find([
      "model",
      "write",
      "code",
    ])
    const reviewer = find([
      "patch",
      "diff",
      "review",
    ])
    const verifier = find([
      "tests",
      "test",
      "verify",
    ])
    const approval = find([
      "approval",
      "merge",
    ])

    const analystMark = markOf(analyst?.status)
    const coderMark = markOf(coder?.status)
    const reviewerMark = markOf(reviewer?.status)
    const verifierMark = markOf(verifier?.status)

    let approvalMark: CheckItem["mark"] =
      markOf(approval?.status)

    if (
      selectedTask?.state ===
      "ready_for_approval"
    ) {
      approvalMark = "active"
    }

    if (
      selectedTask?.state ===
      "approved"
    ) {
      approvalMark = "done"
    }

    return [
      {
        key: "write-intake",
        label: "Görev planlandı",
        mark: received,
      },
      {
        key: "write-analysis",
        label:
          analystMark === "done"
            ? "Gereksinimler analiz edildi"
            : analystMark === "active"
              ? "Gereksinimler analiz ediliyor"
              : analystMark === "failed"
                ? "Analiz başarısız"
                : "Analiz bekliyor",
        mark: analystMark,
      },
      {
        key: "write-code",
        label:
          coderMark === "done"
            ? "Kod üretildi"
            : coderMark === "active"
              ? "Kod üretiliyor"
              : coderMark === "failed"
                ? "Kod üretimi başarısız"
                : "Kod üretimi bekliyor",
        mark: coderMark,
      },
      {
        key: "write-review",
        label:
          reviewerMark === "done"
            ? "Değişiklikler incelendi"
            : reviewerMark === "active"
              ? "Değişiklikler inceleniyor"
              : reviewerMark === "failed"
                ? "İnceleme başarısız"
                : "İnceleme bekliyor",
        mark: reviewerMark,
      },
      {
        key: "write-tests",
        label:
          verifierMark === "done"
            ? "Testler çalıştırıldı"
            : verifierMark === "active"
              ? "Testler çalışıyor"
              : verifierMark === "failed"
                ? "Testler başarısız"
                : "Testler bekliyor",
        mark: verifierMark,
      },
      {
        key: "write-approval",
        label:
          approvalMark === "done"
            ? "Onaylandı ve birleştirildi"
            : approvalMark === "active"
              ? "Onay bekleniyor"
              : approvalMark === "failed"
                ? "Onay / birleştirme başarısız"
                : "Onay & birleştirme bekliyor",
        mark: approvalMark,
      },
    ]
  }

  if (stages.length > 0) {
    return stages.map((stage) => ({
      key: stage.id,
      label: stage.label,
      mark: markOf(stage.status),
    }))
  }

  return [
    {
      key: "intake",
      label: "Görev alındı",
      mark: received,
    },
  ]
}

export function WorldRightRail({
  selectedTask,
  selectedProject,
  pipeline,
  pipelineStages,
  controlCenter,
  agentExecutions,
  clock,
}: Props) {
  const cc = controlCenter as unknown as CC | null
  const progress = pct(pipeline?.progress_percent)
  const exec =
    agentExecutions.find((x) => x.status === "running") ??
    agentExecutions.slice().reverse()[0]

  const taskKind =
    (
      pipeline as
        | (TaskPipeline & {
            task_kind?: string | null
          })
        | null
    )?.task_kind ?? null

  const taskKindLabel =
    taskKind === "read"
      ? "READ"
      : taskKind === "write"
        ? "WRITE"
        : "—"

  const checklist = buildChecklist(
    selectedTask,
    taskKind,
    pipeline?.stages ?? pipelineStages,
  )

  const branch = cc?.git?.branch ?? "—"

  return (
    <aside className="world-right-rail">
      <section className="world-rail-card world-active-task-card">
        <div className="world-rail-title">
          <strong>Aktif Görev</strong>
          <span className="world-clock">{clock}</span>
        </div>

        <div className="world-task-id-row">
          <span>{selectedTask?.task_id ?? "Görev seçilmedi"}</span>
          <small>{stateLabel(selectedTask?.state)}</small>
        </div>

        <h3>
          {selectedTask?.prompt ??
            "Ayrıntıları görmek için bir görev seç."}
        </h3>

        <dl className="world-task-facts">
          <div>
            <dt>Durum</dt>
            <dd className="positive">
              {stateLabel(selectedTask?.state)}
            </dd>
          </div>
          <div>
            <dt>Ajan</dt>
            <dd>{exec?.agent_name ?? "—"}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>
              {selectedTask?.model ??
                exec?.model_name ??
                "—"}
            </dd>
          </div>
          <div>
            <dt>Proje</dt>
            <dd>{selectedProject?.name ?? "—"}</dd>
          </div>
          <div>
            <dt>Dal</dt>
            <dd>{branch}</dd>
          </div>
          <div>
            <dt>Tür</dt>
            <dd>{taskKindLabel}</dd>
          </div>
        </dl>

        <div className="world-task-progress">
          <div>
            <span>İlerleme</span>
            <strong>{Math.round(progress)}%</strong>
          </div>
          <div className="world-meter">
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>

        <ul className="world-checklist">
          {checklist.map((item) => (
            <li key={item.key} className={`mark-${item.mark}`}>
              <span aria-hidden="true">
                {item.mark === "done"
                  ? "✓"
                  : item.mark === "active"
                    ? "●"
                    : item.mark === "failed"
                      ? "×"
                      : "○"}
              </span>
              <p>{item.label}</p>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  )
}
