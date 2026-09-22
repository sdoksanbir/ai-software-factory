import { OpsIcon, type OpsIconName } from "./opsIcons"

export type ActivityItem = {
  id: string
  time: string
  actor: string
  message: string
  icon: OpsIconName
  kind: "task" | "agent" | "system"
}

type Props = {
  items: ActivityItem[]
  filter: "all" | "tasks" | "agents" | "system"
  onFilterChange: (value: "all" | "tasks" | "agents" | "system") => void
  onSeeAll: () => void
}

const FILTERS: Array<{
  key: Props["filter"]
  label: string
}> = [
  { key: "all", label: "Tümü" },
  { key: "tasks", label: "Görevler" },
  { key: "agents", label: "Ajanlar" },
  { key: "system", label: "Sistem" },
]

export function ActivityFeed({
  items,
  filter,
  onFilterChange,
  onSeeAll,
}: Props) {
  const visible =
    filter === "all"
      ? items
      : items.filter((item) => item.kind === filter)

  return (
    <section className="ops-activity" id="ops-activity">
      <div className="ops-activity-head">
        <div>
          <OpsIcon name="agents" />
          <strong>Canlı Aktivite</strong>
          <span className="ops-live-dot">
            <i />
            Canlı
          </span>
        </div>

        <button type="button" onClick={onSeeAll}>
          Tümünü Gör
          <b>→</b>
        </button>
      </div>

      <div className="ops-activity-filters" role="tablist" aria-label="Aktivite filtresi">
        {FILTERS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={filter === item.key}
            className={filter === item.key ? "active" : ""}
            onClick={() => onFilterChange(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="ops-activity-list">
        {visible.length === 0 ? (
          <div className="ops-feed-empty">
            Canlı aktiviteyi görmek için bir görev başlatın.
          </div>
        ) : (
          visible.map((item) => (
            <article className="ops-feed-card" key={item.id}>
              <time>{item.time}</time>
              <span className="ops-feed-icon">
                <OpsIcon name={item.icon} />
              </span>
              <div>
                <strong>{item.actor}</strong>
                <p>{item.message}</p>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  )
}
