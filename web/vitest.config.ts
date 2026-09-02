import { defineConfig } from 'vitest/config'
import path from 'node:path'

// The same `@/` the app uses, so a test imports a module by the name the
// application does rather than by a relative path that drifts when a file moves.
export default defineConfig({
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
