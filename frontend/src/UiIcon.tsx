import {
  Activity,
  Bot,
  Boxes,
  Check,
  ClipboardList,
  Container,
  Cpu,
  Database,
  Factory,
  FileDiff,
  Folder,
  FolderKanban,
  FolderOpen,
  Gauge,
  GitBranch,
  History,
  LayoutDashboard,
  ListChecks,
  Logs,
  Search,
  SearchCode,
  Server,
  Settings,
  TerminalSquare,
  UserCheck,
  Wrench,
} from "lucide-react"

type UiIconProps = {
  name: string
  className?: string
}

const ICONS = {
  factory: Factory,
  dashboard: LayoutDashboard,
  overview: LayoutDashboard,
  tasks: ClipboardList,
  task: ClipboardList,
  projects: FolderKanban,
  folder: Folder,
  open: FolderOpen,
  models: Boxes,
  model: Bot,
  settings: Settings,
  running: Activity,
  history: History,
  worktree: GitBranch,
  repo_analysis: SearchCode,
  patch: Wrench,
  tests: Container,
  diff: FileDiff,
  approval: UserCheck,
  logs: Logs,
  result: ListChecks,
  cpu: Cpu,
  sqlite: Database,
  search: Search,
  check: Check,
  terminal: TerminalSquare,
  server: Server,
  gauge: Gauge,
} as const

export function UiIcon({
  name,
  className = "",
}: UiIconProps) {
  const Icon =
    ICONS[name as keyof typeof ICONS] ??
    Activity

  return (
    <Icon
      className={`ui-icon ${className}`}
      aria-hidden="true"
      strokeWidth={1.8}
    />
  )
}
