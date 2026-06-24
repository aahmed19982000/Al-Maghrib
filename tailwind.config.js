/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./**/templates/**/*.html",
    "./static/**/*.js",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: "#0a1d37",
        secondary: "#146c3c",
        "on-primary": "#ffffff",
        "on-secondary": "#ffffff",
        background: "#f8f9fa",
        surface: "#ffffff",
        outline: "#75777e",
        "outline-variant": "#c5c6ce",
        "on-surface": "#191c1d",
        "on-surface-variant": "#44474d",
        "surface-container-lowest": "#ffffff",
        "surface-container-low": "#f3f4f5",
        error: "#ba1a1a"
      },
      borderRadius: {
        DEFAULT: "4px",
        lg: "4px",
        xl: "8px",
        full: "9999px"
      },
      spacing: {
        "base-unit": "8px",
        "margin-mobile": "16px",
        "container-max-width": "1280px",
        "margin-desktop": "64px",
        gutter: "24px"
      },
      fontFamily: {
        "headline-lg": ["Noto Kufi Arabic"],
        "body-md": ["Noto Kufi Arabic"],
        "headline-md": ["Noto Kufi Arabic"]
      },
      fontSize: {
        "display-lg": ["48px", {lineHeight: "56px", letterSpacing: "-0.02em", fontWeight: "700"}],
        "headline-lg": ["32px", {lineHeight: "40px", fontWeight: "700"}],
        "headline-md": ["24px", {lineHeight: "32px", fontWeight: "600"}],
        "body-md": ["16px", {lineHeight: "24px", fontWeight: "400"}],
        "label-sm": ["12px", {lineHeight: "16px", letterSpacing: "0.05em", fontWeight: "600"}]
      }
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
    require('@tailwindcss/container-queries'),
  ],
}
