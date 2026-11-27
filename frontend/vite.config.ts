import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] })],
  server: {
    proxy: {
      '/api': 'http://localhost:8001',
      // The coach endpoint and the OAuth endpoints an assistant calls. Not
      // all of /oauth: the approval page (/oauth/consent) is this app's own.
      '/mcp': 'http://localhost:8001',
      '/oauth/authorize': 'http://localhost:8001',
      '/oauth/token': 'http://localhost:8001',
      '/.well-known': 'http://localhost:8001',
    },
  },
})
