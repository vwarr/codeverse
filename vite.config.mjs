import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig({
  // Set VITE_BASE when hosting under a sub-path, e.g. VITE_BASE=/codeverse/.
  base: process.env.VITE_BASE ?? '/',
  plugins: [react(), tsconfigPaths()],
  // `vercel dev` copies the repo into .vercel/cache to build the Python functions.
  server: { watch: { ignored: ['**/.vercel/**', '**/backend/**', '**/api/**'] } },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './vitest.setup.mjs',
    exclude: [...configDefaults.exclude, '**/.vercel/**'],
  },
});
