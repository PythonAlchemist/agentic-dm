/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // D&D themed colors
        'dnd-red': '#8b0000',
        'dnd-gold': '#d4af37',
        'parchment': '#f5e6c5',
        'parchment-dark': '#e6d5b0',
      },
    },
  },
  plugins: [],
}
