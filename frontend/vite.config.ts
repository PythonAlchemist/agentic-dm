import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

// Two entry points, deliberately. `index.html` is the campaign UI; `lab.html`
// is the agent lab, which has its own React root and shares no component with
// it. Listing both here is what makes the lab survive a production build --
// without it, `vite build` emits only index.html and the lab exists in dev
// alone, which is the sort of thing nobody notices until they deploy.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        lab: resolve(__dirname, 'lab.html'),
      },
    },
  },
})
