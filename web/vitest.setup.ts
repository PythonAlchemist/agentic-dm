import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Component tests each mount into a fresh document via `// @vitest-environment
// jsdom`, but nothing unmounts between `it` blocks in the same file unless
// something asks it to. `@testing-library/react` only wires this up itself
// when it finds a global `afterEach` -- which requires `test.globals: true`,
// off here so a `node`-environment test isn't tripped by ambient DOM matchers.
// Wiring it explicitly, once, keeps every component test file isolated
// without turning on globals project-wide.
afterEach(() => {
  cleanup()
})
