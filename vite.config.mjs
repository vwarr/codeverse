import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tsconfigPaths from 'vite-tsconfig-paths';

// The app lives at https://varunwarrier.com/codeverse/ (that site rewrites /codeverse/* to this
// project), so every URL the browser uses starts with /codeverse/: pages, assets and /codeverse/api/*.
const BASE = '/codeverse/';

// Demo mode (VITE_DEMO) replaces the API and Gemini with a script. It is for local UI work and
// screenshots only: a Vercel build with it set fails, so production never ships the demo.
if (process.env.VITE_DEMO && process.env.VERCEL) {
  throw new Error('VITE_DEMO is set in a Vercel build. Remove it from the project environment.');
}

export default defineConfig({
  base: BASE,
  // Build into dist/codeverse/ so the files exist at /codeverse/... in the deployment (outputDirectory
  // is dist). Vercel serves the filesystem before rewrites, so assets need no rewrite rule.
  build: { outDir: 'dist/codeverse', emptyOutDir: true },
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
