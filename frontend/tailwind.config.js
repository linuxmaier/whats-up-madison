/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: 'var(--c-brand)',
          dark: 'var(--c-brand-dark)',
          light: 'var(--c-brand-light)',
        },
        accent: 'var(--c-accent)',
      },
    },
  },
  plugins: [],
}

