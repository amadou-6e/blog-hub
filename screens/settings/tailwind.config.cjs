const path = require('node:path');

module.exports = {
  content: [path.join(__dirname, 'v1.html'), path.join(__dirname, 'v2.html')],
  theme: {
    extend: {
      colors: {
        surface: '#0f1117', panel: '#181c27', border: '#252a38',
        'border-hi': '#3a3f52', muted: '#5a6080', text: '#c9cfe0',
        bright: '#e8eaf2', accent: '#6366f1',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
};
