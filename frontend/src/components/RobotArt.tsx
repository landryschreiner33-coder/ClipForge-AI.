/** Original pixel artwork for the studio. Activity and motion are supplied by the shared status view. */
export type RobotKind = "finder" | "editor" | "checker" | "scheduler";
export type RobotState = "working" | "waiting" | "paused" | "attention" | "completed" | "disconnected" | "stopped";

type ArtProps = { kind: RobotKind; state?: RobotState; className?: string };

const ink = "#0B1421";
const shadow = "#283A50";
const ivory = "#F4EBD7";
const shade = "#CBBDA6";
const paper = "#FFF6E3";
const accents: Record<RobotKind, string> = {
  finder: "#75CDD2", editor: "#F5B94C", checker: "#A7C69D", scheduler: "#B8A5DB",
};

function Tool({ kind }: { kind: RobotKind }) {
  const accent = accents[kind];
  if (kind === "finder") return <g className="robot-tool">
    <path fill={shadow} d="M68 36h12v4h4v12h-4v4h-12v-4h-4V40h4z" />
    <path fill={accent} d="M70 38h8v4h4v8h-4v4h-8v-4h-4v-8h4z" />
    <path fill="#173D4A" d="M70 42h8v8h-8z" />
    <path fill={paper} d="M70 42h4v2h-2v4h-2z" />
    <path fill={shade} d="M66 54h4v4h-4zM62 58h4v8h-4z" />
    <path fill={ivory} d="M62 56h4v6h-4z" />
  </g>;
  if (kind === "editor") return <g className="robot-tool">
    <path fill={ink} d="M24 64h48v14H24z" />
    <path fill={shade} d="M26 64h44v10H26z" />
    <path fill={paper} d="M28 66h4v2h-4zm6 0h4v2h-4zm6 0h4v2h-4zm6 0h4v2h-4zm6 0h4v2h-4z" />
    <path fill={paper} d="M30 70h4v2h-4zm6 0h4v2h-4zm6 0h14v2H42z" />
    <path fill={accent} d="M60 66h6v6h-6z" />
  </g>;
  if (kind === "checker") return <g className="robot-tool">
    <path fill={shadow} d="M62 42h22v32H62z" />
    <path fill={accent} d="M62 40h20v30H62z" />
    <path fill={paper} d="M66 46h12v20H66z" />
    <path fill={shade} d="M68 38h8v6h-8z" />
    <path fill="#496346" d="M66 50h2v2h2v-4h2v6h-4v-2h-2zm0 10h2v2h2v-4h2v6h-4v-2h-2z" />
    <path fill={shade} d="M74 50h4v2h-4zm0 10h4v2h-4z" />
  </g>;
  return <g className="robot-tool">
    <path fill={shadow} d="M62 42h24v30H62z" />
    <path fill={paper} d="M62 42h22v26H62z" />
    <path fill={accent} d="M62 42h22v8H62z" />
    <path fill={shadow} d="M66 38h2v8h-2zm12 0h2v8h-2z" />
    <path fill={shade} d="M66 54h4v4h-4zm6 0h4v4h-4zm6 0h2v4h-2zM66 60h4v4h-4zm6 0h4v4h-4z" />
    <path fill={accent} d="M78 60h2v4h-2z" />
    <path fill={paper} d="M72 54h4v4h-4z" />
  </g>;
}

export function RobotArt({ kind, state = "waiting", className = "" }: ArtProps) {
  const accent = accents[kind];
  const resting = state === "paused" || state === "stopped" || state === "disconnected";
  return <svg viewBox="0 0 96 96" aria-hidden="true" focusable="false" shapeRendering="crispEdges"
    className={`robot-art robot-${kind} is-${state} ${className}`}>
    <path fill={ink} opacity=".55" d="M26 88h44v2h10v4H16v-4h10z" />
    <g className="robot-body">
      <path fill={shadow} d="M44 6h8v10h-8z" />
      <path fill={accent} d="M42 2h12v6H42z" />
      <path fill={paper} d="M44 2h6v2h-6z" />
      <path fill={shadow} d="M24 14h48v4h4v30h-4v4H24v-4h-4V18h4z" />
      <path fill={ivory} d="M26 12h44v4h4v28h-4v4H26v-4h-4V16h4z" />
      <path fill={paper} d="M28 14h40v4H28zM24 18h4v22h-4z" />
      <path fill={shade} d="M68 18h4v24h-4zM28 44h40v4H28z" />
      <path fill={shade} d="M16 24h6v14h-6zm58 0h6v14h-6z" />
      <path fill={accent} d="M16 28h4v6h-4zm60 0h4v6h-4z" />
      <path fill={shadow} d="M28 22h40v20H28z" />
      <path fill={ink} d="M30 24h36v16H30z" />
      <g className="robot-eyes" fill={accent}>
        {resting ? <path d="M34 32h8v2h-8zm20 0h8v2h-8z" /> : state === "completed" ?
          <path d="M34 30h2v-2h4v2h2v2h-2v-2h-4v2h-2zm20 0h2v-2h4v2h2v2h-2v-2h-4v2h-2z" /> :
          <path d="M34 28h6v8h-6zm20 0h6v8h-6z" />}
        {state === "attention" && <path fill={ivory} d="M34 24h6v2h-6zm20 0h6v2h-6z" />}
      </g>
      <path fill={accent} opacity=".55" d="M46 36h4v2h-4z" />
      <path fill={shadow} d="M38 48h20v8H38z" />
      <path fill={shade} d="M40 48h16v4H40z" />
      <path fill={shadow} d="M30 54h36v26H30z" />
      <path fill={ivory} d="M30 52h34v24H30z" />
      <path fill={paper} d="M32 54h4v18h-4z" />
      <path fill={shade} d="M58 56h6v20h-6zM34 72h24v4H34z" />
      <path fill={accent} d="M40 56h12v8H40z" />
      <path fill={paper} d="M42 58h4v2h-4z" />
      <path fill={shadow} d="M40 68h4v2h-4zm6 0h4v2h-4zm6 0h4v2h-4z" />
      <path fill={shade} d="M32 76h12v8H32zm20 0h10v8H52z" />
      <path fill={shadow} d="M28 82h16v8H28zm24 0h16v8H52z" />
      <path fill={ivory} d="M28 82h14v4H28zm24 0h14v4H52z" />
      <g className="robot-arm robot-arm-left">
        <path fill={shadow} d="M24 54h6v16h-6zM20 68h10v8H20z" />
        <path fill={ivory} d="M22 54h6v14h-6zM20 66h8v6h-8z" />
        <path fill={shade} d="M22 56h2v10h-2z" />
      </g>
      <g className="robot-arm robot-arm-right">
        <path fill={shadow} d="M64 54h6v10h-6zM62 62h10v8H62z" />
        <path fill={ivory} d="M62 54h6v10h-6zM60 62h10v6H60z" />
      </g>
      <Tool kind={kind} />
    </g>
  </svg>;
}

export function Desk({ kind, state = "waiting", className = "" }: ArtProps) {
  const accent = accents[kind];
  return <svg viewBox="0 0 160 68" aria-hidden="true" focusable="false" shapeRendering="crispEdges"
    className={`robot-desk desk-${kind} is-${state} ${className}`}>
    <path fill={ink} opacity=".5" d="M6 60h148v4H6z" />
    <path fill={shadow} d="M14 42h8v20h-8zm124 0h8v20h-8z" />
    <path fill="#866A48" d="M12 40h8v20h-8zm128 0h8v20h-8z" />
    <path fill="#594738" d="M20 46h120v6H20z" />
    <path fill="#B58E5B" d="M4 34h152v8H4z" />
    <path fill="#DFC095" d="M4 32h152v4H4z" />
    <g className="desk-screen">
      <path fill={shadow} d="M26 2h58v26H26zM48 28h14v4H48z" />
      <path fill={shade} d="M24 0h58v26H24z" />
      <path fill={ink} d="M28 4h50v18H28z" />
      {kind === "editor" ? <>
        <path fill={accent} d="M32 8h12v4H32zm16 0h20v4H48zM32 16h34v2H32z" />
        <path fill={paper} d="M48 6h2v14h-2z" />
      </> : kind === "scheduler" ? <>
        <path fill={accent} d="M32 6h40v4H32zM34 14h6v4h-6zm12 0h6v4h-6zm12 0h6v4h-6z" />
      </> : kind === "checker" ? <>
        <path fill={accent} d="M32 10h2v4h4v-8h2v10h-6v-2h-2zM46 8h26v2H46zm0 6h18v2H46z" />
      </> : <>
        <path fill={accent} d="M32 8h26v2H32zm0 6h18v2H32zM66 8h6v8h-6z" />
        <path fill={ivory} d="M58 16h8v2h-8z" />
      </>}
    </g>
    <path fill={shade} d="M34 30h46v2H34z" />
    <path fill={ink} d="M38 30h4v2h-4zm8 0h4v2h-4zm8 0h4v2h-4zm8 0h4v2h-4z" />
    <g className="desk-cards">
      <path fill={shadow} d="M104 24h30v8h-30z" />
      <path fill={shade} d="M102 22h30v6h-30z" />
      <path fill={ivory} d="M100 18h30v6h-30z" />
      <path fill={accent} d="M102 18h6v6h-6z" />
      <path fill={shade} d="M112 20h14v2h-14z" />
    </g>
    <path fill={shadow} d="M142 18h8v12h-8zM150 20h4v8h-4z" />
    <path fill={ivory} d="M140 18h8v12h-8zM148 20h4v6h-4z" />
    <path fill={accent} d="M140 18h8v2h-8z" />
  </svg>;
}

export function OfficeBackdrop({ className = "" }: { className?: string }) {
  return <svg viewBox="0 0 640 144" aria-hidden="true" focusable="false" shapeRendering="crispEdges"
    preserveAspectRatio="xMidYMid slice" className={`office-backdrop ${className}`}>
    <path fill="#101D2E" d="M0 0h640v144H0z" />
    <path fill="#192B40" d="M0 110h640v34H0z" />
    <path fill="#304055" d="M0 106h640v4H0z" />
    <path fill="#22364B" d="M0 128h640v2H0zM80 112h2v16h-2zm160 0h2v16h-2zm160 0h2v16h-2zm160 0h2v16h-2z" />
    <path fill="#22364B" d="M0 142h640v2H0zM0 130h2v12H0zm160 0h2v12h-2zm160 0h2v12h-2zm160 0h2v12h-2z" />
    <g className="office-window">
      <path fill={ink} d="M272 12h96v64h-96z" />
      <path fill="#34465D" d="M268 8h96v64h-96z" />
      <path fill="#192D42" d="M272 12h88v56h-88z" />
      <path fill="#2A4058" d="M276 16h80v48h-80z" />
      <path fill="#39536C" d="M276 44h8v20h-8zm12-12h12v32h-12zm16 8h16v24h-16zm24-16h8v40h-8zm12 14h16v26h-16z" />
      <path fill="#9C986E" d="M292 40h2v4h-2zm16 8h2v4h-2zm24-16h2v4h-2zm12 16h2v4h-2z" />
      <path fill="#526277" d="M314 12h4v56h-4zM272 38h88v4h-88z" />
      <path fill="#647082" d="M264 70h104v4H264z" />
    </g>
    <g className="office-shelf">
      <path fill="#725C45" d="M42 44h128v6H42z" />
      <path fill="#BD9563" d="M40 42h128v4H40z" />
      <path fill="#557D88" d="M50 20h10v22H50z" />
      <path fill="#BBA06D" d="M64 16h8v26h-8z" />
      <path fill="#859A77" d="M76 22h12v20H76z" />
      <path fill="#877BA9" d="M94 18h8v24h-8z" />
      <path fill={ivory} opacity=".6" d="M52 24h6v2h-6zm14-4h4v2h-4zm12 6h8v2h-8zm18-4h4v2h-4z" />
      <path fill="#3C4D60" d="M122 30h30v12h-30z" />
      <path fill={shade} d="M126 26h24v12h-24z" />
      <path fill="#977F61" d="M128 28h20v2h-20zm0 6h20v2h-20z" />
    </g>
    <g className="office-plant">
      <path fill={ink} d="M558 106h44v4h-44z" />
      <path fill="#9C7858" d="M564 82h30v6h-30zm4 6h22v18h-22z" />
      <path fill="#C69B6E" d="M564 82h28v4h-28zm4 6h4v14h-4z" />
      <path fill="#728E74" d="M578 54h4v28h-4zM564 58h8v4h8v8h-8v-4h-8zM580 46h8v-4h8v8h-8v8h-8z" />
      <path fill="#A7C69D" d="M560 52h10v4h6v6h-6v-4h-10zM582 42h8v-4h10v8h-10v6h-8z" />
      <path fill="#94B395" d="M578 30h6v4h4v10h-4v12h-6V44h-4V34h4z" />
    </g>
    <g className="office-wall-art">
      <path fill="#3B4B5D" d="M442 18h56v40h-56z" />
      <path fill={shade} d="M440 16h56v40h-56z" />
      <path fill="#1F3347" d="M444 20h48v32h-48z" />
      <path fill="#E3B16C" d="M474 26h8v8h-8z" />
      <path fill="#698C89" d="M450 44h6v-6h6v-6h6v8h6v6h12v2h-36z" />
    </g>
  </svg>;
}
