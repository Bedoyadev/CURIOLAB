import { Composition, Still } from "remotion";
import { AnimShort, AnimThumb, animDuration } from "./AnimShort";
import type { AnimProps } from "./types";

const sample: AnimProps = {
  brand: { ink: "#15161C", paper: "#FFFFFF", accent: "#FFD23F", accent2: "#18B7A6" },
  channel: "CANAL", slogan: "Preguntas raras, respuestas de verdad.", closingLine: "", subscribe: "SUSCRÍBETE",
  title: "¿Qué pasaría si…?",
  scenes: [], words: [], speakers: {},
  audio: "audio/narration.wav", music: null, shots: [],
  durationSeconds: 4, tailSeconds: 3,
  thumb: { src: "", at: 0 },
};

export const Root: React.FC = () => (
  <>
    <Composition id="AnimShort" component={AnimShort} width={1080} height={1920} fps={30} durationInFrames={210}
      defaultProps={sample}
      calculateMetadata={({ props }) => ({ durationInFrames: Math.ceil(animDuration(props) * 30) })} />
    <Composition id="AnimOverlay" component={AnimShort} width={1080} height={1920} fps={30} durationInFrames={210}
      defaultProps={sample}
      calculateMetadata={({ props }) => ({ durationInFrames: Math.ceil(animDuration(props) * 30), props: { ...props, overlayOnly: true } })} />
    <Still id="AnimThumb" component={AnimThumb} width={1080} height={1920} defaultProps={sample} />
  </>
);
