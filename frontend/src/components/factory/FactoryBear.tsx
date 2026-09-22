import { useId } from "react"

type FactoryBearProps = {
  variant: number
  active?: boolean
  mood?: "idle" | "working" | "happy" | "sad" | "thinking" | "angry"
  /** away = masaya bakıyor (sırt kullanıcıya), toward = yüz kullanıcıya */
  facing?: "away" | "toward"
  /** Aktif masadaki çalışanın yanındaki hareketli evraklar */
  workPapers?: boolean
  /** Yuvarlak avatar: yüz ve karaktere yakın kırpma */
  portrait?: boolean
}

const accents = [
  "#ffb63f",
  "#38a9ff",
  "#9667ff",
  "#ff9e42",
  "#35dda2",
  "#38bfff",
]

const furPalettes = [
  ["#f4c27a", "#d7924c", "#a86432", "#6f3d1f"],
  ["#f0b872", "#c98a4a", "#9a5f30", "#6a381c"],
  ["#e8b07a", "#c07a48", "#8f5430", "#5f3018"],
  ["#f2be7e", "#d08e50", "#a66834", "#6d3c1e"],
  ["#efc08a", "#c99458", "#9a6738", "#68401f"],
  ["#f6c888", "#d99a52", "#ad6e38", "#73421f"],
]

function RoleAccessory({
  role,
  accent,
}: {
  role: number
  accent: string
}) {
  if (role === 0) {
    // Planlayıcı — sarı ampul şapka
    return (
      <g className="bear-accessory role-planner">
        <ellipse cx="95" cy="42" rx="38" ry="14" fill="#f0b429" />
        <path
          d="M60 44c6-26 24-40 35-40s29 14 35 40c-22-6-47-6-70 0z"
          fill="#ffd24a"
        />
        <path
          d="M95 8c-9 0-16 10-16 22h32c0-12-7-22-16-22z"
          fill="#ffe9a0"
        />
        <circle cx="95" cy="22" r="9" fill="#fff4c8" />
        <path
          d="M95 12v4M86 18l3 3M104 18l-3 3M88 28l2-2M102 28l-2-2"
          stroke="#ff9a1a"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <rect x="90" y="30" width="10" height="8" rx="2" fill="#c98518" />
      </g>
    )
  }

  if (role === 1) {
    // Analist — mavi gözlük + büyüteç rozeti
    return (
      <g className="bear-accessory role-analyst">
        <circle
          cx="72"
          cy="88"
          r="16"
          fill="rgba(40,110,180,.18)"
          stroke="#1e4f86"
          strokeWidth="5"
        />
        <circle
          cx="118"
          cy="88"
          r="16"
          fill="rgba(40,110,180,.18)"
          stroke="#1e4f86"
          strokeWidth="5"
        />
        <path
          d="M88 88h14"
          stroke="#1e4f86"
          strokeWidth="5"
          strokeLinecap="round"
        />
        <path
          d="M56 88c-8-2-14-1-18 4"
          stroke="#1e4f86"
          strokeWidth="4"
          strokeLinecap="round"
          fill="none"
        />
        <path
          d="M134 88c8-2 14-1 18 4"
          stroke="#1e4f86"
          strokeWidth="4"
          strokeLinecap="round"
          fill="none"
        />
        <g transform="translate(142 48)">
          <circle cx="0" cy="0" r="14" fill="#2f8fff" />
          <circle
            cx="0"
            cy="0"
            r="7"
            fill="none"
            stroke="#fff"
            strokeWidth="2.4"
          />
          <path
            d="M5 5l7 7"
            stroke="#fff"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
        </g>
      </g>
    )
  }

  if (role === 2) {
    // Kodlayıcı — mor kulaklık + kod rozeti
    return (
      <g className="bear-accessory role-coder">
        <path
          d="M46 78c2-34 20-52 49-52s47 18 49 52"
          fill="none"
          stroke={accent}
          strokeWidth="9"
          strokeLinecap="round"
        />
        <rect x="30" y="72" width="20" height="40" rx="10" fill={accent} />
        <rect x="140" y="72" width="20" height="40" rx="10" fill={accent} />
        <circle cx="40" cy="92" r="4" fill="#e4d7ff" />
        <circle cx="150" cy="92" r="4" fill="#e4d7ff" />
        <g transform="translate(142 48)">
          <circle cx="0" cy="0" r="14" fill="#7a4dff" />
          <text
            x="0"
            y="5"
            textAnchor="middle"
            fill="#fff"
            fontSize="11"
            fontWeight="900"
            fontFamily="Segoe UI, sans-serif"
          >
            {"</>"}
          </text>
        </g>
      </g>
    )
  }

  if (role === 3) {
    // İnceleyici — mavi kep + büyüteç
    return (
      <g className="bear-accessory role-reviewer">
        <path
          d="M48 62c10-26 34-36 55-33 22 3 38 16 44 38-34-8-66-9-99-5z"
          fill="#1b74d0"
        />
        <path
          d="M108 58c20 0 36 3 50 11-12 7-28 10-48 8z"
          fill="#4eb0ff"
        />
        <ellipse cx="78" cy="52" rx="18" ry="8" fill="#0f5aa8" opacity="0.45" />
        <g transform="translate(142 48)">
          <circle cx="0" cy="0" r="14" fill="#2f8fff" />
          <circle
            cx="-1"
            cy="-1"
            r="6"
            fill="none"
            stroke="#fff"
            strokeWidth="2.4"
          />
          <path
            d="M4 4l7 7"
            stroke="#fff"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
        </g>
      </g>
    )
  }

  if (role === 4) {
    // Doğrulayıcı — yeşil şapka + onay
    return (
      <g className="bear-accessory role-verifier">
        <path
          d="M48 62c10-26 34-36 55-33 22 3 38 16 44 38-34-8-66-9-99-5z"
          fill="#12a06e"
        />
        <path
          d="M108 58c20 0 36 3 50 11-12 7-28 10-48 8z"
          fill="#4ae0a8"
        />
        <g transform="translate(142 48)">
          <circle cx="0" cy="0" r="14" fill="#1ecf8a" />
          <path
            d="M-6 0l4 5 9-10"
            fill="none"
            stroke="#fff"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      </g>
    )
  }

  // Birleştirici — beyaz/turuncu baret + dişli
  return (
    <g className="bear-accessory role-deploy">
      <path
        d="M48 64c10-28 34-38 55-35 22 3 38 17 44 40-34-8-66-9-99-5z"
        fill="#f4f8ff"
      />
      <path
        d="M108 58c20 0 36 4 50 12-12 7-28 10-48 8z"
        fill="#ffb24a"
      />
      <ellipse cx="95" cy="48" rx="22" ry="10" fill="#dfe8f4" />
      <g transform="translate(142 48)">
        <circle cx="0" cy="0" r="14" fill="#ff9d2e" />
        <circle cx="0" cy="0" r="5" fill="none" stroke="#fff" strokeWidth="2.2" />
        <path
          d="M0-9v3M0 6v3M-9 0h3M6 0h3M-6.4-6.4l2.1 2.1M4.3 4.3l2.1 2.1M6.4-6.4l-2.1 2.1M-4.3 4.3l-2.1 2.1"
          stroke="#fff"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </g>
    </g>
  )
}

export function FactoryBear({
  variant,
  active = false,
  mood = "idle",
  facing = "toward",
  workPapers = false,
  portrait = false,
}: FactoryBearProps) {
  const uid = useId().replace(/:/g, "")
  const role = variant % 6
  const accent = accents[role]
  const fur = furPalettes[role]
  const resolvedMood =
    mood === "idle" && active ? "working" : mood
  const id = `svg-bear-${uid}`
  const isHappy = resolvedMood === "happy"
  const isSad = resolvedMood === "sad"
  const isThinking = resolvedMood === "thinking"
  const isAngry = resolvedMood === "angry"
  const isWorking = resolvedMood === "working"
  const faceAway = facing === "away" && !portrait

  if (faceAway) {
    return (
      <svg
        className={`factory-svg-bear mood-${resolvedMood} facing-away ${
          isWorking ? "is-working" : ""
        }`}
        viewBox="0 0 190 205"
        aria-hidden="true"
      >
        <defs>
          <radialGradient id={`${id}-fur`} cx="40%" cy="30%" r="78%">
            <stop offset="0%" stopColor={fur[0]} />
            <stop offset="55%" stopColor={fur[1]} />
            <stop offset="100%" stopColor={fur[3]} />
          </radialGradient>
          <linearGradient id={`${id}-shirt`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={accent} />
            <stop offset="100%" stopColor="#12304c" />
          </linearGradient>
          <filter
            id={`${id}-shadow`}
            x="-80%"
            y="-80%"
            width="260%"
            height="300%"
          >
            <feDropShadow
              dx="0"
              dy="9"
              stdDeviation="7"
              floodColor="#020713"
              floodOpacity="0.56"
            />
          </filter>
        </defs>

        <ellipse
          className="factory-bear-floor-shadow"
          cx="95"
          cy="192"
          rx="49"
          ry="8"
        />

        <g className="factory-bear-body" filter={`url(#${id}-shadow)`}>
          <circle cx="48" cy="52" r="24" fill={`url(#${id}-fur)`} />
          <circle cx="142" cy="52" r="24" fill={`url(#${id}-fur)`} />
          <circle cx="48" cy="52" r="11" fill={fur[2]} />
          <circle cx="142" cy="52" r="11" fill={fur[2]} />
          <ellipse
            cx="95"
            cy="158"
            rx="48"
            ry="42"
            fill={`url(#${id}-shirt)`}
          />
          <ellipse
            cx="95"
            cy="92"
            rx="58"
            ry="60"
            fill={`url(#${id}-fur)`}
          />
          <ellipse
            cx="95"
            cy="78"
            rx="34"
            ry="22"
            fill={fur[2]}
            opacity="0.28"
          />
          <RoleAccessory role={role} accent={accent} />
          <g className="factory-bear-arms">
            <ellipse cx="48" cy="156" rx="18" ry="16" fill={fur[1]} />
            <ellipse cx="142" cy="156" rx="18" ry="16" fill={fur[1]} />
          </g>
        </g>
      </svg>
    )
  }

  const viewBox = portrait ? "28 8 134 128" : "0 0 190 205"

  return (
    <svg
      className={`factory-svg-bear mood-${resolvedMood} facing-toward ${
        portrait ? "is-portrait" : ""
      } ${isWorking ? "is-working" : ""} ${isHappy ? "is-happy" : ""} ${
        isSad ? "is-sad" : ""
      } ${isThinking ? "is-thinking" : ""} ${isAngry ? "is-angry" : ""}`}
      viewBox={viewBox}
      aria-hidden="true"
    >
      <defs>
        <radialGradient id={`${id}-fur`} cx="32%" cy="24%" r="78%">
          <stop offset="0%" stopColor={fur[0]} />
          <stop offset="45%" stopColor={fur[1]} />
          <stop offset="78%" stopColor={fur[2]} />
          <stop offset="100%" stopColor={fur[3]} />
        </radialGradient>

        <radialGradient id={`${id}-muzzle`} cx="40%" cy="30%" r="75%">
          <stop offset="0%" stopColor="#fff0d4" />
          <stop offset="100%" stopColor="#dca87c" />
        </radialGradient>

        <linearGradient id={`${id}-shirt`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={accent} />
          <stop offset="100%" stopColor="#163458" />
        </linearGradient>

        <filter
          id={`${id}-shadow`}
          x="-80%"
          y="-80%"
          width="260%"
          height="300%"
        >
          <feDropShadow
            dx="0"
            dy="9"
            stdDeviation="7"
            floodColor="#020713"
            floodOpacity="0.56"
          />
        </filter>

        <filter
          id={`${id}-glow`}
          x="-100%"
          y="-100%"
          width="300%"
          height="300%"
        >
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {!portrait && (
        <ellipse
          className="factory-bear-floor-shadow"
          cx="95"
          cy="192"
          rx="49"
          ry="8"
        />
      )}

      <g className="factory-bear-body" filter={`url(#${id}-shadow)`}>
        <circle cx="48" cy="50" r="25" fill={`url(#${id}-fur)`} />
        <circle cx="142" cy="50" r="25" fill={`url(#${id}-fur)`} />
        <circle cx="48" cy="50" r="13" fill={fur[0]} />
        <circle cx="142" cy="50" r="13" fill={fur[0]} />

        {!portrait && (
          <ellipse
            cx="95"
            cy="157"
            rx="48"
            ry="43"
            fill={`url(#${id}-shirt)`}
          />
        )}

        <ellipse
          cx="95"
          cy="91"
          rx="60"
          ry="62"
          fill={`url(#${id}-fur)`}
        />

        {isSad ? (
          <>
            <path
              d="M64 78c8 5 16 5 22 0"
              stroke="#75452b"
              strokeWidth="3.2"
              strokeLinecap="round"
              opacity="0.7"
            />
            <path
              d="M106 78c8 5 16 5 22 0"
              stroke="#75452b"
              strokeWidth="3.2"
              strokeLinecap="round"
              opacity="0.7"
            />
          </>
        ) : isAngry ? (
          <>
            <path
              d="M62 72c10 6 18 8 26 4"
              stroke="#5a3018"
              strokeWidth="4"
              strokeLinecap="round"
            />
            <path
              d="M128 72c-10 6-18 8-26 4"
              stroke="#5a3018"
              strokeWidth="4"
              strokeLinecap="round"
            />
          </>
        ) : isThinking ? (
          <>
            <path
              d="M64 76c8-2 16-1 22 3"
              stroke="#75452b"
              strokeWidth="3"
              strokeLinecap="round"
              opacity="0.65"
            />
            <path
              d="M106 79c8-3 16-3 22 0"
              stroke="#75452b"
              strokeWidth="3"
              strokeLinecap="round"
              opacity="0.65"
            />
          </>
        ) : (
          <>
            <path
              d="M64 75c7-4 14-4 20 0"
              stroke="#75452b"
              strokeWidth="3"
              strokeLinecap="round"
              opacity="0.55"
            />
            <path
              d="M106 75c7-4 14-4 20 0"
              stroke="#75452b"
              strokeWidth="3"
              strokeLinecap="round"
              opacity="0.55"
            />
          </>
        )}

        {isHappy ? (
          <>
            <path
              d="M64 90c5-8 13-8 18 0"
              fill="none"
              stroke="#17110d"
              strokeWidth="4"
              strokeLinecap="round"
            />
            <path
              d="M108 90c5-8 13-8 18 0"
              fill="none"
              stroke="#17110d"
              strokeWidth="4"
              strokeLinecap="round"
            />
          </>
        ) : (
          <>
            <ellipse
              cx="73"
              cy="88"
              rx="7"
              ry={isSad ? 9 : 8}
              fill="#17110d"
            />
            <ellipse
              cx="117"
              cy="88"
              rx="7"
              ry={isSad ? 9 : 8}
              fill="#17110d"
            />
            <circle cx="70.5" cy="85" r="2.2" fill="#ffffff" />
            <circle cx="114.5" cy="85" r="2.2" fill="#ffffff" />
          </>
        )}

        <ellipse
          cx="95"
          cy="111"
          rx="29"
          ry="23"
          fill={`url(#${id}-muzzle)`}
        />
        <ellipse cx="95" cy="103" rx="8" ry="6" fill="#2c1c14" />

        {isSad ? (
          <path
            d="M84 124c6-8 16-8 22 0"
            fill="none"
            stroke="#65402b"
            strokeWidth="3.2"
            strokeLinecap="round"
          />
        ) : isAngry ? (
          <path
            d="M82 122c8-10 18-10 26 0"
            fill="none"
            stroke="#5a3018"
            strokeWidth="3.6"
            strokeLinecap="round"
          />
        ) : isHappy ? (
          <path
            d="M78 114c8 14 26 14 34 0"
            fill="#c45a4a"
            stroke="#65402b"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : isThinking ? (
          <path
            d="M86 118c5 2 13 2 18 0"
            fill="none"
            stroke="#65402b"
            strokeWidth="3"
            strokeLinecap="round"
          />
        ) : (
          <path
            d="M84 116c6 7 16 7 22 0"
            fill="none"
            stroke="#65402b"
            strokeWidth="3.2"
            strokeLinecap="round"
          />
        )}

        {isAngry && (
          <g className="bear-angry-marks">
            <path
              d="M52 70l8-10M58 72l10-6"
              stroke="#ff6b5a"
              strokeWidth="2.4"
              strokeLinecap="round"
              opacity="0.85"
            />
            <path
              d="M138 70l-8-10M132 72l-10-6"
              stroke="#ff6b5a"
              strokeWidth="2.4"
              strokeLinecap="round"
              opacity="0.85"
            />
          </g>
        )}

        {isSad && (
          <g className="bear-tears">
            <ellipse cx="64" cy="104" rx="4" ry="7" fill="#6ec8ff" opacity="0.9">
              <animate
                attributeName="cy"
                values="98;112;98"
                dur="1.2s"
                repeatCount="indefinite"
              />
            </ellipse>
            <ellipse cx="126" cy="106" rx="4" ry="7" fill="#6ec8ff" opacity="0.85">
              <animate
                attributeName="cy"
                values="100;116;100"
                dur="1.35s"
                repeatCount="indefinite"
              />
            </ellipse>
          </g>
        )}

        <RoleAccessory role={role} accent={accent} />

        {!portrait && (
          <g className="factory-bear-arms">
            <ellipse cx="51" cy="154" rx="19" ry="17" fill={fur[1]} />
            <ellipse cx="139" cy="154" rx="19" ry="17" fill={fur[1]} />
          </g>
        )}

        {workPapers && isWorking && !portrait && (
          <g className="bear-work-papers" aria-hidden="true">
            <g className="bear-paper-left">
              <rect
                x="8"
                y="118"
                width="36"
                height="46"
                rx="3"
                fill="#f5f8fc"
                stroke="#9eb6cc"
                strokeWidth="2"
                transform="rotate(-18 26 141)"
              />
              <path
                d="M14 130h18M14 138h14M14 146h16"
                stroke="#7d95ab"
                strokeWidth="2"
                strokeLinecap="round"
                transform="rotate(-18 26 141)"
              />
            </g>
            <g className="bear-paper-right">
              <rect
                x="146"
                y="116"
                width="38"
                height="48"
                rx="3"
                fill="#ffffff"
                stroke="#9eb6cc"
                strokeWidth="2"
                transform="rotate(16 165 140)"
              />
              <path
                d="M154 128h18M154 136h14M154 144h16"
                stroke="#7d95ab"
                strokeWidth="2"
                strokeLinecap="round"
                transform="rotate(16 165 140)"
              />
            </g>
          </g>
        )}

        {isHappy && !portrait && (
          <g className="bear-papers" filter={`url(#${id}-glow)`}>
            <rect
              x="68"
              y="128"
              width="42"
              height="52"
              rx="4"
              fill="#f4f7fb"
              stroke="#c5d4e4"
              strokeWidth="2"
              transform="rotate(-12 89 154)"
            />
            <rect
              x="84"
              y="124"
              width="44"
              height="54"
              rx="4"
              fill="#ffffff"
              stroke="#9eb6cc"
              strokeWidth="2"
              transform="rotate(8 106 151)"
            />
          </g>
        )}
      </g>
    </svg>
  )
}
