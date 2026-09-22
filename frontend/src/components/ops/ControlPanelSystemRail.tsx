import type { ControlCenterStatus } from "../../api"

import "./ControlPanelSystemRail.css"

type Props = {
  controlCenter: ControlCenterStatus | null
  availableModels: string[]
}

type CC = {
  system?: {
    platform?: string
    cpu?: { logical_count?: number | null; used_percent?: number | null }
    memory?: {
      total_bytes?: number | null
      available_bytes?: number | null
      used_percent?: number | null
    }
    disk?: { used_percent?: number | null }
    gpu?: {
      used_percent?: number | null
      vram_used_bytes?: number | null
      vram_total_bytes?: number | null
    }
  }
  services?: {
    ollama?: { online?: boolean; models?: Array<{ name?: string }> }
    docker?: { online?: boolean }
  }
  git?: { available?: boolean; branch?: string | null }
}

const pct = (value: number | null | undefined) =>
  Math.min(100, Math.max(0, Number(value ?? 0)))

const bytes = (value: number | null | undefined) => {
  if (value == null) return "—"
  if (value >= 1073741824) return `${(value / 1073741824).toFixed(1)} GB`
  return `${(value / 1048576).toFixed(0)} MB`
}

function Meter({
  label,
  value,
  percent,
  detail,
  tone,
}: {
  label: string
  value: string
  percent: number
  detail: string
  tone: "cyan" | "blue" | "violet" | "amber"
}) {
  return (
    <div className="control-system-resource">
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className={`control-system-meter ${tone}`}>
        <span style={{ width: `${pct(percent)}%` }} />
      </div>
      <small>{detail}</small>
    </div>
  )
}

function Service({
  name,
  detail,
  online,
}: {
  name: string
  detail: string
  online: boolean
}) {
  return (
    <div className="control-system-service">
      <i className={online ? "online" : "offline"} />
      <div>
        <strong>{name}</strong>
        <small>{detail}</small>
      </div>
      <span className={online ? "online" : "offline"}>
        {online ? "Çalışıyor" : "Kapalı"}
      </span>
    </div>
  )
}

export function ControlPanelSystemRail({
  controlCenter,
  availableModels,
}: Props) {
  const cc = controlCenter as unknown as CC | null

  const cpu = pct(cc?.system?.cpu?.used_percent)
  const memory = pct(cc?.system?.memory?.used_percent)
  const disk = pct(cc?.system?.disk?.used_percent)

  const total = cc?.system?.memory?.total_bytes
  const available = cc?.system?.memory?.available_bytes
  const used =
    total != null && available != null
      ? total - available
      : null

  const gpuRaw = cc?.system?.gpu?.used_percent
  const hasGpu = gpuRaw != null && Number.isFinite(Number(gpuRaw))
  const vramUsed = cc?.system?.gpu?.vram_used_bytes
  const vramTotal = cc?.system?.gpu?.vram_total_bytes

  const ollama = !!cc?.services?.ollama?.online
  const docker = !!cc?.services?.docker?.online
  const git = !!cc?.git?.available
  const api = controlCenter != null
  const allHealthy = ollama && docker && git && api

  return (
    <div className="control-panel-system-rail">
      <section className="control-system-card">
        <div className="control-system-title">
          <div>
            <span>SİSTEM</span>
            <strong>Sistem Kaynakları</strong>
          </div>
          <small>{cc?.system?.platform ?? "Yerel"}</small>
        </div>

        <Meter
          label="CPU"
          value={`${Math.round(cpu)}%`}
          percent={cpu}
          detail={`${cc?.system?.cpu?.logical_count ?? "—"} mantıksal çekirdek`}
          tone="cyan"
        />

        <Meter
          label="RAM"
          value={`${bytes(used)} / ${bytes(total)}`}
          percent={memory}
          detail={`${Math.round(memory)}% kullanımda`}
          tone="blue"
        />

        <Meter
          label="Disk"
          value={`${Math.round(disk)}%`}
          percent={disk}
          detail="Yerel çalışma alanı"
          tone="violet"
        />

        {hasGpu && (
          <Meter
            label="GPU"
            value={`${Math.round(pct(gpuRaw))}%`}
            percent={pct(gpuRaw)}
            detail={
              vramUsed != null && vramTotal != null
                ? `VRAM ${bytes(vramUsed)} / ${bytes(vramTotal)}`
                : "GPU kullanımı"
            }
            tone="amber"
          />
        )}
      </section>

      <section className="control-system-card">
        <div className="control-system-title">
          <div>
            <span>ALTYAPI</span>
            <strong>Servis Durumu</strong>
          </div>
          <small className={allHealthy ? "healthy" : "warning"}>
            {allHealthy ? "Tümü Sağlıklı" : "Kontrol Gerekli"}
          </small>
        </div>

        <div className="control-system-service-list">
          <Service
            name="Ollama"
            detail={`${cc?.services?.ollama?.models?.length ?? availableModels.length} model`}
            online={ollama}
          />
          <Service name="Docker Sandbox" detail="Test ortamı" online={docker} />
          <Service
            name="Git / Worktree"
            detail={cc?.git?.branch ?? "Repository"}
            online={git}
          />
          <Service name="SQLite" detail="Task state" online={api} />
          <Service name="Factory API" detail="Control Center" online={api} />
        </div>
      </section>
    </div>
  )
}
