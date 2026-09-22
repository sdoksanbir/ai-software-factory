import {
  useEffect,
  useRef,
  useState,
} from "react"

import type {
  PipelineStation,
  PipelineStationState,
} from "../ops/FactoryPipeline"

import { OpsIcon } from "../ops/opsIcons"
import { FactoryBear } from "./FactoryBear"
import { FactoryMachine } from "./FactoryMachine"

import "./FactoryVisuals.css"
import "./TeddyFactoryPipeline.css"

type Props = {
  stations: PipelineStation[]
  hasAiResponse?: boolean
}

type RunnerMood =
  | "idle"
  | "thinking"
  | "angry"
  | "happy"
  | "sad"
  | "walking"

type RunnerSlot = {
  index: number
  mood: RunnerMood
  /** Sırada/işlemde arkası dönük; sonuçta yüz kullanıcıya */
  facing: "away" | "toward"
  sigh: boolean
  growl: boolean
}

function stateLabel(state: PipelineStationState) {
  const labels: Record<PipelineStationState, string> = {
    completed: "TAMAMLANDI",
    active: "ÇALIŞIYOR",
    waiting: "ONAY BEKLİYOR",
    failed: "HATA",
    pending: "SIRADA",
    skipped: "GEREKMİYOR",
  }

  return labels[state]
}

function stationSummary(lines: string[]) {
  const useful = lines
    .map((line) => {
      const value = line.trim()

      if (
        value === "not_required" ||
        value === "skipped"
      ) {
        return "Bu görevde gerekli değil"
      }

      return value
    })
    .filter(Boolean)
    .filter(
      (line) =>
        ![
          "Tamamlandı",
          "Çalışıyor",
          "Sırada",
          "Onay Bekliyor",
          "Hata",
        ].includes(line),
    )

  if (useful.length === 0) {
    return "Bekliyor"
  }

  return useful.slice(0, 2).join(" · ")
}

/** Altta yürüyen ayıcığın hedef masası ve ruh hali. */
function resolveRunnerSlot(
  stations: PipelineStation[],
): RunnerSlot | null {
  if (stations.length === 0) {
    return null
  }

  const failedIndex = stations.findIndex(
    (station) => station.state === "failed",
  )

  if (failedIndex >= 0) {
    return {
      index: failedIndex,
      mood: "sad",
      facing: "toward",
      sigh: false,
      growl: false,
    }
  }

  const allDone = stations.every(
    (station) => station.state === "completed",
  )

  if (allDone) {
    return {
      index: stations.length - 1,
      mood: "happy",
      facing: "toward",
      sigh: false,
      growl: false,
    }
  }

  const waitingIndex = stations.findIndex(
    (station) => station.state === "waiting",
  )

  if (waitingIndex >= 0) {
    return {
      index: waitingIndex,
      mood: "angry",
      facing: "toward",
      sigh: false,
      growl: true,
    }
  }

  const activeIndex = stations.findIndex(
    (station) => station.state === "active",
  )

  if (activeIndex >= 0) {
    return {
      index: activeIndex,
      mood: "idle",
      facing: "away",
      sigh: true,
      growl: false,
    }
  }

  const nextIndex = stations.findIndex(
    (station) => station.state !== "completed",
  )

  if (nextIndex >= 0) {
    return {
      index: nextIndex,
      mood: "idle",
      facing: "away",
      sigh: true,
      growl: false,
    }
  }

  return {
    index: stations.length - 1,
    mood: "happy",
    facing: "toward",
    sigh: false,
    growl: false,
  }
}

export function TeddyFactoryPipeline({
  stations,
  hasAiResponse = false,
}: Props) {
  const runner = resolveRunnerSlot(stations)
  const count = Math.max(stations.length, 1)
  const [walking, setWalking] = useState(false)
  const prevIndex = useRef<number | null>(null)

  useEffect(() => {
    if (runner == null) {
      return
    }

    if (
      prevIndex.current != null &&
      prevIndex.current !== runner.index
    ) {
      setWalking(true)
      const timer = window.setTimeout(() => {
        setWalking(false)
      }, 900)
      prevIndex.current = runner.index
      return () => window.clearTimeout(timer)
    }

    prevIndex.current = runner.index
  }, [runner?.index])

  const runnerMood: RunnerMood =
    walking &&
    runner?.mood !== "sad" &&
    runner?.mood !== "happy" &&
    runner?.mood !== "angry"
      ? "walking"
      : (runner?.mood ?? "idle")

  const runnerFacing =
    runnerMood === "happy" ||
    runnerMood === "sad" ||
    runnerMood === "angry"
      ? "toward"
      : (runner?.facing ?? "away")

  const showSigh =
    !runner?.growl &&
    ((runner?.sigh ?? false) ||
      runnerMood === "thinking" ||
      runnerMood === "idle" ||
      runnerMood === "walking")

  const showGrowl =
    (runner?.growl ?? false) || runnerMood === "angry"

  const runnerLeft =
    runner == null
      ? "8%"
      : `${((runner.index + 0.5) / count) * 100}%`

  const lastStationIndex = Math.max(stations.length - 1, 0)

  return (
    <section
      className={`teddy-factory-pipeline station-count-${stations.length}`}
      id="factory-home"
    >
      <header className="teddy-pipeline-head">
        <div>
          <span>AI SOFTWARE FACTORY</span>
          <strong>AI FACTORY PIPELINE</strong>
        </div>

        <small>
          {stations
            .map(
              (station) =>
                station.label,
            )
            .join(" → ")}
        </small>
      </header>

      <div className="ref-factory-stage teddy-factory-stage has-runner">
        <div className="ref-stage-background" />

        <div className="ref-conveyor">
          <div className="ref-conveyor-rail" />

          {stations.map((station, index) => (
            <div
              className={`teddy-flow-light teddy-flow-light-${index}`}
              key={`flow-${station.key}`}
            />
          ))}
        </div>

        <div className="ref-machine-row">
          {stations.map((station, index) => {
            const working = station.state === "active"
            const isLastDesk = index === lastStationIndex

            return (
              <article
                key={station.key}
                className={`ref-machine teddy-station state-${station.state}${
                  isLastDesk ? " is-last-desk" : ""
                }`}
                aria-label={`${station.label}: ${stateLabel(station.state)}`}
              >
                <div
                  className={`ref-worker desk-worker ${
                    working ? "is-busy" : ""
                  }`}
                >
                  <FactoryBear
                    variant={index}
                    active={working}
                    mood={working ? "working" : "idle"}
                    facing="toward"
                    workPapers={working}
                  />
                  {working && (
                    <>
                      <span className="desk-paper desk-paper-left" />
                      <span className="desk-paper desk-paper-left mid" />
                      <span className="desk-paper desk-paper-right" />
                      <span className="desk-paper desk-paper-right mid" />
                    </>
                  )}

                  {isLastDesk && hasAiResponse && (
                    <a
                      className="teddy-ai-response-beacon is-speech side-right"
                      href="#task-ai-response"
                      aria-label="AI yanıtını görüntüle"
                    >
                      <span className="teddy-ai-response-terminal">
                        <b>AI</b>
                        <i />
                      </span>

                      <span className="teddy-ai-response-copy">
                        <strong>AI YANITI HAZIR</strong>
                        <small>Görüntülemek için tıkla</small>
                      </span>
                    </a>
                  )}
                </div>

                <FactoryMachine
                  variant={index}
                  active={working}
                />

                <div className="ref-machine-face">
                  <div className="ref-machine-icon">
                    <OpsIcon name={station.icon} />
                  </div>

                  <strong>{station.label}</strong>

                  <span title={station.lines.join(" · ")}>
                    {stationSummary(station.lines)}
                  </span>

                  <em
                    className={`ref-machine-state state-${station.state}`}
                  >
                    {stateLabel(station.state)}
                  </em>
                </div>

                {working && (
                  <div
                    className="teddy-working-signal"
                    aria-hidden="true"
                  >
                    <i />
                    <i />
                    <i />
                  </div>
                )}
              </article>
            )
          })}
        </div>

        {runner && (
          <div
            className={`teddy-runner mood-${runnerMood} facing-${runnerFacing} ${
              walking ? "is-walking" : ""
            }`}
            style={{ left: runnerLeft }}
            aria-hidden="true"
          >
            {(runnerMood === "thinking" ||
              runnerMood === "idle" ||
              runnerMood === "walking") &&
              !showGrowl && (
              <div className="teddy-think-bubble">
                <span>…</span>
                <i />
                <i />
                <i />
              </div>
            )}

            {showGrowl && (
              <div className="teddy-growl">
                <strong>Rrrr!</strong>
              </div>
            )}

            {showSigh && (
              <div className="teddy-sigh">
                <em>uf…</em>
                <em>puf…</em>
              </div>
            )}

            <FactoryBear
              variant={0}
              active={runnerMood === "walking"}
              facing={runnerFacing}
              mood={
                runnerMood === "walking"
                  ? "working"
                  : runnerMood === "thinking"
                    ? "thinking"
                    : runnerMood === "angry"
                      ? "angry"
                      : runnerMood
              }
            />
          </div>
        )}
      </div>

</section>
  )
}
