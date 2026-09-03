import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * The four source hues, measured rather than asserted.
 *
 * THIS TEST EXISTS BECAUSE THE MEASUREMENT WAS WRONG ONCE. Three designers
 * each proposed moving a hue for colour blindness and all three were overruled
 * on a simulation run against colours the product did not use — emerald-500
 * and amber-400, while the app was painted in emerald-300 and amber-200. What
 * actually shipped had a worst pair of dE 8.8: `yours` against `invented`,
 * the DM's own material against a model's invention.
 *
 * A number in a comment cannot fail. This can.
 */

const CSS = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf8')

function token(name: string): [number, number, number] {
  const found = CSS.match(new RegExp(`--color-${name}:\\s*#([0-9a-f]{6})`, 'i'))
  if (!found) throw new Error(`no --color-${name} in globals.css`)
  const hex = found[1]
  return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number]
}

const linear = (c: number) => {
  const v = c / 255
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}
const encode = (c: number) => {
  const v = Math.max(0, Math.min(1, c))
  return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055
}

/** Viénot 1999 simulation of the two common colour blindnesses. */
function simulate(rgb: number[], kind: 'deuter' | 'protan'): number[] {
  const [r, g, b] = rgb.map(linear)
  const m =
    kind === 'deuter'
      ? [[0.625, 0.375, 0], [0.7, 0.3, 0], [0, 0.3, 0.7]]
      : [[0.567, 0.433, 0], [0.558, 0.442, 0], [0, 0.242, 0.758]]
  return m.map((row) => Math.round(encode(row[0] * r + row[1] * g + row[2] * b) * 255))
}

function lab(rgb: number[]): [number, number, number] {
  const [r, g, b] = rgb.map(linear)
  const X = 0.4124 * r + 0.3576 * g + 0.1805 * b
  const Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const Z = 0.0193 * r + 0.1192 * g + 0.9505 * b
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  return [116 * f(Y) - 16, 500 * (f(X / 0.9505) - f(Y)), 200 * (f(Y) - f(Z / 1.089))]
}

const distance = (a: number[], b: number[]) => {
  const [l1, a1, b1] = lab(a)
  const [l2, a2, b2] = lab(b)
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2)
}

const contrast = (a: number[], b: number[]) => {
  const l = (c: number[]) => 0.2126 * linear(c[0]) + 0.7152 * linear(c[1]) + 0.0722 * linear(c[2])
  const [hi, lo] = [l(a), l(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const SOURCES = ['book', 'yours', 'table', 'invented'] as const

/** The floor the searched palette clears with room to spare. Below about 20 a
 *  pair starts reading as one colour; the palette this replaced sat at 8.8. */
const FLOOR = 25

describe('the four source hues', () => {
  it('every pair stays apart under deuteranopia and protanopia', () => {
    for (const kind of ['deuter', 'protan'] as const) {
      for (let i = 0; i < SOURCES.length; i++) {
        for (let j = i + 1; j < SOURCES.length; j++) {
          const d = distance(simulate(token(SOURCES[i]), kind), simulate(token(SOURCES[j]), kind))
          expect(
            d,
            `${SOURCES[i]} vs ${SOURCES[j]} under ${kind}anopia is dE ${d.toFixed(1)}`,
          ).toBeGreaterThan(FLOOR)
        }
      }
    }
  })

  it('each one is readable on both grounds', () => {
    for (const source of SOURCES) {
      expect(contrast(token(source), token('ground'))).toBeGreaterThan(7)
      expect(contrast(token(source), token('surface'))).toBeGreaterThan(7)
    }
  })

  it('the ink ladder clears the text floor on the surface it sits on', () => {
    // `ink-faint` is the dimmest thing allowed to carry words.
    expect(contrast(token('ink-faint'), token('surface'))).toBeGreaterThan(4.5)
    expect(contrast(token('ink-dim'), token('surface'))).toBeGreaterThan(4.5)
  })
})
