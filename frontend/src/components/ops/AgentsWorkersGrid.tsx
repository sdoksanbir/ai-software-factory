import type {
  AgentExecution,
  ControlCenterStatus,
} from "../../api"
import { FactoryBear } from "../factory/FactoryBear"
import "../factory/FactoryVisuals.css"
import "./AgentsWorkersGrid.css"

type AgentItem = {
  name?: string
  provider?: string
  provider_status?: string
  capabilities?: string[]
}

type Props = {
  agentExecutions: AgentExecution[]
  agentItems: AgentItem[]
  controlCenter: ControlCenterStatus | null
  availableModels: string[]
  memoryActive?: number
}

type RoleDef = {
  key: string
  label: string
  variant: number
  match: string[]
  defaultCaps: string[]
  workingAction: string
}

const ROLES: RoleDef[] = [
  {
    key: "planner",
    label: "Planlayıcı",
    variant: 0,
    match: ["plan"],
    defaultCaps: ["planlama", "strateji", "analiz"],
    workingAction: "Görev planı oluşturuyor",
  },
  {
    key: "analyst",
    label: "Analist",
    variant: 1,
    match: ["analy", "read"],
    defaultCaps: ["analiz", "keşif", "bağlam"],
    workingAction: "Kod tabanını inceliyor",
  },
  {
    key: "coder",
    label: "Kodlayıcı",
    variant: 2,
    match: ["cod", "write", "writer"],
    defaultCaps: ["yazma", "refactor", "patch"],
    workingAction: "Kod değişiklikleri yazıyor",
  },
  {
    key: "reviewer",
    label: "İnceleyici",
    variant: 3,
    match: ["review"],
    defaultCaps: ["inceleme", "kalite", "risk"],
    workingAction: "Değişiklikleri inceliyor",
  },
  {
    key: "verifier",
    label: "Doğrulayıcı",
    variant: 4,
    match: ["verif", "test"],
    defaultCaps: ["doğrulama", "test", "kontrol"],
    workingAction: "Sonuçları doğruluyor",
  },
  {
    key: "deploy",
    label: "Birleştirici",
    variant: 5,
    match: ["deploy", "merge", "lead", "birleş", "approv"],
    defaultCaps: ["birleştirme", "yayın", "entegrasyon"],
    workingAction: "Sonuçları birleştiriyor",
  },
]

type BearMood =
  | "idle"
  | "working"
  | "happy"
  | "sad"
  | "thinking"
  | "angry"

function matchRole(name: string, role: RoleDef) {
  const lower = name.toLowerCase()
  return role.match.some((token) => lower.includes(token))
}

function relativeTime(value: string | null | undefined) {
  if (!value) return "—"
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return "—"
  const mins = Math.max(0, Math.round((Date.now() - time) / 60000))
  if (mins < 1) return "şimdi"
  if (mins < 60) return `${mins} dk önce`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} saat önce`
  return `${Math.floor(hours / 24)} gün önce`
}

function resolveExecution(
  role: RoleDef,
  executions: AgentExecution[],
) {
  const matched = executions.filter((item) =>
    matchRole(item.agent_name, role),
  )
  if (matched.length === 0) return null
  return (
    matched.find((item) => item.status === "running") ??
    matched.slice().reverse()[0]
  )
}

function resolveVisual(
  execution: AgentExecution | null,
): {
  mood: BearMood
  facing: "away" | "toward"
  workPapers: boolean
  statusLabel: string
  statusTone: string
  sigh: boolean
} {
  if (!execution) {
    return {
      mood: "idle",
      facing: "away",
      workPapers: false,
      statusLabel: "Bekliyor",
      statusTone: "waiting",
      sigh: true,
    }
  }

  if (execution.status === "running") {
    return {
      mood: "working",
      facing: "toward",
      workPapers: true,
      statusLabel: "Çalışıyor",
      statusTone: "running",
      sigh: false,
    }
  }

  if (execution.status === "failed") {
    return {
      mood: "sad",
      facing: "toward",
      workPapers: false,
      statusLabel: "Hata",
      statusTone: "failed",
      sigh: false,
    }
  }

  return {
    mood: "happy",
    facing: "toward",
    workPapers: false,
    statusLabel: "Tamamlandı",
    statusTone: "completed",
    sigh: false,
  }
}

function formatMemory(value: number) {
  return new Intl.NumberFormat("tr-TR").format(value)
}

export function AgentsWorkersGrid({
  agentExecutions,
  agentItems,
  controlCenter,
  availableModels,
  memoryActive = 0,
}: Props) {
  const cards = ROLES.map((role) => {
    const execution = resolveExecution(role, agentExecutions)
    const catalog = agentItems.find((item) =>
      matchRole(item.name ?? "", role),
    )
    const visual = resolveVisual(execution)
    const busy = visual.mood === "working"

    const actionText =
      execution?.status === "running"
        ? role.workingAction
        : execution?.status === "completed"
          ? `${execution.provider_name} tamamlandı`
          : execution?.status === "failed"
            ? execution.error ?? "Çalışma başarısız"
            : catalog?.provider_status
              ? `Durum: ${catalog.provider_status}`
              : "Sırada bekliyor"

    return {
      role,
      execution,
      catalog,
      visual,
      busy,
      actionText,
    }
  })

  const activeCount = cards.filter(
    (card) => card.visual.statusTone === "running",
  ).length
  const readyModels = availableModels.length
  const servicesOnline =
    (controlCenter?.services.ollama.online ? 1 : 0) +
    (controlCenter?.services.docker.online ? 1 : 0)
  const systemHealthy =
    controlCenter?.services.ollama.online &&
    (controlCenter.services.docker.online ||
      !controlCenter.services.docker.installed)

  return (
    <div className="agents-workers">
      <div className="agents-kpi-row">
        <article className="agents-kpi tone-orange">
          <div>
            <span>Aktif Ajan</span>
            <strong>{activeCount || cards.filter((c) => c.execution).length || agentItems.length || 0}</strong>
            <small>
              {ROLES.length} ajanın {activeCount} tanesi
              aktif
            </small>
          </div>
          <em>◎</em>
        </article>

        <article className="agents-kpi tone-purple">
          <div>
            <span>Çalışan Modeller</span>
            <strong>{readyModels}</strong>
            <small>
              {readyModels} model hazır
            </small>
          </div>
          <em>◈</em>
        </article>

        <article className="agents-kpi tone-blue">
          <div>
            <span>Hafıza Kayıtları</span>
            <strong>{formatMemory(memoryActive)}</strong>
            <small>aktif proje hafızası</small>
          </div>
          <em>▣</em>
        </article>

        <article className="agents-kpi tone-green">
          <div>
            <span>Sistem Sağlığı</span>
            <strong>
              {systemHealthy ? "Sağlıklı" : "Dikkat"}
            </strong>
            <small>
              {servicesOnline}/2 servis ayakta
            </small>
          </div>
          <em>♡</em>
        </article>
      </div>

      <div className="agents-section-head">
        <div>
          <h3>Aktif Ajanlar</h3>
          <p>
            Gerçek yürütme durumuna göre çalışan
            fabrika ajanları
          </p>
        </div>
        <span>{cards.length} ajan</span>
      </div>

      <div className="agents-workers-grid">
        {cards.map(
          ({
            role,
            execution,
            catalog,
            visual,
            busy,
            actionText,
          }) => (
            <article
              key={role.key}
              className={`agents-worker-card tone-${role.variant} state-${visual.statusTone}`}
            >
              <header className="agents-worker-top">
                <div
                  className={`agents-avatar ${
                    busy ? "is-busy" : ""
                  } ${
                    visual.statusTone === "waiting"
                      ? "is-waiting"
                      : ""
                  }`}
                >
                  <FactoryBear
                    variant={role.variant}
                    active={busy}
                    mood={
                      visual.statusTone === "waiting"
                        ? "thinking"
                        : visual.mood
                    }
                    facing="toward"
                    workPapers={false}
                    portrait
                  />
                  {visual.sigh && (
                    <div className="agents-avatar-sigh">
                      uf…
                    </div>
                  )}
                </div>

                <div className="agents-worker-title">
                  <strong>{role.label}</strong>
                  <em
                    className={`agents-status tone-${visual.statusTone}`}
                  >
                    <i />
                    {visual.statusLabel}
                  </em>
                </div>
              </header>

              <dl className="agents-worker-facts">
                <div>
                  <dt>Model</dt>
                  <dd>
                    {execution?.model_name ??
                      catalog?.provider ??
                      "—"}
                  </dd>
                </div>
                <div>
                  <dt>Süre</dt>
                  <dd>
                    {execution
                      ? relativeTime(execution.started_at)
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Son İşlem</dt>
                  <dd>{actionText}</dd>
                </div>
              </dl>

              <div className="agents-worker-tags">
                {(
                  execution?.capabilities?.length
                    ? execution.capabilities
                    : catalog?.capabilities?.length
                      ? catalog.capabilities
                      : role.defaultCaps
                )
                  .slice(0, 3)
                  .map((cap) => (
                    <span key={cap}>{cap}</span>
                  ))}
              </div>

              <footer className="agents-worker-foot">
                <button type="button">
                  Detayları Gör
                  <span>→</span>
                </button>
                <button
                  type="button"
                  className="agents-more"
                  aria-label="Diğer"
                >
                  ⋯
                </button>
              </footer>
            </article>
          ),
        )}
      </div>
    </div>
  )
}
