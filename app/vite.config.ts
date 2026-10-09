import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  // Relative asset paths so the build works under a subpath (GitHub Pages).
  base: './',
  // Serve the published pipeline artifacts at / — no copying, no backend.
  // MVP is single-county by spec; multi-county needs a served index instead.
  publicDir: '../data/processed/54081',
});
