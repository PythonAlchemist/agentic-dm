import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import { Lab } from './Lab.tsx'

createRoot(document.getElementById('lab-root')!).render(
  <StrictMode>
    <Lab />
  </StrictMode>,
)
