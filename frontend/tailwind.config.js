/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                seade: {
                    blue: {
                        primary: '#0066CC',
                        dark: '#003D7A',
                        light: '#4A90E2',
                    },
                    white: '#FFFFFF',
                    gray: {
                        light: '#F5F7FA',
                        medium: '#E1E8ED',
                        dark: '#657786',
                    }
                },
                entity: {
                    person: '#0066CC',
                    org: '#4A90E2',
                    concept: '#7AB8E8',
                    term: '#A8D5F2',
                    location: '#0052A3',
                    date: '#003D7A',
                }
            }
        },
    },
    plugins: [],
}
