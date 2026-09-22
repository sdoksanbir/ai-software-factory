import type {
  AgentExecution,
  Task,
} from "../../api"

import "./TaskHistoryPanel.css"

type PipelineStage = {
  id: string
  label: string
  status: string
}

type Props = {
  selectedTask: Task | null
  pipelineStages: PipelineStage[]
  agentExecutions: AgentExecution[]
  liveLogs: string[]
}

function statusLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    queued: "Sırada",
    running: "Çalışıyor",
    ready_for_approval: "Onay Bekliyor",
    approved: "Tamamlandı",
    completed: "Tamamlandı",
    success: "Tamamlandı",
    rejected: "Reddedildi",
    failed: "Başarısız",
    pending: "Sırada",
    active: "Çalışıyor",
    waiting: "Onay Bekliyor",
    skipped: "Gerekmiyor",
    not_required: "Gerekmiyor",
  }

  return labels[value ?? ""] ?? value ?? "Bekliyor"
}

function visualState(value: string) {
  if (value === "completed" || value === "success") return "completed"
  if (value === "active" || value === "running") return "active"
  if (value === "waiting" || value === "ready_for_approval") return "waiting"
  if (value === "failed" || value === "rejected") return "failed"
  if (value === "skipped" || value === "not_required") return "skipped"
  return "pending"
}

function formatTime(value: string | null) {
  if (!value) return "—"

  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return "—"

  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date)
}

type FailureInfo = {
  title: string
  detail: string
}

function failureFromLogs(
  logs: string[],
): FailureInfo | null {
  const raw =
    logs
      .slice()
      .reverse()
      .find((message) =>
        /basarisiz|başarısız|hata|failed|error|could not be reached|ulaşılamadı/i.test(
          message,
        ),
      ) ?? null

  if (!raw) return null

  const detail = raw
    .replace(/^READ gorevi basarisiz:\s*/i, "")
    .replace(/^Görev başarısız:\s*/i, "")
    .trim()

  const lower =
    detail.toLocaleLowerCase("tr-TR")

  if (
    lower.includes("ollama server could not be reached") ||
    (
      lower.includes("ollama") &&
      lower.includes("ulaşılam")
    )
  ) {
    return {
      title: "Ollama servisine ulaşılamadı",
      detail,
    }
  }

  if (
    lower.includes("model") &&
    (
      lower.includes("not found") ||
      lower.includes("bulunamad")
    )
  ) {
    return {
      title: "Model bulunamadı",
      detail,
    }
  }

  if (
    lower.includes("timeout") ||
    lower.includes("timed out")
  ) {
    return {
      title: "Model zaman aşımına uğradı",
      detail,
    }
  }

  return {
    title: "Görev çalıştırılırken hata oluştu",
    detail,
  }
}

export function TaskHistoryPanel({
  selectedTask,
  pipelineStages,
  agentExecutions,
  liveLogs,
}: Props) {
  if (!selectedTask) return null

  const failedExecution =
    agentExecutions
      .slice()
      .reverse()
      .find(
        (execution) =>
          execution.status === "failed" &&
          !!execution.error,
      ) ?? null

  const logFailure =
    failureFromLogs(liveLogs)

  const failureInfo: FailureInfo | null =
    failedExecution?.error
      ? {
          title: "Ajan yürütmesi başarısız oldu",
          detail: failedExecution.error,
        }
      : logFailure

  const executions = agentExecutions
    .slice()
    .sort(
      (a, b) =>
        new Date(a.started_at).getTime() -
        new Date(b.started_at).getTime(),
    )

  return (
    <section className="task-history-panel">
      <header className="task-history-header">
        <div>
          <span>GÖREV TARİHÇESİ</span>
          <h2>{selectedTask.task_id}</h2>
          <p>{selectedTask.prompt}</p>
        </div>

        <strong
          className={`task-history-current state-${selectedTask.state}`}
        >
          {statusLabel(selectedTask.state)}
        </strong>
      </header>

      <div className="task-history-stages">
        {pipelineStages.map((stage) => (
          <div
            key={stage.id}
            className={`state-${visualState(stage.status)}`}
          >
            <i />
            <span>
              <b>{stage.label}</b>
              <small>{statusLabel(stage.status)}</small>
            </span>
          </div>
        ))}
      </div>

      {selectedTask.state === "failed" && (
        <div
          className="task-history-failure"
          role="alert"
        >
          <div className="task-history-failure-icon">
            !
          </div>

          <div>
            <span>HATA NEDENİ</span>

            <strong>
              {failureInfo?.title ??
                "Görev başarısız oldu"}
            </strong>

            <p>
              {failureInfo?.detail ??
                "Ayrıntılı hata kaydı bulunamadı. Görev loglarını kontrol edin."}
            </p>
          </div>
        </div>
      )}

      <div className="task-history-timeline">
        <article className="state-completed">
          <time>{formatTime(selectedTask.started_at)}</time>
          <div>
            <strong>Görev oluşturuldu</strong>
            <p>{selectedTask.prompt}</p>
          </div>
        </article>

        {executions.length === 0 ? (
          <div className="task-history-empty">
            {selectedTask.state === "failed"
              ? "Bu görev ajan yürütme kaydı oluşturmadan başarısız oldu. Hata nedeni yukarıda gösteriliyor."
              : "Bu görev için henüz ajan yürütme kaydı yok."}
          </div>
        ) : (
          executions.map((execution) => (
            <div key={execution.execution_id}>
              <article
                className={
                  execution.status === "running"
                    ? "state-active"
                    : "state-completed"
                }
              >
                <time>{formatTime(execution.started_at)}</time>
                <div>
                  <strong>{execution.agent_name} başladı</strong>
                  <p>
                    {execution.provider_name}
                    {execution.model_name
                      ? ` / ${execution.model_name}`
                      : ""}
                  </p>
                </div>
              </article>

              {execution.completed_at && (
                <article
                  className={
                    execution.status === "failed"
                      ? "state-failed"
                      : "state-completed"
                  }
                >
                  <time>{formatTime(execution.completed_at)}</time>
                  <div>
                    <strong>
                      {execution.agent_name}{" "}
                      {execution.status === "failed"
                        ? "başarısız"
                        : "tamamlandı"}
                    </strong>
                    <p>
                      {execution.status === "failed"
                        ? execution.error ??
                          "Ajan çalışması başarısız oldu."
                        : execution.duration_ms != null
                          ? `Süre: ${(execution.duration_ms / 1000).toFixed(1)} sn`
                          : "Ajan çalışması tamamlandı."}
                    </p>
                  </div>
                </article>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  )
}
