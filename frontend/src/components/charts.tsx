/**
 * Hand-rolled SVG charts matching the design's chart language:
 * thin grid lines, rounded line paths, soft area fills, rounded bars.
 * All charts use viewBox + preserveAspectRatio="none" and scale to width.
 */
import { useState } from 'react'

export interface Pt {
  x: number
  y: number
}

// ── hover ──────────────────────────────────────────────────────────────────
//
// Every chart here stretches a fixed viewBox to the container's width
// (preserveAspectRatio="none"), so viewBox units are NOT screen pixels and a
// pointer's SVG coordinate can't be read off the event. The pointer is
// therefore resolved against the wrapper element's own rect and turned into a
// data index; the chart then maps that index back to viewBox space itself,
// which it can do exactly because it owns its geometry.

export type HoverMode =
  /** Bars/columns: the plot is `count` equal slices, hit anywhere in a slice. */
  | 'band'
  /** Lines/dots: samples sit ON the edges, so the nearest one wins. */
  | 'point'

export interface ChartHover {
  index: number | null
  bind: {
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => void
    onPointerLeave: () => void
  }
}

export function useChartHover(count: number, mode: HoverMode = 'band'): ChartHover {
  const [index, setIndex] = useState<number | null>(null)
  return {
    index: index != null && index < count ? index : null,
    bind: {
      onPointerMove: (e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        if (count <= 0 || rect.width <= 0) return
        const f = (e.clientX - rect.left) / rect.width
        const raw = mode === 'band' ? Math.floor(f * count) : Math.round(f * (count - 1))
        setIndex(Math.max(0, Math.min(count - 1, raw)))
      },
      onPointerLeave: () => setIndex(null),
    },
  }
}

/** Fraction across the plot, 0–1, of the slot the hover resolved to. */
export function hoverFraction(index: number, count: number, mode: HoverMode = 'band'): number {
  if (count <= 0) return 0
  if (mode === 'band') return (index + 0.5) / count
  return count > 1 ? index / (count - 1) : 0.5
}

/**
 * Tooltip pinned to a top corner of the plot — the one AWAY from the mark being
 * hovered, so it never sits on top of it.
 *
 * It deliberately does not track the pointer. A tooltip centred on the mark
 * covers it whenever the card is short (150px here, against a ~140px tooltip),
 * and one that tracks horizontally has no width it can clamp itself to without
 * measuring, so it overflows the card on narrow screens. A fixed corner has
 * neither problem, and the crosshair plus the highlighted mark already say
 * *which* point the numbers belong to.
 *
 * Must live inside an element carrying `.chart-hover` (position: relative),
 * which is also what `bind` should be spread onto.
 */
export function ChartTooltip({
  index,
  count,
  mode = 'band',
  children,
}: {
  index: number | null
  count: number
  mode?: HoverMode
  children: React.ReactNode
}) {
  if (index == null) return null
  const side = hoverFraction(index, count, mode) < 0.5 ? 'right' : 'left'
  return (
    <div className="chart-tip" data-side={side}>
      {children}
    </div>
  )
}

/** One row of a tooltip: swatch + label + value. */
export function TipRow({ color, label, value }: { color?: string; label: string; value: React.ReactNode }) {
  return (
    <div className="tip-row">
      {color && <span className="tip-sw" style={{ background: color }} />}
      <span className="tip-label">{label}</span>
      <span className="tip-value">{value}</span>
    </div>
  )
}

/** Vertical rule marking the hovered slot, in viewBox coordinates. */
export function Crosshair({ x, h }: { x: number; h: number }) {
  return <path d={`M${x.toFixed(1)} 0 V${h}`} stroke="var(--text-3)" strokeWidth="1" opacity="0.45" fill="none" />
}

/** Map values into an SVG path across a fixed viewbox. */
export function linePath(
  values: (number | null)[],
  opts: { w: number; h: number; min?: number; max?: number; pad?: number; connectGaps?: boolean },
): { path: string; min: number; max: number } {
  const present = values.filter((v): v is number => v != null && Number.isFinite(v))
  if (present.length === 0) return { path: '', min: 0, max: 1 }
  const pad = opts.pad ?? 0.08
  let min = opts.min ?? Math.min(...present)
  let max = opts.max ?? Math.max(...present)
  if (min === max) {
    min -= 1
    max += 1
  }
  const range = max - min
  min -= range * pad
  max += range * pad

  const dx = values.length > 1 ? opts.w / (values.length - 1) : 0
  let path = ''
  let pen = false
  values.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) {
      // Sparse metrics are the norm (weight logged occasionally); by default
      // bridge gaps so the trend stays a line instead of orphaned points.
      if (!opts.connectGaps) pen = false
      return
    }
    const x = (i * dx).toFixed(1)
    const y = (opts.h - ((v - min) / (max - min)) * opts.h).toFixed(1)
    path += `${pen ? 'L' : 'M'}${x} ${y}`
    pen = true
  })
  return { path, min, max }
}

export function areaFromLine(path: string, w: number, h: number): string {
  if (!path) return ''
  return `${path} L${w} ${h} L0 ${h} Z`
}

export function GridLines({ w, h, rows = 3 }: { w: number; h: number; rows?: number }) {
  const ys = Array.from({ length: rows }, (_, i) => ((i + 1) * h) / (rows + 1))
  return (
    <path
      d={ys.map((y) => `M0 ${y.toFixed(1)} H${w}`).join(' ')}
      stroke="var(--grid-line)"
      strokeWidth="1"
      fill="none"
    />
  )
}

/**
 * Seconds from the first sample to the bucket a downsampled index came from.
 *
 * `downsample` averages away the timestamps, so a hovered bucket can't say when
 * it happened; this re-derives it from the same bucketing arithmetic.
 */
export function bucketElapsed(
  samples: { timestamp: string }[],
  index: number,
  buckets: number,
): number | null {
  if (samples.length === 0 || buckets <= 0) return null
  const step = samples.length / buckets
  const s = samples[Math.min(samples.length - 1, Math.floor(index * step))]
  const t0 = new Date(samples[0].timestamp).getTime()
  const t = new Date(s.timestamp).getTime()
  if (!Number.isFinite(t) || !Number.isFinite(t0)) return null
  return (t - t0) / 1000
}

/** Downsample an array to at most n points (mean of each bucket). */
export function downsample(values: number[], n: number): number[] {
  if (values.length <= n) return values
  const out: number[] = []
  const step = values.length / n
  for (let i = 0; i < n; i++) {
    const start = Math.floor(i * step)
    const end = Math.max(start + 1, Math.floor((i + 1) * step))
    const bucket = values.slice(start, end)
    out.push(bucket.reduce((a, b) => a + b, 0) / bucket.length)
  }
  return out
}

/** HR zone bands (default bpm boundaries; drawn only where they intersect the y-domain). */
export const HR_ZONES: { name: string; from: number; to: number; color: string }[] = [
  { name: 'Z1', from: 0, to: 120, color: 'rgba(94,124,142,0.10)' },
  { name: 'Z2', from: 120, to: 140, color: 'rgba(95,168,138,0.11)' },
  { name: 'Z3', from: 140, to: 155, color: 'rgba(217,169,62,0.10)' },
  { name: 'Z4', from: 155, to: 170, color: 'rgba(238,123,60,0.10)' },
  { name: 'Z5', from: 170, to: 240, color: 'rgba(220,74,59,0.10)' },
]

export const HR_ZONE_LEGEND: { name: string; color: string }[] = [
  { name: 'Z1', color: '#5E7C8E' },
  { name: 'Z2', color: '#5FA88A' },
  { name: 'Z3', color: '#D9A93E' },
  { name: 'Z4', color: '#EE7B3C' },
  { name: 'Z5', color: '#DC4A3B' },
]

export function zoneBands(min: number, max: number, w: number, h: number) {
  return HR_ZONES.flatMap((z) => {
    const lo = Math.max(z.from, min)
    const hi = Math.min(z.to, max)
    if (hi <= lo) return []
    const y = h - ((hi - min) / (max - min)) * h
    const bandH = ((hi - lo) / (max - min)) * h
    return [{ key: z.name, y, h: bandH, color: z.color, w }]
  })
}
