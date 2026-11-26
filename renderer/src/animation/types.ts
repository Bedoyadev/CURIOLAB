// Props of the animated Short. Nothing here names a channel or a character: brand, names and
// colours arrive from the channel's profile and the asset library.
export type Brand = { ink: string; paper: string; accent: string; accent2: string };

// A scene drawn by Godot: an MP4 of exactly `duration` seconds that starts at `start`.
export type AnimScene = { src: string; start: number; duration: number; label: string };

export type AnimWord = { word: string; start: number; end: number; speaker: string; scene: number; line: number };

export type Shot = { src: string; at: number; seconds: number; volume: number };

// `type` (not `interface`): Remotion's Composition requires props assignable to Record<string, unknown>.
export type AnimProps = {
  brand: Brand;
  channel: string; slogan: string; closingLine: string; subscribe: string;
  title: string;
  scenes: AnimScene[]; words: AnimWord[];
  speakers: Record<string, { name: string; color: string }>;
  // The dialogue, already mixed into one track as long as the scenes.
  audio: string;
  music: { src: string; volume: number; loopSeconds: number } | null;
  shots: Shot[];
  // Length of the scenes; the closing card runs for `tailSeconds` after them.
  durationSeconds: number; tailSeconds: number;
  // The frame the cover is taken from.
  thumb: { src: string; at: number };
  // Only what goes over the scenes (title, captions, labels, closing card, sound), on a
  // transparent background: FFmpeg lays it over the scenes, which is much faster than having the
  // browser decode them frame by frame.
  overlayOnly?: boolean;
};
