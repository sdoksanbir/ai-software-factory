type FactoryMachineProps = {
  variant: number
  active?: boolean
}

const accents = [
  "#ffb53e",
  "#38a8ff",
  "#976bff",
  "#ff9d3e",
  "#39dca2",
  "#36bfff",
]

export function FactoryMachine({
  variant,
  active = false,
}: FactoryMachineProps) {
  const role = variant % 6
  const accent = accents[role]
  const id = `factory-desk-${role}`

  return (
    <svg
      className={`factory-machine-svg ${
        active ? "is-active" : ""
      }`}
      viewBox="0 0 230 190"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id={`${id}-top`}
          x1="0"
          y1="0"
          x2="0"
          y2="1"
        >
          <stop offset="0%" stopColor="#4a6d8f" />
          <stop offset="45%" stopColor="#2a4560" />
          <stop offset="100%" stopColor="#152838" />
        </linearGradient>

        <linearGradient
          id={`${id}-apron`}
          x1="0"
          y1="0"
          x2="0"
          y2="1"
        >
          <stop offset="0%" stopColor="#1a3148" />
          <stop offset="55%" stopColor="#0e2134" />
          <stop offset="100%" stopColor="#081722" />
        </linearGradient>

        <linearGradient
          id={`${id}-leg`}
          x1="0"
          y1="0"
          x2="1"
          y2="0"
        >
          <stop offset="0%" stopColor="#24384d" />
          <stop offset="50%" stopColor="#152636" />
          <stop offset="100%" stopColor="#1e3348" />
        </linearGradient>

        <linearGradient
          id={`${id}-screen`}
          x1="0"
          y1="0"
          x2="0"
          y2="1"
        >
          <stop offset="0%" stopColor="#0a1a2c" />
          <stop offset="100%" stopColor="#050e18" />
        </linearGradient>

        <filter
          id={`${id}-glow`}
          x="-50%"
          y="-50%"
          width="200%"
          height="200%"
        >
          <feGaussianBlur stdDeviation="2.4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        <filter
          id={`${id}-shadow`}
          x="-40%"
          y="-20%"
          width="180%"
          height="160%"
        >
          <feDropShadow
            dx="0"
            dy="6"
            stdDeviation="5"
            floodColor="#000"
            floodOpacity="0.48"
          />
        </filter>
      </defs>

      {/* floor shadow */}
      <ellipse
        cx="115"
        cy="184"
        rx="88"
        ry="6"
        fill="#020712"
        opacity="0.55"
      />

      <g filter={`url(#${id}-shadow)`}>
        {/* left leg */}
        <path
          d="M34 98h28v72c0 4-3 7-7 7H41c-4 0-7-3-7-7V98z"
          fill={`url(#${id}-leg)`}
          stroke={accent}
          strokeWidth="1.4"
          strokeOpacity="0.45"
        />
        <rect
          x="30"
          y="170"
          width="36"
          height="8"
          rx="3"
          fill="#1a2d40"
          stroke={accent}
          strokeWidth="1.2"
          strokeOpacity="0.55"
        />

        {/* right leg */}
        <path
          d="M168 98h28v72c0 4-3 7-7 7h-14c-4 0-7-3-7-7V98z"
          fill={`url(#${id}-leg)`}
          stroke={accent}
          strokeWidth="1.4"
          strokeOpacity="0.45"
        />
        <rect
          x="164"
          y="170"
          width="36"
          height="8"
          rx="3"
          fill="#1a2d40"
          stroke={accent}
          strokeWidth="1.2"
          strokeOpacity="0.55"
        />

        {/* apron / under-desk panel */}
        <rect
          x="22"
          y="52"
          width="186"
          height="108"
          rx="14"
          fill={`url(#${id}-apron)`}
          stroke={accent}
          strokeWidth="2.2"
        />

        {/* inner screen well — face panel sits here */}
        <rect
          x="31"
          y="59"
          width="168"
          height="93"
          rx="12"
          fill={`url(#${id}-screen)`}
          stroke={accent}
          strokeOpacity="0.42"
          strokeWidth="1.4"
        />

        <rect
          x="36"
          y="64"
          width="158"
          height="83"
          rx="9"
          fill={accent}
          opacity="0.04"
        />

        {/* desk top surface (bear sits on this) */}
        <rect
          x="10"
          y="22"
          width="210"
          height="34"
          rx="10"
          fill={`url(#${id}-top)`}
          stroke={accent}
          strokeWidth="2.4"
          filter={`url(#${id}-glow)`}
        />

        {/* tabletop thickness edge */}
        <path
          d="M14 52h202"
          stroke={accent}
          strokeWidth="3.2"
          strokeLinecap="round"
          opacity="0.9"
          filter={`url(#${id}-glow)`}
        />

        <path
          d="M18 48h194"
          stroke="#9ec4e8"
          strokeWidth="1.2"
          opacity="0.18"
        />

        {/* subtle desktop grain lines */}
        <path
          d="M28 34h174"
          stroke="#d7ebff"
          strokeWidth="1"
          opacity="0.08"
        />
        <path
          d="M36 42h158"
          stroke="#d7ebff"
          strokeWidth="1"
          opacity="0.06"
        />

        {/* neon rim accents on desk corners */}
        <path
          d="M20 40V28c0-4 3-7 7-7h18"
          fill="none"
          stroke={accent}
          strokeWidth="2.6"
          opacity="0.75"
        />
        <path
          d="M210 40V28c0-4-3-7-7-7h-18"
          fill="none"
          stroke={accent}
          strokeWidth="2.6"
          opacity="0.75"
        />

        {/* status LEDs on desk front edge */}
        <circle
          cx="48"
          cy="55"
          r="2.8"
          fill={active ? "#5bffb2" : "#4b6074"}
        />
        <circle
          cx="59"
          cy="55"
          r="2.8"
          fill={active ? accent : "#4b6074"}
        />
        <circle
          cx="70"
          cy="55"
          r="2.8"
          fill="#4b6074"
        />

        {/* small drawer / cable tray hint under apron */}
        <rect
          x="88"
          y="148"
          width="54"
          height="7"
          rx="3"
          fill="#0c1c2c"
          stroke={accent}
          strokeWidth="1"
          strokeOpacity="0.35"
        />
      </g>
    </svg>
  )
}
