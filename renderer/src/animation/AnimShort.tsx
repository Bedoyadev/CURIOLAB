import { useEffect, useState } from "react";
import { AbsoluteFill, Audio, Loop, OffthreadVideo, Sequence, continueRender, delayRender, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT_BODY, FONT_TITLE, SAFE, fontsReady } from "./brand";
import type { AnimProps, AnimWord, Brand } from "./types";

const TITLE_SECONDS = 2.8;
// Frames a scene takes to settle after a cut: a small push instead of a hard jump.
const SETTLE = 8;
const PAGE_CHARS = 34;
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export const animDuration = (p: AnimProps) => p.durationSeconds + p.tailSeconds;

type Page = { words: AnimWord[]; start: number; end: number };

// A page of captions never mixes two lines (so never two speakers) and closes on a full stop.
export const paginate = (words: AnimWord[]): Page[] => {
  const pages: Page[] = [];
  let current: AnimWord[] = [];
  let chars = 0;
  const flush = () => {
    if (current.length) pages.push({ words: current, start: current[0].start, end: current[current.length - 1].end });
    current = [];
    chars = 0;
  };
  for (const w of words) {
    if (current.length > 0 && (current[0].line !== w.line || chars + w.word.length + 1 > PAGE_CHARS)) flush();
    current.push(w);
    chars += w.word.length + 1;
    if (/[.?!…]$/.test(w.word)) flush();
  }
  flush();
  return pages;
};

const Captions: React.FC<{ words: AnimWord[]; brand: Brand; speakers: AnimProps["speakers"]; until: number }> = ({ words, brand, speakers, until }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  if (t >= until) return null;
  const pages = paginate(words);
  // A page leaves shortly after its last word: between lines the picture is left clean.
  const page = pages.find((p) => t >= p.start - 0.06 && t < p.end + 0.35);
  if (!page) return null;
  const appear = interpolate(t, [page.start - 0.06, page.start + 0.1], [0, 1], clamp);
  const who = speakers[page.words[0].speaker];
  return (
    <div style={{ position: "absolute", left: SAFE.side, right: SAFE.side, bottom: SAFE.bottom - 40, display: "flex", flexDirection: "column",
                  alignItems: "center", gap: 14, opacity: appear, transform: `translateY(${(1 - appear) * 12}px)` }}>
      {who ? (
        <div style={{ fontFamily: FONT_BODY, fontWeight: 800, fontSize: 30, letterSpacing: 2, color: brand.ink, background: who.color,
                      padding: "5px 18px", borderRadius: 999, border: `3px solid ${brand.ink}` }}>
          {who.name.toUpperCase()}
        </div>
      ) : null}
      <div style={{ fontFamily: FONT_BODY, fontWeight: 800, fontSize: 60, lineHeight: 1.22, textAlign: "center", color: brand.paper,
                    maxWidth: 928, WebkitTextStroke: `10px ${brand.ink}`, paintOrder: "stroke fill" }}>
        {page.words.map((w, i) => (
          <span key={i} style={{ display: "inline-block", margin: "0 8px", color: t >= w.start - 0.03 && t < w.end + 0.08 ? brand.accent : brand.paper }}>
            {w.word}
          </span>
        ))}
      </div>
    </div>
  );
};

const fitTitle = (text: string) => (text.length > 60 ? 46 : text.length > 40 ? 54 : 62);

const TitleCard: React.FC<{ title: string; brand: Brand }> = ({ title, brand }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame: frame - 3, fps, config: { damping: 13, stiffness: 150 } });
  const leave = interpolate(frame, [TITLE_SECONDS * fps - 9, TITLE_SECONDS * fps], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", top: SAFE.top, left: SAFE.side, right: SAFE.side, display: "flex", justifyContent: "center",
                  opacity: leave, transform: `scale(${0.7 + 0.3 * pop}) rotate(${(1 - pop) * -4}deg)` }}>
      <div style={{ fontFamily: FONT_TITLE, fontSize: fitTitle(title), lineHeight: 1.12, textAlign: "center", color: brand.ink, background: brand.accent,
                    padding: "26px 34px", borderRadius: 30, border: `6px solid ${brand.ink}`, boxShadow: `0 12px 0 ${brand.ink}` }}>
        {title}
      </div>
    </div>
  );
};

// What kind of picture this is, when the scene has to say it ("Simulación simplificada").
const Label: React.FC<{ text: string; brand: Brand }> = ({ text, brand }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [6, 16], [0, 1], clamp);
  return (
    <div style={{ position: "absolute", top: SAFE.top - 70, left: SAFE.side, opacity: p, transform: `translateX(${(1 - p) * -20}px)`,
                  fontFamily: FONT_BODY, fontWeight: 800, fontSize: 30, letterSpacing: 2, color: brand.ink, background: brand.paper,
                  padding: "8px 18px", borderRadius: 10, border: `3px solid ${brand.ink}` }}>
      {text.toUpperCase()}
    </div>
  );
};

const SceneView: React.FC<{ src: string; label: string; brand: Brand; first: boolean; overlayOnly: boolean }> = ({ src, label, brand, first, overlayOnly }) => {
  const frame = useCurrentFrame();
  const settle = first ? 1 : interpolate(frame, [0, SETTLE], [0, 1], clamp);
  if (overlayOnly) {
    // The cut itself: a short white blink over the scene change.
    return (
      <AbsoluteFill>
        {first ? null : <AbsoluteFill style={{ background: "#fff", opacity: 0.5 * (1 - settle) }} />}
        {label ? <Label text={label} brand={brand} /> : null}
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ transform: `scale(${1.045 - 0.045 * settle})`, opacity: 0.55 + 0.45 * settle }}>
      <OffthreadVideo src={staticFile(src)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      {label ? <Label text={label} brand={brand} /> : null}
    </AbsoluteFill>
  );
};

const Closing: React.FC<{ p: AnimProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rise = spring({ frame, fps, config: { damping: 15, stiffness: 120 } });
  const button = spring({ frame: frame - 28, fps, config: { damping: 11, stiffness: 170 } });
  return (
    <AbsoluteFill style={{ background: p.brand.accent2, alignItems: "center", justifyContent: "center", gap: 34, padding: SAFE.side }}>
      <div style={{ fontFamily: FONT_TITLE, fontSize: 118, color: p.brand.paper, WebkitTextStroke: `14px ${p.brand.ink}`, paintOrder: "stroke fill",
                    transform: `translateY(${(1 - rise) * 60}px)`, opacity: rise }}>
        {p.channel}
      </div>
      <div style={{ fontFamily: FONT_BODY, fontWeight: 800, fontSize: 44, color: p.brand.ink, textAlign: "center", opacity: rise }}>{p.slogan}</div>
      {p.closingLine ? (
        <div style={{ fontFamily: FONT_BODY, fontWeight: 500, fontSize: 38, color: p.brand.ink, textAlign: "center", opacity: rise, maxWidth: 820 }}>{p.closingLine}</div>
      ) : null}
      {p.subscribe ? (
        <div style={{ marginTop: 26, fontFamily: FONT_BODY, fontWeight: 800, fontSize: 46, color: p.brand.ink, background: p.brand.accent,
                      padding: "18px 46px", borderRadius: 999, border: `5px solid ${p.brand.ink}`, boxShadow: `0 9px 0 ${p.brand.ink}`,
                      transform: `scale(${button})` }}>
          {p.subscribe}
        </div>
      ) : null}
      <div style={{ position: "absolute", bottom: SAFE.bottom, fontFamily: FONT_BODY, fontWeight: 500, fontSize: 28, color: p.brand.ink, opacity: 0.8 * rise }}>
        Fuentes en la descripción
      </div>
    </AbsoluteFill>
  );
};

const useFonts = () => {
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    fontsReady.then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, [handle]);
};

export const AnimShort: React.FC<AnimProps> = (p) => {
  useFonts();
  const { fps } = useVideoConfig();
  const end = Math.round(p.durationSeconds * fps);
  return (
    <AbsoluteFill style={{ background: p.overlayOnly ? "transparent" : p.brand.ink }}>
      {p.scenes.map((s, i) => (
        <Sequence key={i} from={Math.round(s.start * fps)} durationInFrames={Math.round(s.duration * fps)}>
          <SceneView src={s.src} label={s.label} brand={p.brand} first={i === 0} overlayOnly={Boolean(p.overlayOnly)} />
        </Sequence>
      ))}
      <Sequence durationInFrames={Math.round(TITLE_SECONDS * fps)}>
        <TitleCard title={p.title} brand={p.brand} />
      </Sequence>
      <Captions words={p.words} brand={p.brand} speakers={p.speakers} until={p.durationSeconds} />
      <Sequence from={end}>
        <Closing p={p} />
      </Sequence>
      <Audio src={staticFile(p.audio)} />
      {p.music ? (
        <Loop durationInFrames={Math.round(p.music.loopSeconds * fps)}>
          <Audio src={staticFile(p.music.src)} volume={p.music.volume} />
        </Loop>
      ) : null}
      {p.shots.map((s, i) => (
        <Sequence key={i} from={Math.round(s.at * fps)} durationInFrames={Math.max(1, Math.round(s.seconds * fps))}>
          <Audio src={staticFile(s.src)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

// The cover: a frame of the episode with its question over it.
export const AnimThumb: React.FC<AnimProps> = (p) => {
  useFonts();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: p.brand.ink }}>
      <OffthreadVideo src={staticFile(p.thumb.src)} muted startFrom={Math.round(p.thumb.at * fps)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 100%)" }} />
      <div style={{ position: "absolute", left: SAFE.side, right: SAFE.side, bottom: 300, fontFamily: FONT_TITLE, fontSize: fitTitle(p.title) + 22,
                    lineHeight: 1.1, textAlign: "center", color: p.brand.accent, WebkitTextStroke: `16px ${p.brand.ink}`, paintOrder: "stroke fill" }}>
        {p.title}
      </div>
    </AbsoluteFill>
  );
};
