/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          blue: "#072f5fe8",
          green: "#059669",
        },
        surface: "#F5F7FA",
        border: "#E2E8F0",
        ink: "#172B3A",
        muted: "#64748B",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        subtle: "0 1px 2px rgb(15 23 42 / 0.06)",
      },
    },
  },
  plugins: [],
};
