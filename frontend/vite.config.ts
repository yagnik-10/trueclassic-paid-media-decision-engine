import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // Pin to :3000 so the dev origin always matches the FastAPI CORS allowlist
      // (http://localhost:3000 / http://127.0.0.1:3000), regardless of how Vite is
      // launched (bare `vite` would otherwise default to 5173).
      port: 3000,
      strictPort: true,
      // Optional escape hatch: set DISABLE_HMR=true to turn off HMR + file
      // watching (handy when an external agent makes rapid edits and the watcher
      // would otherwise thrash). Defaults to normal HMR.
      hmr: process.env.DISABLE_HMR !== 'true',
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
    // `vite preview` must also stay on the CORS-allowed origin.
    preview: { port: 3000, strictPort: true },
  };
});
