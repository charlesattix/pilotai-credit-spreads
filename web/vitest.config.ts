import { defineConfig } from 'vitest/config'
import path from 'path'
export default defineConfig({
  test: { globals: true, environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['tests/**/*.test.ts'], exclude: ['node_modules/**', 'node_modules_*/**', '.next/**'] },
  resolve: { alias: { '@': path.resolve(__dirname, '.') } }
})
