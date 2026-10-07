/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js"
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Cinematic Dark Theme Colors
        background: 'hsl(240 10% 4%)',
        foreground: 'hsl(0 0% 98%)',
        
        card: 'hsl(240 10% 7%)',
        'card-foreground': 'hsl(0 0% 98%)',
        
        popover: 'hsl(240 10% 5%)',
        'popover-foreground': 'hsl(0 0% 98%)',
        
        primary: {
          DEFAULT: 'hsl(270 70% 60%)',
          foreground: 'hsl(0 0% 100%)',
        },
        
        secondary: {
          DEFAULT: 'hsl(240 5% 15%)',
          foreground: 'hsl(0 0% 98%)',
        },
        
        muted: {
          DEFAULT: 'hsl(240 5% 15%)',
          foreground: 'hsl(240 5% 65%)',
        },
        
        accent: {
          DEFAULT: 'hsl(320 80% 60%)',
          foreground: 'hsl(0 0% 100%)',
        },
        
        destructive: {
          DEFAULT: 'hsl(0 62% 30%)',
          foreground: 'hsl(0 0% 98%)',
        },
        
        border: 'hsl(240 5% 15%)',
        input: 'hsl(240 5% 15%)',
        ring: 'hsl(270 70% 60%)',
        
        sidebar: {
          DEFAULT: 'hsl(240 10% 3%)',
          foreground: 'hsl(240 5% 90%)',
          primary: 'hsl(270 70% 60%)',
          'primary-foreground': 'hsl(0 0% 100%)',
          accent: 'hsl(240 5% 15%)',
          'accent-foreground': 'hsl(0 0% 98%)',
          border: 'hsl(240 5% 10%)',
          ring: 'hsl(270 70% 60%)',
        },
      },
      fontFamily: {
        sans: ['Outfit', 'Inter', 'system-ui', 'sans-serif'],
        display: ['Outfit', 'sans-serif'],
      },
      borderRadius: {
        lg: '0.75rem',
        md: 'calc(0.75rem - 2px)',
        sm: 'calc(0.75rem - 4px)',
        xl: 'calc(0.75rem + 4px)',
      },
      keyframes: {
        'shimmer': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        'pulse-glow': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
        'slide-up': {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'slide-down': {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'scale-in': {
          '0%': { transform: 'scale(0.95)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
      },
      animation: {
        'shimmer': 'shimmer 2s infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.5s ease-out',
        'slide-down': 'slide-down 0.5s ease-out',
        'fade-in': 'fade-in 0.5s ease-out',
        'scale-in': 'scale-in 0.3s ease-out',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
      },
    },
  },
  plugins: [],
}

