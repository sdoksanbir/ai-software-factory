import {
  useEffect,
  useMemo,
  useRef,
} from "react"

import type {
  AgentExecution,
  Task,
  TaskPipeline,
} from "../../api"

import "./TaskLiveActivityPanel.css"

type Props = {
  selectedTask: Task | null
  pipeline: TaskPipeline | null
  liveLogs: string[]
  agentExecutions: AgentExecution[]
}

type StepState =
  | "done"
  | "active"
  | "waiting"
  | "failed"
  | "skipped"

type Step = {
  id: string
  label: string
  state: StepState
  detail: string
}

type PipelineStageLite = {
  id: string
  label: string
  status: string
}

function normalizedTaskKind(
  selectedTask: Task | null,
  pipeline: TaskPipeline | null,
) {
  const fromPipeline =
    (
      pipeline as
        | (TaskPipeline & {
            task_kind?: string | null
          })
        | null
    )?.task_kind

  const fromTask =
    (
      selectedTask as
        | (Task & {
            task_kind?: string | null
          })
        | null
    )?.task_kind

  return fromPipeline ?? fromTask ?? null
}

function stepState(
  status: string | null | undefined,
): StepState {
  if (
    status === "completed" ||
    status === "success"
  ) {
    return "done"
  }

  if (
    status === "active" ||
    status === "running"
  ) {
    return "active"
  }

  if (
    status === "waiting" ||
    status === "ready_for_approval"
  ) {
    return "waiting"
  }

  if (
    status === "failed" ||
    status === "rejected"
  ) {
    return "failed"
  }

  if (
    status === "skipped" ||
    status === "not_required"
  ) {
    return "skipped"
  }

  return "waiting"
}

function buildSteps(
  selectedTask: Task | null,
  pipeline: TaskPipeline | null,
): Step[] {
  const stages =
    (
      pipeline?.stages ??
      []
    ) as PipelineStageLite[]

  const find = (ids: string[]) =>
    stages.find((stage) =>
      ids.some(
        (id) =>
          stage.id === id ||
          stage.id.includes(id),
      ),
    )

  const make = (
    id: string,
    label: string,
    ids: string[],
    fallbackDetail: string,
  ): Step => {
    const stage = find(ids)

    return {
      id,
      label,
      state: stepState(stage?.status),
      detail:
        stage?.label ??
        fallbackDetail,
    }
  }

  const kind =
    normalizedTaskKind(
      selectedTask,
      pipeline,
    )

  if (kind === "read") {
    const resultState: StepState =
      selectedTask?.state === "completed"
        ? "done"
        : selectedTask?.state === "failed"
          ? "failed"
          : stepState(
              find(["completed"])
                ?.status,
            )

    return [
      make(
        "read-task",
        "Görev alındı",
        ["task"],
        "Görev hazırlanıyor",
      ),
      make(
        "read-analysis",
        "Proje analizi",
        ["repo_analysis"],
        "Proje analizi bekliyor",
      ),
      make(
        "read-model",
        "Yanıt üretimi",
        ["model"],
        "Model sırasını bekliyor",
      ),
      {
        id: "read-result",
        label: "Sonuç",
        state: resultState,
        detail:
          resultState === "done"
            ? "Yanıt hazır"
            : resultState === "failed"
              ? "Görev tamamlanamadı"
              : "Sonuç bekleniyor",
      },
    ]
  }

  if (kind === "write") {
    let approvalState =
      stepState(
        find(["approval", "merge"])
          ?.status,
      )

    if (
      selectedTask?.state ===
      "ready_for_approval"
    ) {
      approvalState = "waiting"
    }

    if (
      selectedTask?.state ===
      "approved"
    ) {
      approvalState = "done"
    }

    return [
      make(
        "write-task",
        "Görev hazırlanıyor",
        ["task", "worktree"],
        "Görev / worktree hazırlanıyor",
      ),
      make(
        "write-analysis",
        "Proje analizi",
        ["repo_analysis", "analysis"],
        "Analiz bekliyor",
      ),
      make(
        "write-model",
        "Kod üretimi",
        ["model", "write", "code"],
        "Model sırasını bekliyor",
      ),
      make(
        "write-review",
        "Değişiklik inceleme",
        ["patch", "diff", "review"],
        "İnceleme bekliyor",
      ),
      make(
        "write-tests",
        "Testler",
        ["tests", "test", "verify"],
        "Testler bekliyor",
      ),
      {
        id: "write-approval",
        label: "Onay & birleştirme",
        state: approvalState,
        detail:
          selectedTask?.state ===
          "ready_for_approval"
            ? "Kullanıcı onayı bekleniyor"
            : selectedTask?.state ===
                "approved"
              ? "Onaylandı ve birleştirildi"
              : "Onay aşaması bekliyor",
      },
    ]
  }

  return stages.map((stage) => ({
    id: stage.id,
    label: stage.label,
    state: stepState(stage.status),
    detail: stage.label,
  }))
}

function stateText(
  state: StepState,
) {
  const labels: Record<
    StepState,
    string
  > = {
    done: "Tamamlandı",
    active: "Çalışıyor",
    waiting: "Bekliyor",
    failed: "Hata",
    skipped: "Gerekmiyor",
  }

  return labels[state]
}

function taskStatusText(
  state: string | null | undefined,
) {
  const labels: Record<string, string> = {
    queued: "Sırada",
    running: "Çalışıyor",
    ready_for_approval:
      "Onay Bekliyor",
    approved: "Tamamlandı",
    completed: "Tamamlandı",
    failed: "Başarısız",
    rejected: "Reddedildi",
  }

  return (
    labels[state ?? ""] ??
    state ??
    "Bekliyor"
  )
}

function humanizeLog(
  message: string,
) {
  const normalized =
    message.trim()

  if (
    /görev sıraya alındı|gorev siraya alindi/i.test(
      normalized,
    )
  ) {
    return "Görev kuyruğa alındı."
  }

  const router =
    normalized.match(
      /Task Router:\s*(READ|WRITE|EXECUTE)/i,
    )

  if (router) {
    return `Görev türü belirlendi: ${router[1].toUpperCase()}.`
  }

  if (
    /READ gorevi calistiriliyor/i.test(
      normalized,
    )
  ) {
    return "READ görevi çalıştırılıyor."
  }

  if (
    /WRITE gorevi calistiriliyor/i.test(
      normalized,
    )
  ) {
    return "WRITE görevi çalıştırılıyor."
  }

  if (
    /EXECUTE gorevi calistiriliyor/i.test(
      normalized,
    )
  ) {
    return "EXECUTE görevi çalıştırılıyor."
  }

  if (
    /EXECUTE gorevi tamamlandi/i.test(
      normalized,
    )
  ) {
    return "EXECUTE görevi tamamlandı."
  }

  if (
    /worktree/i.test(normalized) &&
    /oluştur|olustur|created|hazır|hazir/i.test(
      normalized,
    )
  ) {
    return "İzole çalışma alanı hazırlandı."
  }

  if (
    /test/i.test(normalized) &&
    /başar|basar|passed|success/i.test(
      normalized,
    )
  ) {
    return "Testler başarıyla tamamlandı."
  }

  if (
    /basarisiz|başarısız|failed|error|hata/i.test(
      normalized,
    )
  ) {
    return "İşlem sırasında hata oluştu."
  }

  return normalized
}

export function TaskLiveActivityPanel({
  selectedTask,
  pipeline,
  liveLogs,
  agentExecutions,
}: Props) {
  const logBoxRef =
    useRef<HTMLDivElement | null>(
      null,
    )

  const steps = useMemo(
    () =>
      buildSteps(
        selectedTask,
        pipeline,
      ),
    [selectedTask, pipeline],
  )

  const currentExecution =
    agentExecutions.find(
      (item) =>
        item.status === "running",
    ) ??
    agentExecutions.at(-1) ??
    null

  const kind =
    normalizedTaskKind(
      selectedTask,
      pipeline,
    )

  const isLive =
    selectedTask?.state ===
      "running" ||
    selectedTask?.state ===
      "queued"

  const lastLog =
    liveLogs.at(-1) ?? null

  useEffect(() => {
    const element =
      logBoxRef.current

    if (!element) return

    element.scrollTop =
      element.scrollHeight
  }, [liveLogs])

  if (!selectedTask) {
    return (
      <section className="task-live-panel empty">
        <div className="task-live-empty">
          Canlı işlemleri görmek için bir görev seç.
        </div>
      </section>
    )
  }

  return (
    <section
      className="task-live-panel"
      aria-label="Canlı işlem akışı"
    >
      <header className="task-live-head">
        <div>
          <span>CANLI GÖREV DURUMU</span>
          <h2>Görev İzleme</h2>
          <p>
            {selectedTask.task_id}
            {" · "}
            {kind
              ? kind.toUpperCase()
              : "AUTO"}
          </p>
        </div>

        <div
          className={`task-live-badge ${
            isLive
              ? "live"
              : "idle"
          }`}
        >
          <i />
          {isLive
            ? "CANLI"
            : taskStatusText(
                selectedTask.state,
              )}
        </div>
      </header>

      <div className="task-live-now">
        <div className="task-live-now-copy">
          <span>
            {isLive ? "ŞU AN" : "SON DURUM"}
          </span>
          <strong>
            {isLive && lastLog
              ? humanizeLog(lastLog)
              : taskStatusText(
                  selectedTask.state,
                )}
          </strong>
        </div>

        {currentExecution && (
          <div className="task-live-agent">
            <span>
              {isLive ? "AKTİF AJAN" : "SON AJAN"}
            </span>
            <strong>
              {currentExecution.agent_name}
            </strong>
            <small>
              {currentExecution.model_name ??
                currentExecution.provider_name}
            </small>
          </div>
        )}
      </div>

      <div className="task-live-step-grid">
        {steps.map(
          (step, index) => (
            <div
              key={step.id}
              className={`task-live-step state-${step.state}`}
            >
              <div className="task-live-step-index">
                {step.state ===
                "done"
                  ? "✓"
                  : step.state ===
                      "failed"
                    ? "×"
                    : index + 1}
              </div>

              <div className="task-live-step-copy">
                <strong>{step.label}</strong>
                <span>{step.detail}</span>
              </div>

              <small>
                {stateText(step.state)}
              </small>
            </div>
          ),
        )}
      </div>

    </section>
  )
}
