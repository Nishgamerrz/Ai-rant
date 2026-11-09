/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#09090b",
        panel: "#121214",
        card: "#18181b",
        "card-hover": "#1f1f23",
        line: "#27272a",
        "line-strong": "#3f3f46",
        muted: "#71717a",
        "muted-strong": "#a1a1aa",
        accent: "#7c3aed",
        "accent-hover": "#6d28d9",
        good: "#10b981",
        warn: "#f59e0b",
        bad: "#ef4444",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1rem",
        "3xl": "1.5rem",
      },
      boxShadow: {
        soft: "0 2px 10px rgba(0,0,0,0.2), 0 0 0 1px rgba(255,255,255,0.04)",
        medium: "0 8px 30px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.06)",
        large: "0 20px 60px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.08)",
      },
      animation: {
        "pulse-subtle": "pulse-subtle 1.8s ease-in-out infinite",
        slideIn: "slideIn 0.2s ease-out",
      },
    },
  },
  plugins: [],
};
