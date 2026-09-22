import type { CSSProperties } from "react"
import type {
  AgentExecution,
  ControlCenterStatus,
  Task,
} from "../../api"

import "./AgentWorld.css"

type WorldStage = {
  key: string
  label: string
  caption: string
  role: string
  state:
    | "completed"
    | "active"
    | "waiting"
    | "failed"
    | "pending"
  accent: string
}

type Props = {
  stages: WorldStage[]
  selectedTask: Task | null
  agentExecutions: AgentExecution[]
  liveLogs: string[]
  availableModels: string[]
  controlCenter: ControlCenterStatus | null
}

type IslandKind =
  | "analysis"
  | "code"
  | "review"
  | "test"
  | "approval"
  | "deploy"
  | "models"
  | "memory"
  | "git"

type IslandProps = {
  kind: IslandKind
  title: string
  subtitle: string
  state?: WorldStage["state"]
  x: number
  y: number
  accent: string
  bubble?: string | null
  onClick?: () => void
}

function goTo(id: string) {
  document.getElementById(id)?.scrollIntoView({
    behavior: "smooth",
    block: "start",
  })
}

function stateText(state: WorldStage["state"] | undefined) {
  if (state === "active") return "Çalışıyor"
  if (state === "completed") return "Tamamlandı"
  if (state === "failed") return "Hata"
  if (state === "waiting") return "Bekliyor"
  return "Sırada"
}

function IslandArt({
  kind,
  accent,
}: {
  kind: IslandKind
  accent: string
}) {
  const uid = `isl-${kind}`

  const glyph =
    kind === "code"
      ? "</>"
      : kind === "review"
        ? "🔍"
        : kind === "test"
          ? "⚗"
          : kind === "approval"
            ? "✓"
            : kind === "deploy"
              ? "🚀"
              : kind === "models"
                ? "▣"
                : kind === "memory"
                  ? "☰"
                  : kind === "git"
                    ? "⑂"
                    : "📄"

  return (
    <svg
      className="island-art"
      viewBox="0 0 140 120"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`${uid}-grass`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7dce6a" />
          <stop offset="55%" stopColor="#4faa4a" />
          <stop offset="100%" stopColor="#2f7a38" />
        </linearGradient>
        <linearGradient id={`${uid}-rock`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#6a8a6e" />
          <stop offset="40%" stopColor="#4a6350" />
          <stop offset="100%" stopColor="#2c3d34" />
        </linearGradient>
        <linearGradient id={`${uid}-roof`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={accent} />
          <stop offset="100%" stopColor="#1a2a44" />
        </linearGradient>
        <linearGradient id={`${uid}-bot`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#f4fbff" />
          <stop offset="100%" stopColor={accent} />
        </linearGradient>
        <filter id={`${uid}-soft`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.2" />
        </filter>
      </defs>

      {/* shadow */}
      <ellipse cx="70" cy="108" rx="48" ry="8" fill="rgba(0,0,0,.35)" />

      {/* cliff / rock base */}
      <path
        d="M22 78 C28 92 48 100 70 100 C92 100 112 92 118 78 L110 70 C100 78 84 84 70 84 C56 84 40 78 30 70 Z"
        fill={`url(#${uid}-rock)`}
      />
      <path
        d="M26 76 C34 86 50 92 70 92 C90 92 106 86 114 76 L108 68 C98 76 84 80 70 80 C56 80 42 76 32 68 Z"
        fill="#3d5444"
        opacity=".55"
      />

      {/* grassy top */}
      <ellipse
        cx="70"
        cy="68"
        rx="52"
        ry="22"
        fill={`url(#${uid}-grass)`}
      />
      <ellipse
        cx="70"
        cy="64"
        rx="44"
        ry="16"
        fill="rgba(180,240,140,.28)"
      />

      {/* trees */}
      <g className="island-trees">
        <ellipse cx="28" cy="62" rx="7" ry="9" fill="#2f8f45" />
        <rect x="26.5" y="68" width="3" height="6" rx="1" fill="#6b4423" />
        <ellipse cx="112" cy="60" rx="8" ry="10" fill="#278a42" />
        <rect x="110.5" y="67" width="3" height="7" rx="1" fill="#6b4423" />
        <ellipse cx="40" cy="58" rx="5" ry="7" fill="#3aa354" />
      </g>

      {/* building */}
      <g className="island-building">
        <path
          d="M48 42 L70 28 L92 42 L92 44 L48 44 Z"
          fill={`url(#${uid}-roof)`}
        />
        <rect x="52" y="44" width="36" height="26" rx="2" fill="#e8f2ff" />
        <rect x="52" y="44" width="36" height="26" rx="2" fill="rgba(40,80,140,.12)" />
        <rect x="58" y="50" width="8" height="8" rx="1.5" fill="#12304a" />
        <rect x="74" y="50" width="8" height="8" rx="1.5" fill="#12304a" />
        <rect x="66" y="58" width="8" height="12" rx="1" fill="#1a3a55" />
        <rect x="86" y="34" width="5" height="12" rx="1" fill="#8a6a55" />
        <text
          x="70"
          y="40"
          textAnchor="middle"
          fontSize="9"
          fontWeight="800"
          fill="#fff"
          opacity=".9"
        >
          {glyph}
        </text>
      </g>

      {/* robot */}
      <g className="island-bot" transform="translate(86 48)">
        <ellipse cx="16" cy="36" rx="10" ry="3" fill="rgba(0,0,0,.25)" />
        <rect
          x="6"
          y="14"
          width="20"
          height="18"
          rx="7"
          fill={`url(#${uid}-bot)`}
          stroke="rgba(255,255,255,.55)"
          strokeWidth="1.2"
        />
        <rect
          x="8"
          y="4"
          width="16"
          height="14"
          rx="6"
          fill="#eef8ff"
          stroke={accent}
          strokeWidth="1.2"
        />
        <rect x="11" y="8" width="10" height="6" rx="3" fill="#0b2137" />
        <circle cx="13.5" cy="11" r="1.1" fill={accent} />
        <circle cx="18.5" cy="11" r="1.1" fill={accent} />
        <path
          d="M13 14.5c2 1.2 4 1.2 6 0"
          stroke={accent}
          strokeWidth="1"
          fill="none"
          strokeLinecap="round"
        />
        <line
          x1="16"
          y1="4"
          x2="16"
          y2="1"
          stroke={accent}
          strokeWidth="1.4"
          strokeLinecap="round"
        />
        <circle cx="16" cy="0.5" r="1.3" fill={accent} />
        <rect x="2" y="16" width="5" height="10" rx="2.5" fill={accent} />
        <rect x="25" y="16" width="5" height="10" rx="2.5" fill={accent} />
        <rect x="9" y="30" width="5" height="7" rx="2" fill="#cfe6f6" />
        <rect x="18" y="30" width="5" height="7" rx="2" fill="#cfe6f6" />
      </g>
    </svg>
  )
}

function WorldIsland({
  kind,
  title,
  subtitle,
  state,
  x,
  y,
  accent,
  bubble,
  onClick,
}: IslandProps) {
  return (
    <button
      type="button"
      className={`world-island world-island-${kind} state-${state ?? "pending"}`}
      style={
        {
          left: `${x}%`,
          top: `${y}%`,
          "--island-accent": accent,
        } as CSSProperties
      }
      onClick={onClick}
    >
      {bubble && (
        <div className="world-task-bubble">
          <small>GÖREV</small>
          <span>{bubble}</span>
        </div>
      )}

      <div className="world-island-label">
        <strong>{title}</strong>
      </div>

      <div className="world-island-platform">
        <IslandArt kind={kind} accent={accent} />
      </div>

      <div className="world-island-status">
        <span>{subtitle}</span>
        {state && (
          <small>
            <i />
            {stateText(state)}
          </small>
        )}
      </div>
    </button>
  )
}

export function AgentWorld({
  stages,
  selectedTask,
  agentExecutions,
  liveLogs,
  availableModels,
  controlCenter,
}: Props) {
  const stage = (index: number) =>
    stages[index] ?? {
      key: "pending",
      label: "Bekliyor",
      caption: "Henüz başlamadı",
      role: "System",
      state: "pending" as const,
      accent: "blue",
    }

  const analysis = stage(1)
  const code = stage(2)
  const review = stage(3)
  const test = stage(4)
  const approval = stage(5)

  const cc = controlCenter as unknown as {
    project_memory?: { active?: number }
    git?: { branch?: string; clean?: boolean }
    agents?: { ready?: number; total?: number }
  } | null

  const currentExecution =
    agentExecutions.find((execution) => execution.status === "running") ??
    agentExecutions.slice().reverse()[0]

  const lastLog = liveLogs[liveLogs.length - 1] ?? "Canlı işlem bekleniyor"

  const activeBubble =
    selectedTask &&
    (selectedTask.state === "running" ||
      selectedTask.state === "queued" ||
      selectedTask.state === "ready_for_approval")
      ? `${selectedTask.task_id}: ${selectedTask.prompt.slice(0, 36)}${
          selectedTask.prompt.length > 36 ? "…" : ""
        }`
      : null

  const bubbleFor = (s: WorldStage["state"]) =>
    s === "active" || s === "waiting" ? activeBubble : null

  // Positions kept well inside the map box (safe inset margins).
  const islands: Array<IslandProps> = [
    {
      kind: "analysis",
      title: "ANALİST",
      subtitle: analysis.caption,
      state: analysis.state,
      x: 18,
      y: 18,
      accent: "#4da7ff",
      bubble: bubbleFor(analysis.state),
      onClick: () => goTo("world-agents"),
    },
    {
      kind: "code",
      title: "KODLAYICI",
      subtitle: code.caption,
      state: code.state,
      x: 42,
      y: 12,
      accent: "#9a71ff",
      bubble: bubbleFor(code.state),
      onClick: () => goTo("world-tasks"),
    },
    {
      kind: "review",
      title: "İNCELEYİCİ",
      subtitle: review.caption,
      state: review.state,
      x: 66,
      y: 16,
      accent: "#47a8ff",
      bubble: bubbleFor(review.state),
      onClick: () => goTo("world-agents"),
    },
    {
      kind: "test",
      title: "DOĞRULAYICI",
      subtitle: test.caption,
      state: test.state,
      x: 82,
      y: 28,
      accent: "#48e0b4",
      bubble: bubbleFor(test.state),
      onClick: () => goTo("world-agents"),
    },
    {
      kind: "models",
      title: "Modeller",
      subtitle: `${availableModels.length} yerel model`,
      x: 14,
      y: 48,
      accent: "#4da7ff",
      onClick: () => goTo("world-models"),
    },
    {
      kind: "memory",
      title: "Hafıza",
      subtitle: `${cc?.project_memory?.active ?? 0} aktif kayıt`,
      x: 20,
      y: 72,
      accent: "#a47bff",
      onClick: () => goTo("world-memory"),
    },
    {
      kind: "git",
      title: "Git / Worktree",
      subtitle: cc?.git?.branch ?? "branch bekleniyor",
      x: 44,
      y: 78,
      accent: "#5ade99",
      onClick: () => goTo("world-projects"),
    },
    {
      kind: "approval",
      title: "Onay",
      subtitle: approval.caption,
      state: approval.state,
      x: 68,
      y: 74,
      accent: "#42dfa5",
      bubble: bubbleFor(approval.state),
      onClick: () => goTo("world-tasks"),
    },
    {
      kind: "deploy",
      title: "Dağıtım",
      subtitle:
        selectedTask?.state === "approved" ? "Yayında" : "Beklemede",
      state:
        selectedTask?.state === "approved" ? "completed" : "pending",
      x: 84,
      y: 54,
      accent: "#ff9d4a",
      onClick: () => goTo("world-tasks"),
    },
  ]

  return (
    <section className="agent-world" id="world-overview">
      <div className="agent-world-stars" />
      <div className="agent-world-vignette" />

      <div className="agent-world-float-copy left">
        Fikirlerden gerçek ürünlere
      </div>
      <div className="agent-world-float-copy right">
        Ajanlar birlikte çalışır
      </div>

      <div className="agent-world-map">
        <svg
          className="agent-world-routes"
          viewBox="0 0 1000 640"
          preserveAspectRatio="xMidYMid meet"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id="routeGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#3aa9ff" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#8b6cff" stopOpacity="0.7" />
            </linearGradient>
          </defs>

          {/* Static dotted spokes — no animation */}
          <path d="M500 320 L180 160" />
          <path d="M500 320 L420 100" />
          <path d="M500 320 L660 130" />
          <path d="M500 320 L820 210" />
          <path d="M500 320 L140 360" />
          <path d="M500 320 L200 520" />
          <path d="M500 320 L440 560" />
          <path d="M500 320 L680 530" />
          <path d="M500 320 L840 400" />
        </svg>

        {islands.map((island) => (
          <WorldIsland key={island.kind} {...island} />
        ))}

        <div className="world-core">
          <div className="world-core-ring" />
          <div className="world-core-platform">
            <div className="world-core-crystal">
              <i />
              <i />
              <i />
            </div>
            <strong>
              AI SOFTWARE
              <br />
              FACTORY
            </strong>
            <span>Ajanlar · Veri · Daha İyi Yazılım</span>
          </div>
        </div>
      </div>

      <div className="world-live-command">
        <span>{currentExecution?.agent_name ?? "Sistem"}</span>
        <strong>
          {selectedTask ? selectedTask.prompt : "Görev seçilmedi"}
        </strong>
        <small>{lastLog}</small>
      </div>
    </section>
  )
}
