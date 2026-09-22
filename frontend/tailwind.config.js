/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        term: {
          bg: "#0a0e0c",
          panel: "#0f1512",
          border: "#1f2b24",
          green: "#39ff88",
          greendim: "#1f9e56",
          amber: "#ffb84d",
          red: "#ff5c5c",
          text: "#c9d6cf",
          dim: "#5c6b63",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
