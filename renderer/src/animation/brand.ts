import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

export const FONT_TITLE = "Archivo Black";
export const FONT_BODY = "Inter";

export const fontsReady = Promise.all([
  loadFont({ family: FONT_TITLE, url: staticFile("fonts/ArchivoBlack-Regular.ttf"), weight: "400" }),
  loadFont({ family: FONT_BODY, url: staticFile("fonts/Inter.ttf"), weight: "500" }),
  loadFont({ family: FONT_BODY, url: staticFile("fonts/Inter.ttf"), weight: "800" }),
]);

// Safe area for the Shorts interface (px, 1080x1920 canvas).
export const SAFE = { top: 210, bottom: 430, side: 76 } as const;
export const EASE = [0.22, 1, 0.36, 1] as const;
