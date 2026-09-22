import { OpsIcon, type OpsIconName } from "./opsIcons"

type KpiItem = {
  key: string
  label: string
  value: string | number
  detail: string
  icon: OpsIconName
  tone: "cyan" | "blue" | "amber" | "violet"
}

type Props = {
  activeTasks: number
  queuedTasks: number
  approvalTasks: number
  activeAgents: number
  totalAgents: number
}

export function OperationsKpi({
  activeTasks,
  queuedTasks,
  approvalTasks,
  activeAgents,
  totalAgents,
}: Props) {
  const items: KpiItem[] = [
    {
      key: "active",
      label: "Aktif Görevler",
      value: activeTasks,
      detail: "Çalışan + sırada",
      icon: "running",
      tone: "cyan",
    },
    {
      key: "queued",
      label: "Sıradaki Görevler",
      value: queuedTasks,
      detail: "Kuyrukta bekleyen",
      icon: "queue",
      tone: "blue",
    },
    {
      key: "approval",
      label: "Onay Bekleyen",
      value: approvalTasks,
      detail: "İnsan onayı",
      icon: "approval",
      tone: "amber",
    },
    {
      key: "agents",
      label: "Aktif Ajanlar",
      value: `${activeAgents}/${totalAgents || 0}`,
      detail: "Yürütme / toplam",
      icon: "agents",
      tone: "violet",
    },
  ]

  return (
    <section className="ops-kpi-grid" aria-label="Operasyon KPI">
      {items.map((item) => (
        <article
          key={item.key}
          className={`ops-kpi-card tone-${item.tone}`}
        >
          <div className="ops-kpi-icon">
            <OpsIcon name={item.icon} />
          </div>
          <div className="ops-kpi-copy">
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <small>{item.detail}</small>
          </div>
        </article>
      ))}
    </section>
  )
}
