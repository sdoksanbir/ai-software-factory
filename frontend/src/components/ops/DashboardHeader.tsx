import { OpsIcon } from "./opsIcons"

type Props = {
  runningCount: number
  onNewTask: () => void
  onNotifyClick?: () => void
}

export function DashboardHeader({
  runningCount,
  onNewTask,
  onNotifyClick,
}: Props) {
  return (
    <header className="ops-header">
      <div className="ops-header-brand">
        <h1>AI Software Factory</h1>
        <p>AI ekibin bugün harika şeyler üretiyor.</p>
      </div>

      <label className="ops-search">
        <OpsIcon name="search" />
        <input
          placeholder="Görev, proje veya ajan ara..."
          aria-label="Ara"
          readOnly
        />
      </label>

      <div className="ops-header-actions">
        <button
          type="button"
          className="ops-bell"
          aria-label="Bildirimler"
          onClick={onNotifyClick}
        >
          <OpsIcon name="bell" />
          {runningCount > 0 && (
            <span>{Math.min(9, runningCount)}</span>
          )}
        </button>

        <button
          type="button"
          className="ops-new-task-btn"
          onClick={onNewTask}
        >
          + Yeni Görev
        </button>
      </div>
    </header>
  )
}
