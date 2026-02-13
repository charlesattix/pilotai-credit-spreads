import type { Config } from "tailwindcss"

const config = {
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "#E5E7EB",
        input: "#E5E7EB",
        ring: "#9B6DFF",
        background: "#FAFAFA",
        foreground: "#111827",
        primary: {
          DEFAULT: "#9B6DFF",
          foreground: "#FFFFFF",
        },
        secondary: {
          DEFAULT: "#F3F4F6",
          foreground: "#111827",
        },
        muted: {
          DEFAULT: "#F3F4F6",
          foreground: "#6B7280",
        },
        accent: {
          DEFAULT: "#F3F4F6",
          foreground: "#111827",
        },
        profit: {
          DEFAULT: "#10B981",
          light: "#D1FAE5",
        },
        loss: {
          DEFAULT: "#EF4444",
          light: "#FEE2E2",
        },
        brand: {
          purple: "#9B6DFF",
          pink: "#E84FAD",
          orange: "#F59E42",
        },
        neutral: {
          DEFAULT: "#F59E0B",
          light: "#FEF3C7",
        },
      },
      borderRadius: {
        lg: "16px",
        md: "12px",
        sm: "8px",
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      keyframes: {
        "ticker-scroll": {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
      },
      animation: {
        "ticker-scroll": "ticker-scroll 30s linear infinite",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
      },
      backgroundImage: {
        'gradient-brand': 'linear-gradient(135deg, #9B6DFF 0%, #E84FAD 50%, #F59E42 100%)',
      },
    },
  },
  plugins: [],
} satisfies Config

export default config
