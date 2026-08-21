import react from "@vitejs/plugin-react";
import path from "node:path";
import { configDefaults, defineConfig } from "vitest/config";

/**
 * Frontend test infrastructure. Vitest + React Testing Library was chosen
 * as the minimal, standard pairing for a Next.js/React app: no custom
 * babel/webpack config to fight, and it reuses the same `@/*` path alias
 * already configured in `tsconfig.json`. See `docs/testing_strategy.md`
 * for how this fits the wider test strategy.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // frontend/e2e/**/*.spec.ts are Playwright specs (run via `npm run
    // test:e2e`, real @playwright/test globals) — vitest's default
    // include pattern would otherwise also match them and fail with
    // "test is not defined"-style errors.
    exclude: [...configDefaults.exclude, "e2e/**"],
    // Base UI popup components (Select/Dialog/Menu) plus userEvent's
    // realistic interaction simulation are consistently slower than the
    // 5s default under jsdom — bumped rather than leaving tests flaky.
    testTimeout: 15_000,
  },
});
