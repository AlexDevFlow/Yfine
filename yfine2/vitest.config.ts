import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

// Dedicated vitest config: node environment, no Tauri/Tailwind plugins. Vite's
// core still handles `?raw` and JSON imports used by the migration code.
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
