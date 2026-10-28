/* Reels Fabrikası — Remotion render motoru.
 * Bütün yerleşim (metin satırları, konumlar, boyutlar, zamanlar) Python'da compose.build_project tarafından
 * hesaplanır ve composition/remotion.json olarak verilir; burada yalnızca çizim ve HyperFrames şablonlarıyla
 * (assets/templates/*.j2) aynı hareketler vardır. Medya ve font: --public-dir composition/ (assets/...). */
import React, { useEffect, useState } from "react";
import {
  AbsoluteFill, Img, OffthreadVideo, Sequence, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig,
} from "remotion";
import { fmt, mix, track } from "./ease";

type Colors = { bg: string; bg2: string; ink: string; accent: string; accent2: string };
type AnyRec = Record<string, any>;
export type Look = {
  caption_style?: string; chip?: string; grain?: number; vignette?: number; letterbox?: boolean; scanlines?: boolean;
  cam_filter?: string; progress?: string;
};
export type ReelsProps = {
  W: number; H: number; fps: number; total: number; look?: Look;
  brand: { font_family: string; colors: Colors };
  handle: string; margin: number; bar_y: number;
  scenes: { start: number; duration: number; d: AnyRec }[];
  captions: { groups: AnyRec[]; js: AnyRec[]; center_y: number; stroke: number; word_spacing: number } | null;
};

const FONT = "RFBrand";
const media = (f: string) => staticFile(`assets/media/${f}`);

function useBrandFont() {
  const [handle] = useState(() => delayRender("marka yazı tipi"));
  useEffect(() => {
    const face = new FontFace(FONT, `url(${staticFile("assets/fonts/brand.ttf")})`, { weight: "100 900" });
    face.load().then((f) => { document.fonts.add(f); continueRender(handle); })
      .catch(() => continueRender(handle));   // yazı tipi yoksa sistem yazı tipiyle devam
  }, [handle]);
}

/* ------------------------------------------------------------------ sahne */
const Scene: React.FC<{ d: AnyRec; c: Colors; W: number; H: number; look: Look }> = ({ d, c, W, H, look }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const J = d.js, ov = J.overlap as number, mv = J.move;
  const bg = d.bg || {};

  /* sahne girişi / çıkışı */
  let scale = 1, x = 0, opacity = 1, blur = 0, clip = "none";
  if (d.enter === "zoom") {
    scale = track(t, 1, [{ at: 0, dur: ov + 0.08, from: 1.28, to: 1, ease: "expo.out" }]);
    opacity = track(t, 1, [{ at: 0, dur: ov + 0.08, from: 0, to: 1, ease: "expo.out" }]);
    blur = track(t, 0, [{ at: 0, dur: ov + 0.08, from: 18, to: 0, ease: "expo.out" }]);
  } else if (d.enter === "whip") {
    x = track(t, 0, [{ at: 0, dur: ov, from: W, to: 0, ease: "power3.out" }]);
    blur = track(t, 0, [{ at: 0, dur: ov, from: 26, to: 0, ease: "power3.out" }]);
  } else if (d.enter === "iris") {
    clip = `circle(${track(t, 120, [{ at: 0, dur: ov + 0.15, from: 0, to: 120, ease: "power2.inOut" }])}% at 50% 40%)`;
  } else if (d.enter === "wipe") {
    clip = `inset(${track(t, 0, [{ at: 0, dur: ov + 0.1, from: 100, to: 0, ease: "power3.inOut" }])}% 0% 0% 0%)`;
  }
  let dip = 0;
  if (J.exit_at !== null && J.exit_at !== undefined) {
    const e = J.exit_at as number, nx = J.exit;
    if (nx === "zoom") {
      scale = track(t, scale, [{ at: e, dur: ov, to: 1.14, ease: "power2.in" }]);
      blur = Math.max(blur, track(t, 0, [{ at: e, dur: ov, to: 10, ease: "power2.in" }]));
    } else if (nx === "whip") {
      x += track(t, 0, [{ at: e, dur: ov * 0.9, to: -380, ease: "power3.in" }]);
      blur = Math.max(blur, track(t, 0, [{ at: e, dur: ov * 0.9, to: 16, ease: "power3.in" }]));
    } else if (nx === "iris") {
      scale = track(t, scale, [{ at: e, dur: ov + 0.15, to: 1.06, ease: "power2.in" }]);
      dip = track(t, 0, [{ at: e, dur: ov + 0.15, to: 0.35, ease: "power1.in" }]);
    } else if (nx === "wipe") {
      dip = track(t, 0, [{ at: e, dur: ov, to: 0.45, ease: "power1.in" }]);
    } else {
      dip = track(t, 0, [{ at: Math.max(0, e - 0.1), dur: 0.1, to: 0.4 }]);
    }
  }
  const wipeY = d.enter === "wipe" ? track(t, 0, [{ at: 0, dur: ov + 0.1, from: 0, to: -H - 22, ease: "power3.inOut" }]) : 0;
  const wipeOn = d.enter === "wipe" && t < ov + 0.12;

  /* kamera (arka plan) */
  const camP = Math.min(1, t / J.dur);
  const cs = track(camP, mv.s0, [{ at: 0, dur: 1, from: mv.s0, to: mv.s1, ease: "sine.inOut" }]);
  const cx = track(camP, mv.x0, [{ at: 0, dur: 1, from: mv.x0, to: mv.x1, ease: "sine.inOut" }]);
  const cy = track(camP, mv.y0, [{ at: 0, dur: 1, from: mv.y0, to: mv.y1, ease: "sine.inOut" }]);
  const full: React.CSSProperties = { position: "absolute", left: 0, top: 0, width: W, height: H, objectFit: "cover" };
  const ground = <div style={{ position: "absolute", inset: 0, background: `linear-gradient(160deg, ${c.bg2} 0%, ${c.bg} 60%)` }} />;
  const dots = (d.dots || []).map((p: AnyRec, i: number) => (
    <div key={`d${i}`} style={{ position: "absolute", borderRadius: "50%", background: "#fff", left: p.x, top: p.y, width: p.r, height: p.r, opacity: p.a,
      transform: `translateY(${-(J.dots?.[i]?.rise || 0) * camP}px)` }} />));
  let back: React.ReactNode;
  if (bg.type === "graphic") {
    back = <>{ground}{(d.blobs || []).map((b: AnyRec, i: number) => {
      const jb = J.blobs?.[i] || { dx: 0, dy: 0 };
      const k = track(camP, 0, [{ at: 0, dur: 1, from: 0, to: 1, ease: "sine.inOut" }]);
      return <div key={`b${i}`} style={{ position: "absolute", borderRadius: "50%", left: b.x, top: b.y, width: b.r, height: b.r,
        background: `radial-gradient(circle, ${b.color} 0%, rgba(0,0,0,0) 68%)`, transform: `translate(${jb.dx * k}px, ${jb.dy * k}px)` }} />;
    })}{dots}</>;
  } else if (bg.fit === "card") {
    back = <>{ground}<Img src={media(bg.bgsrc)} style={full} /></>;
  } else if (bg.fit === "contain" && bg.type === "photo") {
    const k = d.contain;
    const mask = "linear-gradient(180deg, transparent 0%, #000 16%, #000 84%, transparent 100%)";
    back = <>{ground}<Img src={media(bg.bgsrc)} style={{ ...full, opacity: 0.28 }} />{dots}
      <div style={{ position: "absolute", left: k.x, top: k.y, width: k.w, height: k.h, WebkitMaskImage: mask, maskImage: mask }}>
        <Img src={media(bg.src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} /></div></>;
  } else if (bg.type === "video") {
    back = <OffthreadVideo src={media(bg.src)} muted style={full} />;
  } else if (bg.src || bg.bgsrc) {
    back = <Img src={media(bg.dim ? bg.bgsrc : bg.src)} style={full} />;
  } else {
    back = ground;
  }

  /* kart (fotoğraf/video çerçevesi) */
  let card: React.ReactNode = null;
  if (bg.fit === "card" && d.card) {
    const cy0 = track(t, 0, [{ at: J.t0, dur: 0.7, from: 60, to: 0, ease: "expo.out" }]);
    const csc = track(t, 1, [{ at: J.t0, dur: 0.7, from: 0.94, to: 1, ease: "expo.out" }]);
    const cop = track(t, 1, [{ at: J.t0, dur: 0.7, from: 0, to: 1, ease: "expo.out" }]);
    const inner = 1 + 0.09 * camP;
    const fill: React.CSSProperties = { position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" };
    card = <div style={{ position: "absolute", left: d.card.x, top: d.card.y, width: d.card.w, height: d.card.h, overflow: "hidden",
      borderRadius: 36, background: "#000", boxShadow: "0 34px 90px rgba(0,0,0,.6), 0 0 0 2px rgba(255,255,255,.10)",
      transform: `translateY(${cy0}px) scale(${csc})`, opacity: cop }}>
      <div style={{ position: "absolute", inset: 0, transform: `scale(${inner})` }}>
        {bg.type === "video" ? <OffthreadVideo src={media(bg.src)} muted style={fill} /> : <Img src={media(bg.src)} style={fill} />}
      </div></div>;
  }

  const row: React.CSSProperties = { position: "absolute", left: 0, width: W, textAlign: "center", whiteSpace: "nowrap" };
  const pill = (style: string, size: number): React.CSSProperties => style === "ghost"
    ? { display: "inline-block", padding: "14px 28px 13px", borderRadius: 999, background: "rgba(255,255,255,.12)", color: c.ink,
        fontWeight: 750, letterSpacing: ".06em", boxShadow: "inset 0 0 0 2px rgba(255,255,255,.22)", fontSize: size }
    : { display: "inline-block", padding: "16px 30px 15px", borderRadius: look.chip === "bar" ? 6 : 999, background: c.accent, color: c.bg,
        fontWeight: 800, letterSpacing: ".08em", fontSize: size, boxShadow: look.chip === "bar" ? `-12px 0 0 ${c.accent2}` : undefined };

  /* metin blokları */
  const blocks = (d.blocks || []).map((blk: AnyRec, bi: number) => {
    const bj = J.blocks?.[bi] || { words: [], mode: "static", t: 0, stagger: 0, pops: [], lines: [] };
    const order: Record<string, number> = {};
    bj.words.forEach((w: string, i: number) => { order[w] = i; });
    const pops: Record<string, number> = {};
    (bj.pops || []).forEach((p: AnyRec) => { pops[p.id] = p.t; });
    return blk.lines.map((line: AnyRec) => {
      const ls = bj.mode === "punch" ? track(t, 1, [{ at: 0, dur: 0.6, from: 1.05, to: 1, ease: "expo.out" }]) : 1;
      return <div key={line.id} style={{ ...row, top: line.y, fontSize: blk.size, fontWeight: blk.weight, letterSpacing: `${blk.ls}em`,
        lineHeight: 1, transform: `scale(${ls})` }}>
        {line.words.map((w: AnyRec, wi: number) => {
          const at = bj.t + (order[w.id] ?? 0) * bj.stagger;
          let o = 1, y = 0, b = 0, s = 1;
          if (bj.mode === "rise") {
            o = track(t, 1, [{ at, dur: 0.5, from: 0, to: 1, ease: "expo.out" }]);
            y = track(t, 0, [{ at, dur: 0.5, from: 34, to: 0, ease: "expo.out" }]);
          } else if (bj.mode !== "static" && bj.mode !== "punch") {
            o = track(t, 1, [{ at, dur: 0.16, from: 0, to: 1, ease: "power2.out" }]);
            b = track(t, 0, [{ at, dur: 0.16, from: 8, to: 0, ease: "power2.out" }]);
          }
          if (pops[w.id] !== undefined) {
            const pt = pops[w.id];
            s = track(t, 1, [{ at: pt, dur: 0.14, from: 1, to: 1.08, ease: "power2.out" }, { at: pt + 0.14, dur: 0.32, to: 1, ease: "back.out(2)" }]);
          }
          const color = w.hl === "hl" ? c.accent : w.hl === "hl2" ? c.accent2 : undefined;
          return <React.Fragment key={w.id}>
            <span style={{ display: "inline-block", opacity: o, transform: `translateY(${y}px) scale(${s})`, filter: b ? `blur(${b}px)` : undefined, color }}>{w.text}</span>
            {wi < line.words.length - 1 ? " " : null}
          </React.Fragment>;
        })}
      </div>;
    });
  });

  const chips = (d.chips || []).map((ch: AnyRec, i: number) => {
    const cj = J.chips?.[i] || { static: true, t: 0 };
    const p = cj.static ? 100 : track(t, 100, [{ at: cj.t, dur: 0.45, from: 0, to: 100, ease: "power3.out" }]);
    const cx2 = cj.static ? 0 : track(t, 0, [{ at: cj.t, dur: 0.45, from: -24, to: 0, ease: "power3.out" }]);
    return <div key={ch.id} style={{ ...row, top: ch.y }}><span style={{ ...pill(ch.style, ch.size), clipPath: `inset(0% ${100 - p}% 0% 0%)`,
      transform: `translateX(${cx2}px)` }}>{ch.text}</span></div>;
  });

  /* sayaç */
  let stat: React.ReactNode = null;
  if (d.stat && J.stat) {
    const s = J.stat, st = d.stat;
    const no = track(t, 1, [{ at: s.t - 0.2, dur: 0.5, from: 0, to: 1, ease: "back.out(1.6)" }]);
    const ns = track(t, 1, [{ at: s.t - 0.2, dur: 0.5, from: 0.7, to: 1, ease: "back.out(1.6)" },
      { at: s.t + s.count_dur, dur: 0.12, to: 1.08, ease: "power2.out" }, { at: s.t + s.count_dur + 0.12, dur: 0.35, to: 1, ease: "back.out(2)" }]);
    const v = t < s.t ? null : t >= s.t + s.count_dur ? s.value : track(t, 0, [{ at: s.t, dur: s.count_dur, from: 0, to: s.value, ease: "power2.out" }]);
    const fill = track(t, 1, [{ at: s.t, dur: s.count_dur, from: 0, to: 1, ease: "power2.out" }]);
    const to = track(t, 1, [{ at: s.t - 0.2, dur: 0.3, from: 0, to: 1 }]);
    stat = <>
      <div style={{ ...row, top: st.y, fontSize: st.size, color: c.accent, fontWeight: 900, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
        <span style={{ display: "inline-block", opacity: no, transform: `scale(${ns})` }}>{v === null ? st.start_text : s.prefix + fmt(v, s.decimals) + s.suffix}</span></div>
      <div style={{ position: "absolute", left: st.bar.x, top: st.bar.y, width: st.bar.w, height: st.bar.h, borderRadius: 999,
        background: "rgba(255,255,255,.14)", overflow: "hidden", opacity: to }}>
        <div style={{ position: "absolute", left: 0, top: 0, height: "100%", width: "100%", borderRadius: 999, transformOrigin: "0 50%",
          transform: `scaleX(${fill})`, background: `linear-gradient(90deg, ${c.accent}, ${c.accent2})` }} /></div></>;
  }

  /* karşılaştırma */
  const compare = (d.compare || []).map((it: AnyRec, i: number) => {
    const cj = J.compare?.[i] || { t: 0, value: 0, decimals: 0, suffix: "", display: it.start_text };
    const lo = track(t, 1, [{ at: cj.t - 0.25, dur: 0.45, from: 0, to: 1, ease: "expo.out" }]);
    const lx = track(t, 0, [{ at: cj.t - 0.25, dur: 0.45, from: -30, to: 0, ease: "expo.out" }]);
    const tr = track(t, 1, [{ at: cj.t - 0.25, dur: 0.3, from: 0, to: 1 }]);
    const vo = track(t, 1, [{ at: cj.t - 0.1, dur: 0.3, from: 0, to: 1 }]);
    const fl = track(t, 1, [{ at: cj.t, dur: 1.0, from: 0, to: 1, ease: "power3.out" }]);
    const val = t < cj.t ? it.start_text : t >= cj.t + 1 ? cj.display
      : fmt(track(t, 0, [{ at: cj.t, dur: 1, from: 0, to: cj.value, ease: "power3.out" }]), cj.decimals) + cj.suffix;
    const txt: React.CSSProperties = { position: "absolute", fontWeight: 750, whiteSpace: "nowrap" };
    return <React.Fragment key={it.id}>
      <div style={{ ...txt, left: it.x, top: it.label_y, fontSize: it.label_size, opacity: lo, transform: `translateX(${lx}px)` }}>{it.label}</div>
      <div style={{ ...txt, left: it.x, width: it.w, textAlign: "right", top: it.val_y, fontSize: it.val_size, color: it.color, fontWeight: 900,
        fontVariantNumeric: "tabular-nums", lineHeight: 1, opacity: vo }}>{val}</div>
      <div style={{ position: "absolute", left: it.x, top: it.bar_y, width: it.w, height: it.bar_h, borderRadius: 999,
        background: "rgba(255,255,255,.14)", overflow: "hidden", opacity: tr }}>
        <div style={{ position: "absolute", left: 0, top: 0, height: "100%", width: it.fill_w, borderRadius: 999, background: it.color,
          transformOrigin: "0 50%", transform: `scaleX(${fl})` }} /></div>
    </React.Fragment>;
  });

  /* liste */
  const items = (d.list_items || []).map((it: AnyRec, i: number) => {
    const ij = J.items?.[i] || { t: 0 };
    const o = track(t, 1, [{ at: ij.t, dur: 0.55, from: 0, to: 1, ease: "expo.out" }]);
    const ix = track(t, 0, [{ at: ij.t, dur: 0.55, from: 70, to: 0, ease: "expo.out" }]);
    const ib = track(t, 0, [{ at: ij.t, dur: 0.55, from: 6, to: 0, ease: "expo.out" }]);
    return <div key={it.id} style={{ position: "absolute", left: it.x, top: it.y, width: it.w, height: it.h, borderRadius: 28,
      background: "rgba(12,16,28,.72)", boxShadow: "inset 0 0 0 2px rgba(255,255,255,.10), 0 18px 40px rgba(0,0,0,.35)",
      opacity: o, transform: `translateX(${ix}px)`, filter: ib ? `blur(${ib}px)` : undefined }}>
      <div style={{ position: "absolute", left: 24, top: Math.floor((it.h - 72) / 2), width: 72, height: 72, lineHeight: "74px", fontSize: 38,
        borderRadius: "50%", background: c.accent, color: c.bg, fontWeight: 900, textAlign: "center" }}>{i + 1}</div>
      <div style={{ position: "absolute", left: 124, top: Math.floor((it.h - it.size) / 2), fontSize: it.size, lineHeight: 1,
        fontWeight: 750, whiteSpace: "nowrap" }}>{it.text}</div></div>;
  });

  return (
    <AbsoluteFill style={{ background: c.bg, overflow: "hidden", fontFamily: `${FONT}, sans-serif`, color: c.ink }}>
      <AbsoluteFill style={{ background: c.bg, overflow: "hidden", opacity, clipPath: clip,
        transform: `translateX(${x}px) scale(${scale})`, filter: blur ? `blur(${blur}px)` : undefined }}>
        <AbsoluteFill style={{ transform: `translate(${cx}px, ${cy}px) scale(${cs})`, filter: look.cam_filter || undefined }}>{back}</AbsoluteFill>
        <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, rgba(5,7,12,${d.shade_top}) 0%, rgba(5,7,12,0) 40%), `
          + `linear-gradient(0deg, rgba(5,7,12,${d.shade_bottom}) 0%, rgba(5,7,12,0) 46%), rgba(5,7,12,${d.shade_all})` }} />
        {look.vignette ? <div style={{ position: "absolute", inset: 0,
          background: `radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 45%, rgba(0,0,0,${look.vignette}) 100%)` }} /> : null}
        {look.scanlines ? <div style={{ position: "absolute", inset: 0, opacity: 0.16, background:
          "repeating-linear-gradient(0deg, rgba(0,0,0,.9) 0px, rgba(0,0,0,.9) 2px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 5px)" }} /> : null}
        {look.grain ? (() => {  /* şablondaki steps() kaymasıyla aynı: sabit doku, adım adım */
          const n = Math.max(2, Math.round(J.dur * 12)), k = Math.min(n, Math.floor(camP * n)) / n;
          return <div style={{ position: "absolute", left: -64, top: -64, width: W + 128, height: H + 128, opacity: look.grain,
            mixBlendMode: "overlay", background: `url(${staticFile("assets/fx/grain.png")})`, transform: `translate(${64 * k}px, ${48 * k}px)` }} />;
        })() : null}
        {look.letterbox ? <><div style={{ position: "absolute", left: 0, top: 0, width: W, height: 110, background: "#000" }} />
          <div style={{ position: "absolute", left: 0, top: H - 110, width: W, height: 110, background: "#000" }} /></> : null}
        {card}{chips}{blocks}{stat}{compare}{items}
        {wipeOn ? <div style={{ position: "absolute", left: 0, top: H, width: W, height: 22, background: c.accent, transform: `translateY(${wipeY}px)` }} /> : null}
        <div style={{ position: "absolute", inset: 0, background: "#000", opacity: dip }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* ------------------------------------------------------------------ altyazı */
const Captions: React.FC<{ cap: NonNullable<ReelsProps["captions"]>; c: Colors; W: number; style: string }> = ({ cap, c, W, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  return <AbsoluteFill style={{ fontFamily: `${FONT}, sans-serif` }}>
    {cap.groups.map((g: AnyRec, gi: number) => {
      const gj = cap.js[gi];
      if (!gj || t < gj.start - 0.01 || t >= gj.end) return null;
      const o = track(t, 1, [{ at: gj.start, dur: 0.14, from: 0, to: 1, ease: "back.out(2.2)" }, { at: gj.end - 0.1, dur: 0.1, to: 0, ease: "power2.in" }]);
      const s = track(t, 1, [{ at: gj.start, dur: 0.14, from: 0.86, to: 1, ease: "back.out(2.2)" }]);
      const y = track(t, 0, [{ at: gj.start, dur: 0.14, from: 18, to: 0, ease: "back.out(2.2)" }]);
      const wt: Record<string, AnyRec> = {};
      gj.words.forEach((w: AnyRec) => { wt[w.id] = w; });
      return <AbsoluteFill key={g.id} style={{ opacity: Math.max(0, Math.min(1, o)), transformOrigin: `50% ${cap.center_y}px`,
        transform: `translateY(${y}px) scale(${s})` }}>
        {g.lines.map((line: AnyRec, li: number) => (
          <div key={li} style={{ position: "absolute", left: 0, width: W, top: line.y, textAlign: "center", whiteSpace: "nowrap", lineHeight: 1,
            fontWeight: 900, letterSpacing: ".01em", wordSpacing: `${cap.word_spacing}em`, fontSize: g.size }}>
            {line.words.map((w: AnyRec, wi: number) => {
              const j = wt[w.id] || { start: 1e9, end: 1e9, emph: false };
              const baseC = w.emph ? c.accent2 : c.ink, hot = w.emph ? c.accent2 : c.accent;
              const back = Math.max(j.start + 0.08, j.end);
              let span: React.CSSProperties;
              if (style === "box") {  /* konuşulan kelime renkli kutuda (şablondaki box ile aynı) */
                const p = track(t, 0, [{ at: j.start, dur: 0.06, to: 1, ease: "power2.out" }, { at: back, dur: 0.12, to: 0, ease: "power2.out" }]);
                span = { color: mix(baseC, c.bg, p), transform: `scale(${1 + 0.04 * p})`, padding: "0 .14em", margin: "0 -.06em",
                  borderRadius: ".16em", background: p > 0.01 ? mix(c.bg, hot, p) : "transparent", textShadow: p > 0.5 ? undefined : "0 4px 18px rgba(0,0,0,.65)" };
              } else {
                const big = w.emph ? 1.14 : style === "shadow" ? 1.04 : 1.08;
                const p = track(t, 0, [{ at: j.start, dur: 0.08, to: 1, ease: "power2.out" }, { at: back, dur: 0.16, to: 0, ease: "power2.out" }]);
                span = style === "shadow"
                  ? { color: mix(baseC, hot, p), transform: `scale(${1 + (big - 1) * p})`,
                      textShadow: "0 3px 0 rgba(0,0,0,.55), 0 10px 30px rgba(0,0,0,.75), 0 0 2px rgba(0,0,0,.8)" }
                  : { color: mix(baseC, hot, p), transform: `scale(${1 + (big - 1) * p})`, WebkitTextStroke: `${cap.stroke}px rgba(5,7,12,.94)`,
                      paintOrder: "stroke fill", textShadow: "0 8px 26px rgba(0,0,0,.5)" };
              }
              return <React.Fragment key={w.id}>
                <span style={{ display: "inline-block", ...span }}>{w.text}</span>
                {wi < line.words.length - 1 ? " " : null}
              </React.Fragment>;
            })}
          </div>))}
      </AbsoluteFill>;
    })}
  </AbsoluteFill>;
};

/* ------------------------------------------------------------------ üst katman */
const Overlay: React.FC<{ p: ReelsProps }> = ({ p }) => {
  const frame = useCurrentFrame();
  const c = p.brand.colors;
  const prog = Math.min(1, frame / p.fps / p.total);
  return <AbsoluteFill style={{ fontFamily: `${FONT}, sans-serif`, pointerEvents: "none" }}>
    {(p.look?.progress || "top") !== "none" ? <div style={{ position: "absolute", left: p.margin,
      top: p.look?.progress === "bottom" ? p.H - 64 : p.bar_y, width: p.W - 2 * p.margin, height: 7, borderRadius: 999,
      background: "rgba(255,255,255,.20)", overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, borderRadius: 999, transformOrigin: "0 50%", transform: `scaleX(${prog})`,
        background: `linear-gradient(90deg, ${c.accent}, ${c.accent2})` }} /></div> : null}
    {p.handle ? <div style={{ position: "absolute", left: p.margin, top: p.bar_y + 22, fontSize: 28, fontWeight: 700, letterSpacing: ".04em",
      color: "rgba(255,255,255,.78)", textShadow: "0 2px 10px rgba(0,0,0,.6)" }}>{p.handle}</div> : null}
  </AbsoluteFill>;
};

export const Reels: React.FC<ReelsProps> = (p) => {
  useBrandFont();
  const c = p.brand.colors;
  return (
    <AbsoluteFill style={{ background: c.bg }}>
      {p.scenes.map((s, i) => (
        <Sequence key={s.d.id || i} from={Math.round(s.start * p.fps)} durationInFrames={Math.max(1, Math.round(s.duration * p.fps))}
          style={{ zIndex: i + 1 }}>
          <Scene d={s.d} c={c} W={p.W} H={p.H} look={p.look || {}} />
        </Sequence>
      ))}
      {p.captions ? <AbsoluteFill style={{ zIndex: 90 }}><Captions cap={p.captions} c={c} W={p.W} style={p.look?.caption_style || "stroke"} /></AbsoluteFill> : null}
      <AbsoluteFill style={{ zIndex: 95 }}><Overlay p={p} /></AbsoluteFill>
    </AbsoluteFill>
  );
};
