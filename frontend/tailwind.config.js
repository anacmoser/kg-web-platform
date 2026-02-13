/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                brand: {
                    primary: '#6366f1', // Indigo
                    secondary: '#4f46e5',
                    accent: '#818cf8',
                    surface: '#0f172a', // Slate 900
                    card: '#1e293b',    // Slate 800
                    muted: '#64748b',   // Slate 500
                },
                seade: {
                    blue: {
                        primary: '#6366f1',
                        dark: '#312e81',
                        light: '#c7d2fe',
                    },
                    white: '#FFFFFF',
                    gray: {
                        light: '#f8fafc',
                        medium: '#e2e8f0',
                        dark: '#475569',
                    }
                },
                entity: {
                    person: '#6366f1',    // Indigo
                    org: '#06b6d4',       // Cyan
                    concept: '#ec4899',   // Pink
                    term: '#f59e0b',      // Amber
                    location: '#10b981',  // Emerald
                    date: '#8b5cf6',      // Violet
                    default: '#94a3b8'
                }
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif'],
                display: ['Outfit', 'Inter', 'system-ui', 'sans-serif'],
            },
            boxShadow: {
                'premium': '0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
                'glass': '0 8px 32px 0 rgba(31, 38, 135, 0.37)',
            }
        },
    },
    plugins: [],
}
