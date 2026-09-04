import { defineConfig } from 'vitest/config'
import path from 'node:path'

// The same `@/` the app uses, so a test imports a module by the name the
// application does rather than by a relative path that drifts when a file moves.
export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  // Component tests opt into a DOM per file with `// @vitest-environment jsdom`.
  // The default stays `node`: the decisions in `lib/` are where the tests live,
  // and paying for a DOM to assert on a pure function is a tax on every run.
  test: { environment: 'node', include: ['src/**/*.test.{ts,tsx}'] },
})
