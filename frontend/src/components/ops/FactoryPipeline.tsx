import { FactoryBear } from "../factory/FactoryBear"
import { FactoryMachine } from "../factory/FactoryMachine"
import { OpsIcon, type OpsIconName } from "./opsIcons"

export type PipelineStationState =
  | "completed"
  | "active"
  | "pending"
  | "skipped"
  | "failed"
  | "waiting"

export type PipelineStation = {
  key: string
  label: string
  lines: string[]
  state: PipelineStationState
  accent: string
  icon: OpsIconName
}

type Props = {
  stations: PipelineStation[]
}

function stateLabel(state: PipelineStationState) {
  if (state === "completed") return "TAMAMLANDI"
  if (state === "active") return "ÇALIŞIYOR"
  if (state === "waiting") return "ONAY BEKLİYOR"
  if (state === "failed") return "HATA"
  if (state === "skipped") return "GEREKMİYOR"
  return "SIRADA"
}

export function FactoryPipeline({ stations }: Props) {
  return (
    <section
      className="ops-factory-stage ref-factory-stage"
      aria-label="AI Factory Pipeline"
    >
      <div className="ops-stage-heading ref-stage-heading">
        <strong>AI FACTORY PIPELINE</strong>
        <span>
          Planlayıcı → Analist → Kodlayıcı → İnceleyici → Doğrulayıcı → Onay
        </span>
      </div>

      <div className="ops-conveyor ref-conveyor">
        <div className="ops-conveyor-rail ref-conveyor-rail" />
        <div className="ops-packet-track ref-packet-track" aria-hidden="true">
          {Array.from({ length: 10 }).map((_, index) => (
            <span
              key={index}
              className={`ops-data-packet ref-data-packet packet-${index % 6}`}
              style={{ animationDelay: `${index * -0.65}s` }}
            />
          ))}
        </div>

        <div className="ops-machine-row ref-machine-row">
          {stations.map((stage, index) => (
            <article
              key={stage.key}
              className={`ops-machine ref-machine ref-machine-${stage.accent} state-${stage.state}`}
            >
              <FactoryMachine
                variant={index}
                active={stage.state === "active"}
              />

              <div className="ops-worker ref-worker">
                <FactoryBear
                  variant={index}
                  active={stage.state === "active"}
                />
              </div>

              <div className="ops-machine-face ref-machine-face">
                <div className="ops-machine-icon ref-machine-icon">
                  <OpsIcon name={stage.icon} />
                </div>
                <strong>{stage.label}</strong>
                {stage.lines.length === 0 ? (
                  <span>Bekliyor</span>
                ) : (
                  stage.lines.map((line) => (
                    <span key={`${stage.key}-${line}`}>{line}</span>
                  ))
                )}
                <div
                  className={`ops-machine-state ref-machine-state state-${stage.state}`}
                >
                  {stateLabel(stage.state)}
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
