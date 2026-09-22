import type { Task } from "../../api"

type Props = {
  tasks: Task[]
  selectedTaskId: string | null
  onSelectTask: (taskId: string) => void
  onSeeAll: () => void
}

const stateLabels: Record<string, string> = {
  queued: "Sırada",
  running: "Çalışıyor",
  ready_for_approval: "Onay Bekliyor",
  approved: "Tamamlandı",
  completed: "Tamamlandı",
  rejected: "Reddedildi",
  failed: "Başarısız",
}

export function RecentTasks({
  tasks,
  selectedTaskId,
  onSelectTask,
  onSeeAll,
}: Props) {
  const recent = tasks.slice(0, 5)

  return (
    <section className="ops-recent-tasks" aria-label="Son Görevler">
      <div className="ops-recent-head">
        <div>
          <span>ÖZET</span>
          <h2>Son Görevler</h2>
        </div>
        <button type="button" onClick={onSeeAll}>
          Tüm Görevler
          <b>→</b>
        </button>
      </div>

      {recent.length === 0 ? (
        <div className="ops-feed-empty">Henüz görev yok.</div>
      ) : (
        <div className="ops-recent-list">
          {recent.map((task) => (
            <button
              key={task.task_id}
              type="button"
              className={`ops-recent-card ${
                selectedTaskId === task.task_id ? "selected" : ""
              }`}
              onClick={() => onSelectTask(task.task_id)}
            >
              <div>
                <strong>{task.task_id}</strong>
                <em className={`state-${task.state}`}>
                  {stateLabels[task.state] ?? task.state}
                </em>
              </div>
              <p>{task.prompt}</p>
              <small>{task.model ?? "Otomatik model"}</small>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
