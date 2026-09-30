import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react"

import {
  getTaskCommands,
  type Task,
  type TaskCommand,
} from "../../api"

import "./TaskTerminalPanel.css"

type Props = {
  selectedTask: Task | null
}

const ACTIVE_STATES = new Set([
  "running",
  "queued",
])

const TERMINAL_STATES = new Set([
  "completed",
  "failed",
  "approved",
  "rejected",
  "ready_for_approval",
])

function formatDuration(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) {
    return "—"
  }

  if (ms < 1000) {
    return `${Math.round(ms)} ms`
  }

  const seconds = ms / 1000

  if (seconds < 10) {
    return `${seconds.toFixed(1)} s`
  }

  return `${seconds.toFixed(1)} s`
}

function formatArgv(argv: string[]) {
  return argv.join(" ")
}

function statusMeta(status: string) {
  switch (status) {
    case "succeeded":
      return {
        mark: "✓",
        className: "status-succeeded",
        label: "succeeded",
      }
    case "failed":
      return {
        mark: "×",
        className: "status-failed",
        label: "failed",
      }
    case "timed_out":
      return {
        mark: "⚠",
        className: "status-timed-out",
        label: "timed_out",
      }
    case "rejected":
      return {
        mark: "⊘",
        className: "status-rejected",
        label: "rejected",
      }
    default:
      return {
        mark: "·",
        className: "status-unknown",
        label: status || "unknown",
      }
  }
}

function CommandRow({
  command,
}: {
  command: TaskCommand
}) {
  const meta = statusMeta(command.status)
  const argvLabel = formatArgv(command.argv)
  const showStdout =
    Boolean(command.stdout) ||
    command.stdout_truncated
  const showStderr =
    Boolean(command.stderr) ||
    command.stderr_truncated

  return (
    <article
      className={`task-terminal-command ${meta.className}`}
    >
      <div className="task-terminal-command-head">
        <span
          className="task-terminal-status"
          title={meta.label}
          aria-label={meta.label}
        >
          {meta.mark}
        </span>

        <code
          className="task-terminal-argv"
          title={argvLabel}
        >
          {argvLabel || "(empty argv)"}
        </code>
      </div>

      <div className="task-terminal-meta">
        <span className="task-terminal-badge">
          {command.execution_boundary || "—"}
        </span>
        <span className="task-terminal-badge">
          {command.network_policy || "—"}
        </span>
        <span className="task-terminal-badge">
          {command.permission_level || "—"}
        </span>
      </div>

      <div className="task-terminal-facts">
        <span>cwd: {command.cwd || "—"}</span>
        <span>
          {formatDuration(command.duration_ms)}
        </span>
        {command.exit_code !== null && (
          <span>exit {command.exit_code}</span>
        )}
      </div>

      {showStdout && (
        <details className="task-terminal-stream">
          <summary>stdout</summary>
          {command.stdout_truncated && (
            <div className="task-terminal-truncated">
              Output truncated
            </div>
          )}
          {command.stdout ? (
            <pre>{command.stdout}</pre>
          ) : null}
        </details>
      )}

      {showStderr && (
        <details className="task-terminal-stream stderr">
          <summary>stderr</summary>
          {command.stderr_truncated && (
            <div className="task-terminal-truncated">
              Output truncated
            </div>
          )}
          {command.stderr ? (
            <pre>{command.stderr}</pre>
          ) : null}
        </details>
      )}
    </article>
  )
}

export function TaskTerminalPanel({
  selectedTask,
}: Props) {
  const [commands, setCommands] = useState<
    TaskCommand[]
  >([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(
    null,
  )

  const taskId = selectedTask?.task_id ?? null
  const taskState = selectedTask?.state ?? null

  const currentTaskIdRef = useRef<string | null>(
    taskId,
  )
  const latestRequestSequenceRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true

    return () => {
      mountedRef.current = false
      latestRequestSequenceRef.current += 1
    }
  }, [])

  useEffect(() => {
    currentTaskIdRef.current = taskId
    latestRequestSequenceRef.current += 1
  }, [taskId])

  const loadCommands = useCallback(
    async (
      id: string,
      options?: {
        showLoading?: boolean
      },
    ) => {
      const requestSequence =
        ++latestRequestSequenceRef.current

      if (options?.showLoading !== false) {
        setLoading(true)
      }

      const isCurrentRequest = () =>
        mountedRef.current &&
        currentTaskIdRef.current === id &&
        latestRequestSequenceRef.current ===
          requestSequence

      try {
        const data = await getTaskCommands(id)

        if (!isCurrentRequest()) {
          return
        }

        if (data.task_id !== id) {
          return
        }

        setCommands(data.commands)
        setError(null)
      } catch {
        if (!isCurrentRequest()) {
          return
        }

        setError(
          "Terminal ge\u00e7mi\u015fi y\u00fcklenemedi.",
        )
      } finally {
        if (isCurrentRequest()) {
          setLoading(false)
        }
      }
    },
    [],
  )

  useEffect(() => {
    setCommands([])
    setError(null)

    if (!taskId) {
      setLoading(false)
      return
    }

    void loadCommands(taskId, {
      showLoading: true,
    })
  }, [taskId, loadCommands])

  useEffect(() => {
    if (!taskId || !taskState) {
      return
    }

    if (ACTIVE_STATES.has(taskState)) {
      const timer = window.setInterval(() => {
        void loadCommands(taskId, {
          showLoading: false,
        })
      }, 2000)

      return () => {
        window.clearInterval(timer)
        latestRequestSequenceRef.current += 1
      }
    }

    if (TERMINAL_STATES.has(taskState)) {
      void loadCommands(taskId, {
        showLoading: false,
      })

      return () => {
        latestRequestSequenceRef.current += 1
      }
    }
  }, [taskId, taskState, loadCommands])

  if (!selectedTask) {
    return (
      <section className="task-terminal-panel empty">
        <div className="task-terminal-empty">
          Terminal ge\u00e7mi\u015fini g\u00f6rmek
          {" "}
          i\u00e7in bir g\u00f6rev se\u00e7in.
        </div>
      </section>
    )
  }

  return (
    <section
      className="task-terminal-panel"
      aria-label="G\u00f6rev terminal ge\u00e7mi\u015fi"
    >
      <header className="task-terminal-head">
        <div>
          <span>TERMINAL</span>
          <h2>{selectedTask.task_id}</h2>
          <p>
            Ajan taraf\u0131ndan \u00e7al\u0131\u015ft\u0131r\u0131lan
            {" "}
            komut ge\u00e7mi\u015fi
          </p>
        </div>

        <div className="task-terminal-count">
          {commands.length} komut
        </div>
      </header>

      {error && (
        <div className="task-terminal-error">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => {
              void loadCommands(
                selectedTask.task_id,
                { showLoading: true },
              )
            }}
          >
            Yenile
          </button>
        </div>
      )}

      <div className="task-terminal-body">
        {loading && commands.length === 0 && !error ? (
          <div className="task-terminal-empty">
            Y\u00fckleniyor...
          </div>
        ) : !error && commands.length === 0 ? (
          <div className="task-terminal-empty">
            Bu g\u00f6rev i\u00e7in hen\u00fcz terminal
            {" "}
            komutu \u00e7al\u0131\u015ft\u0131r\u0131lmad\u0131.
          </div>
        ) : (
          <div className="task-terminal-list">
            {commands.map((command) => (
              <CommandRow
                key={command.command_id}
                command={command}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
