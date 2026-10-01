/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Every colour resolves from app/static/theme.css, which is THE source
      // of truth for the whole app (server-rendered pages included). It stores
      // each colour as CHANNELS ("0 229 160"), which is what lets Tailwind's
      // /alpha modifiers (bg-accent/15, border-border/70, ...) keep working
      // through a var(). A bare var(--accent) would break every one of them
      // silently. index.html links theme.css so these resolve at runtime.
      colors: {
        bg: {
          DEFAULT:  "rgb(var(--bg-rgb) / <alpha-value>)",
          card:     "rgb(var(--surf-1-rgb) / <alpha-value>)",
          elevated: "rgb(var(--surf-2-rgb) / <alpha-value>)",
          hover:    "rgb(var(--surf-3-rgb) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--edge-rgb) / <alpha-value>)",
          subtle:  "rgb(var(--edge-soft-rgb) / <alpha-value>)",
        },
        text: {
          DEFAULT: "rgb(var(--tx-rgb) / <alpha-value>)",
          // Both map to --tx-mut (#8a92ab, ~6:1). text.dim is the eyebrow /
          // label colour on 224 sites and was deliberately RAISED from
          // #4a5170 for WCAG AA; --tx-dim is darker and must not be used
          // here or that fix is undone. text.muted brightens slightly from
          // #7a8399, which is the same AA correction.
          muted:   "rgb(var(--tx-mut-rgb) / <alpha-value>)",
          dim:     "rgb(var(--tx-mut-rgb) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent-rgb) / <alpha-value>)",
          // The accent now varies per tool (theme.py PER_APP_ACCENT), so a
          // fixed brighter hover hue would clash on blue/violet/sand pages.
          // One site used this.
          hover:   "rgb(var(--accent-rgb) / <alpha-value>)",
          dim:     "rgb(var(--accent-dim-rgb) / <alpha-value>)",
        },
        warn:  "rgb(var(--mid-rgb) / <alpha-value>)",
        error: "rgb(var(--bad-rgb) / <alpha-value>)",

        // Position hues (data). WR/TE/RB are LOCKED to the Aethersight
        // legend in app/trinity_viewer.py. The accent is deliberately NOT in
        // this set: it is chrome only, so "interactive" never reads as
        // "quarterback".
        pos: {
          qb: "rgb(var(--qb-rgb) / <alpha-value>)",
          rb: "rgb(var(--rb-rgb) / <alpha-value>)",
          wr: "rgb(var(--wr-rgb) / <alpha-value>)",
          te: "rgb(var(--te-rgb) / <alpha-value>)",
          dl: "rgb(var(--dl-rgb) / <alpha-value>)",
          dt: "rgb(var(--dt-rgb) / <alpha-value>)",
          lb: "rgb(var(--lb-rgb) / <alpha-value>)",
          db: "rgb(var(--db-rgb) / <alpha-value>)",
          s:  "rgb(var(--s-rgb) / <alpha-value>)",
        },
        good: "rgb(var(--good-rgb) / <alpha-value>)",
        mid:  "rgb(var(--mid-rgb) / <alpha-value>)",
        bad:  "rgb(var(--bad-rgb) / <alpha-value>)",
        info: "rgb(var(--info-rgb) / <alpha-value>)",
        div: {
          neg: "rgb(var(--div-neg-rgb) / <alpha-value>)",
          pos: "rgb(var(--div-pos-rgb) / <alpha-value>)",
        },
        "accent-ink": "rgb(var(--accent-ink-rgb) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
