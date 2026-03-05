/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-outfit)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        canvas: '#f7f7f5',
        surface: {
          DEFAULT: '#ffffff',
          raised: '#fafaf8',
          sunken: '#f0efeb',
          border: '#e5e3de',
        },
        ink: {
          DEFAULT: '#1c1917',
          secondary: '#6b6560',
          tertiary: '#a39e99',
          inverse: '#fafaf8',
        },
        accent: {
          DEFAULT: '#4a5abb',
          light: '#eef0fb',
          hover: '#3d4ea6',
          muted: '#8b95d4',
        },
      },
      boxShadow: {
        'soft': '0 1px 3px rgba(28, 25, 23, 0.05), 0 1px 2px rgba(28, 25, 23, 0.03)',
        'lifted': '0 4px 16px rgba(28, 25, 23, 0.07), 0 1px 3px rgba(28, 25, 23, 0.04)',
        'overlay': '0 16px 48px rgba(28, 25, 23, 0.12), 0 4px 12px rgba(28, 25, 23, 0.06)',
      },
      borderRadius: {
        'xl': '0.875rem',
        '2xl': '1.125rem',
      },
      keyframes: {
        'skeleton-pulse': {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '0.7' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
      animation: {
        'skeleton': 'skeleton-pulse 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        'fade-in': 'fade-in 0.2s ease-out',
      },
    },
  },
  plugins: [],
}
