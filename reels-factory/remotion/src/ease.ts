/* GSAP eğrilerinin karşılıkları ve zaman çizelgesi yardımcıları (HyperFrames şablonlarıyla aynı hareket). */
export type Ease = (t: number) => number;

const backOut = (s: number): Ease => (t) => 1 + (s + 1) * Math.pow(t - 1, 3) + s * Math.pow(t - 1, 2);
const inOut = (p: number): Ease => (t) => (t < 0.5 ? Math.pow(2 * t, p) / 2 : 1 - Math.pow(2 - 2 * t, p) / 2);

export const EASE: Record<string, Ease> = {
  none: (t) => t,
  "power1.in": (t) => t * t,
  "power2.in": (t) => t * t * t,
  "power3.in": (t) => t * t * t * t,
  "power2.out": (t) => 1 - Math.pow(1 - t, 3),
  "power3.out": (t) => 1 - Math.pow(1 - t, 4),
  "power2.inOut": inOut(3),
  "power3.inOut": inOut(4),
  "expo.out": (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  "sine.inOut": (t) => -(Math.cos(Math.PI * t) - 1) / 2,
  "back.out(1.6)": backOut(1.6),
  "back.out(2)": backOut(2),
  "back.out(2.2)": backOut(2.2),
};

export type Seg = { at: number; dur: number; to: number; from?: number; ease?: string };

/** Bir özelliğin zaman içindeki değeri. GSAP gibi: fromTo başlamadan önce "from" değeri uygulanır (ilk segment),
 * to segmenti o anki değerden başlar. Segmentler zamana göre sıralı verilmeli. */
export function track(t: number, base: number, segs: Seg[]): number {
  let v = base;
  segs.forEach((s, i) => {
    if (t < s.at) {
      if (i === 0 && s.from !== undefined) v = s.from;
      return;
    }
    const from = s.from !== undefined ? s.from : v;
    const p = s.dur <= 0 ? 1 : Math.min(1, (t - s.at) / s.dur);
    v = from + (s.to - from) * (EASE[s.ease || "none"] || EASE.none)(p);
  });
  return v;
}

const hex = (c: string) => {
  const m = c.replace("#", "");
  const n = m.length === 3 ? m.split("").map((x) => x + x).join("") : m.slice(0, 6);
  return [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16));
};
/** İki renk arasında karışım (0 → a, 1 → b). */
export function mix(a: string, b: string, p: number): string {
  const x = hex(a), y = hex(b);
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * Math.max(0, Math.min(1, p)))).join(",")})`;
}

/** Türkçe sayı biçimi (binlik nokta, ondalık virgül) — şablondaki fmt ile aynı. */
export function fmt(v: number, dec: number): string {
  const fixed = Math.abs(v).toFixed(dec);
  const parts = fixed.split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (v < 0 ? "-" : "") + parts.join(",");
}
