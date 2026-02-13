import { defineConfig } from 'vitest/config'
import path from 'path'
export default defineConfig({
  test: { globals: true, environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'], exclude: ['node_modules/**', 'node_modules_*/**', '.next/**'], env: { NODE_ENV: 'test' } },
  resolve: { alias: { '@': path.resolve(__dirname, '.') } }
})
