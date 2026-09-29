import type {
  AgentExecution,
  Task,
  TaskKind,
} from "../../api"

import "./TaskTechnicalDetailsPanel.css"

type Props = {
  selectedTask: Task | null
  agentExecutions: AgentExecution[]
  liveLogs: string[]
  diff: string
  loadingDiff: boolean
  onLoadDiff: () => void
  taskKind: TaskKind | null
}

function cleanModelName(
  provider: string,
  model: string,
) {
  const normalized =
    provider.trim().toLowerCase()

  if (
    normalized === "ollama" &&
    model.startsWith("ollama/")
  ) {
    return model.slice("ollama/".length)
  }

  if (
    normalized === "openrouter" &&
    model.startsWith("openrouter/")
  ) {
    return model.slice("openrouter/".length)
  }

  return model
}

function textMeta(
  execution: AgentExecution | null,
  key: string,
) {
  const value = execution?.metadata?.[key]
  return typeof value === "string" && value.trim()
    ? value.trim()
    : null
}

function boolMeta(
  execution: AgentExecution | null,
  key: string,
) {
  return execution?.metadata?.[key] === true
}

function statusText(status: string) {
  const labels: Record<string, string> = {
    running: "Çalışıyor",
    completed: "Tamamlandı",
    failed: "Başarısız",
  }

  return labels[status] ?? status
}

export function TaskTechnicalDetailsPanel({
  selectedTask,
  agentExecutions,
  liveLogs,
  diff,
  loadingDiff,
  onLoadDiff,
  taskKind,
}: Props) {
  if (!selectedTask) return null

  const executions = agentExecutions
    .slice()
    .sort(
      (a, b) =>
        new Date(a.started_at).getTime() -
        new Date(b.started_at).getTime(),
    )

  const coderExecution =
    executions
      .slice()
      .reverse()
      .find((item) => {
        const stepKind =
          typeof item.metadata?.step_kind === "string"
            ? item.metadata.step_kind
            : ""

        return (
          !!item.model_name &&
          (
            stepKind === "write" ||
            /coder|write/i.test(item.agent_name)
          )
        )
      }) ??
    executions
      .slice()
      .reverse()
      .find((item) => !!item.model_name) ??
    null

  const actualProvider =
    coderExecution?.provider_name ?? "—"

  const rawActualModel =
    coderExecution?.model_name ?? "—"

  const actualModel =
    rawActualModel === "—"
      ? rawActualModel
      : cleanModelName(
          actualProvider,
          rawActualModel,
        )

  const configuredProvider =
    textMeta(
      coderExecution,
      "configured_provider",
    )

  const rawConfiguredModel =
    textMeta(
      coderExecution,
      "configured_model",
    )

  const configuredModel =
    configuredProvider &&
    rawConfiguredModel
      ? cleanModelName(
          configuredProvider,
          rawConfiguredModel,
        )
      : rawConfiguredModel

  const fallbackUsed =
    boolMeta(
      coderExecution,
      "fallback",
    ) ||
    boolMeta(
      coderExecution,
      "fallback_used",
    )

  const routeText =
    fallbackUsed
      ? `${configuredProvider ?? "primary"}${
          configuredModel
            ? ` / ${configuredModel}`
            : ""
        } → ${actualProvider}${
          actualModel !== "—"
            ? ` / ${actualModel}`
            : ""
        }`
      : "Doğrudan çalışma"

  return (
    <div className="task-tech-layout">
      <section className="task-tech-panel task-tech-main">
        <header className="task-tech-head">
          <div>
            <span>GÖREV TEKNİĞİ</span>
            <h2>Teknik Ayrıntılar</h2>
            <p>
              Model rotası, ajan çalışmaları ve ham kayıtlar.
            </p>
          </div>

          <div className="task-tech-count">
            {executions.length} yürütme · {liveLogs.length} log
          </div>
        </header>

        <div className="task-tech-summary">
          <div>
            <span>Provider</span>
            <strong>{actualProvider}</strong>
          </div>

          <div>
            <span>Model</span>
            <strong>{actualModel}</strong>
          </div>

          <div className={fallbackUsed ? "fallback" : ""}>
            <span>Model Rotası</span>
            <strong>{routeText}</strong>
          </div>
        </div>

        <div className="task-tech-main-grid">
          <section className="task-tech-section">
            <div className="task-tech-section-head">
              <div>
                <span>AJANLAR</span>
                <strong>Ajan Yürütmeleri</strong>
              </div>
              <small>{executions.length}</small>
            </div>

            <div className="task-tech-execution-list">
              {executions.length === 0 ? (
                <div className="task-tech-empty">
                  Henüz ajan yürütmesi yok.
                </div>
              ) : (
                executions
                  .slice()
                  .reverse()
                  .map((execution) => {
                    const provider =
                      execution.provider_name || "—"

                    const rawModel =
                      execution.model_name

                    const model =
                      rawModel
                        ? cleanModelName(
                            provider,
                            rawModel,
                          )
                        : null

                    return (
                      <div
                        className="task-tech-execution"
                        key={execution.execution_id}
                      >
                        <div>
                          <strong>
                            {execution.agent_name}
                          </strong>
                          <span>
                            {provider}
                            {model
                              ? ` / ${model}`
                              : ""}
                          </span>
                        </div>

                        <small
                          className={`status-${execution.status}`}
                        >
                          {statusText(
                            execution.status,
                          )}
                          {execution.duration_ms != null
                            ? ` · ${(execution.duration_ms / 1000).toFixed(1)} sn`
                            : ""}
                        </small>

                        {execution.error && (
                          <p>{execution.error}</p>
                        )}
                      </div>
                    )
                  })
              )}
            </div>
          </section>

          <section className="task-tech-section">
            <div className="task-tech-section-head">
              <div>
                <span>KAYITLAR</span>
                <strong>Ham Loglar</strong>
              </div>
              <small>{liveLogs.length}</small>
            </div>

            <div className="task-tech-logbox">
              {liveLogs.length === 0 ? (
                <div className="task-tech-empty">
                  Henüz log kaydı yok.
                </div>
              ) : (
                liveLogs.map(
                  (message, index) => (
                    <div
                      className="task-tech-log-row"
                      key={`${index}-${message}`}
                    >
                      <span>
                        #
                        {String(index + 1).padStart(
                          2,
                          "0",
                        )}
                      </span>
                      <code>{message}</code>
                    </div>
                  ),
                )
              )}
            </div>
          </section>
        </div>
      </section>

      {taskKind === "write" && (
        <section className="task-tech-panel task-tech-diff-panel">
          <header className="task-tech-head task-tech-diff-head">
            <div>
              <span>DEĞİŞİKLİKLER</span>
              <h2>Diff</h2>
              <p>
                Görev tarafından yapılan dosya değişiklikleri.
              </p>
            </div>

            <button
              type="button"
              className="task-tech-diff-button"
              onClick={onLoadDiff}
              disabled={loadingDiff}
            >
              {loadingDiff
                ? "Yükleniyor..."
                : diff
                  ? "Yenile"
                  : "Diff'i Göster"}
            </button>
          </header>

          <div className="task-tech-diff">
            {diff ? (
              <pre>{diff}</pre>
            ) : (
              <div className="task-tech-empty">
                Diff henüz yüklenmedi.
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
