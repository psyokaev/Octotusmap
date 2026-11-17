/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: { sans: ['"Google Sans"', 'Roboto', 'Arial', 'sans-serif'] },
      colors: {
        ink: { DEFAULT: '#0E2A3B', 2: '#163A50', 3: '#24506B' },
        water: { DEFAULT: '#1C7CB5', light: '#D6EAF5' },
        paper: '#F5F8FA',
        risk: { low: '#2E8B57', medium: '#D99A00', high: '#C62828', none: '#8A949C' },
      },
    },
  },
  plugins: [],
}
