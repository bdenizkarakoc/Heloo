import React from "react";
import { Composition } from "remotion";
import { Reels, ReelsProps } from "./Reels";

/* Fabrika her görevde composition/remotion.json yazar ve `--props` ile verir; burası yalnızca boş varsayılan. */
const empty: ReelsProps = {
  W: 1080, H: 1920, fps: 30, total: 3,
  brand: { font_family: "Brand", colors: { bg: "#0b0f1a", bg2: "#141b2d", ink: "#ffffff", accent: "#ffd23f", accent2: "#4fd1c5" } },
  handle: "", margin: 72, bar_y: 176, scenes: [], captions: null,
};

export const Root: React.FC = () => (
  <Composition
    id="Reels"
    component={Reels}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={90}
    defaultProps={empty}
    calculateMetadata={({ props }) => ({
      width: props.W, height: props.H, fps: props.fps,
      durationInFrames: Math.max(1, Math.round(props.total * props.fps)),
    })}
  />
);
