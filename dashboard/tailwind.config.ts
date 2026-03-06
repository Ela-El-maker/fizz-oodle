import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        surface: "var(--surface)",
        elevated: "var(--elevated)",
        inset: "var(--inset)",
        ink: "var(--ink)",
        "ink-soft": "var(--ink-soft)",
        muted: "var(--muted)",
        "ink-faint": "var(--ink-faint)",
        line: "var(--line)",
        panel: "var(--panel)",
        "panel-border": "var(--panel-border)",
        "panel-soft": "var(--panel-soft)",
        hover: "var(--hover)",
        brand: "var(--brand)",
        accent: "var(--accent)",
        success: "var(--success)",
        warning: "var(--warning)",
        danger: "var(--danger)",
      },
      borderRadius: {
        lg: "12px",
        xl: "16px",
      },
    },
  },
  plugins: [],
};

export default config;
