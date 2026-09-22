export type OpsIconName =
  | "dashboard"
  | "tasks"
  | "projects"
  | "models"
  | "agents"
  | "memory"
  | "settings"
  | "search"
  | "bell"
  | "running"
  | "queue"
  | "approval"
  | "idea"
  | "flow"
  | "code"
  | "review"
  | "verify"
  | "deploy"

export function OpsIcon({ name }: { name: OpsIconName }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.9,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  }

  switch (name) {
    case "dashboard":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path {...common} d="M4 4h7v7H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 13h7v7H4z" />
        </svg>
      )
    case "tasks":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <rect {...common} x="5" y="4" width="14" height="16" rx="2" />
          <path {...common} d="M9 4V2h6v2M8.5 10h7M8.5 14h7" />
        </svg>
      )
    case "projects":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path {...common} d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" />
          <path {...common} d="M12 12v9M3 7.5l9 4.5 9-4.5" />
        </svg>
      )
    case "models":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path {...common} d="M2 12h4l2-6 4 12 3-9 2 3h5" />
        </svg>
      )
    case "agents":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <circle {...common} cx="9" cy="8" r="3" />
          <circle {...common} cx="17" cy="9" r="2.5" />
          <path {...common} d="M3.5 20c.5-4 2.5-6 5.5-6s5 2 5.5 6" />
          <path {...common} d="M14 15c3.6-.5 5.7 1.2 6.5 4.5" />
        </svg>
      )
    case "memory":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <ellipse {...common} cx="12" cy="6" rx="7" ry="3" />
          <path {...common} d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
          <path {...common} d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
        </svg>
      )
    case "settings":
      return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <circle {...common} cx="12" cy="12" r="3" />
          <path
            {...common}
            d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"
          />
        </svg>
      )
    case "search":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle {...common} cx="10.5" cy="10.5" r="6" />
          <path {...common} d="m15 15 5 5" />
        </svg>
      )
    case "bell":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="M6 17h12l-1.5-2.4V10a4.5 4.5 0 0 0-9 0v4.6z" />
          <path {...common} d="M10 20h4" />
        </svg>
      )
    case "running":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="m13 2-7 11h6l-1 9 7-12h-6z" />
        </svg>
      )
    case "queue":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="M4 7h16M4 12h16M4 17h10" />
        </svg>
      )
    case "approval":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="M12 3 5 6v5c0 5 2.8 8.4 7 10 4.2-1.6 7-5 7-10V6z" />
          <path {...common} d="m9 12 2 2 4-5" />
        </svg>
      )
    case "idea":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="M9 18h6M10 21h4" />
          <path
            {...common}
            d="M8.5 15c-1.5-1.2-2.5-3-2.5-5a6 6 0 1 1 12 0c0 2-1 3.8-2.5 5-.8.6-1.2 1.2-1.4 2H9.9c-.2-.8-.6-1.4-1.4-2Z"
          />
        </svg>
      )
    case "flow":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle {...common} cx="8" cy="8" r="3" />
          <circle {...common} cx="16" cy="8" r="3" />
          <path {...common} d="M2.5 20c.5-4 2.5-6 5.5-6M21.5 20c-.5-4-2.5-6-5.5-6M9 20h6" />
        </svg>
      )
    case "code":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="m9 7-5 5 5 5M15 7l5 5-5 5M13 4l-2 16" />
        </svg>
      )
    case "review":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle {...common} cx="10" cy="10" r="5.5" />
          <path {...common} d="m14 14 6 6" />
        </svg>
      )
    case "verify":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="M12 3 5 6v5c0 5 2.8 8.4 7 10 4.2-1.6 7-5 7-10V6z" />
          <path {...common} d="m9 12 2 2 4-5" />
        </svg>
      )
    case "deploy":
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="M14 4c3 0 5 0 6 0 0 1 0 3-1 6l-7 7-5-5z" />
          <path {...common} d="m7 12-4 1 3 3-1 5 5-3M15 9h.01" />
        </svg>
      )
    default:
      return (
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path {...common} d="m6 12 4 4 8-9" />
        </svg>
      )
  }
}
