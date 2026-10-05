import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config.ts";

export default defineConfig((env) => mergeConfig(
  viteConfig(env),
  defineConfig({
    test: { setupFiles: ["./src/test/setup.ts"] },
  }),
));
