import { defineConfig } from 'vitest/config'
import path from 'path'

const reactPath = path.resolve(__dirname, 'node_modules/react')
const reactDomPath = path.resolve(__dirname, 'node_modules/react-dom')

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    exclude: ['node_modules/**', 'node_modules_*/**', '.next/**'],
    env: { NODE_ENV: 'test' },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary', 'lcov'],
      exclude: ['node_modules/', '.next/', 'tests/', '*.config.*'],
      thresholds: { lines: 50, functions: 50, branches: 40, statements: 50 },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
      'react': reactPath,
      'react-dom': reactDomPath,
      'react/jsx-runtime': path.join(reactPath, 'jsx-runtime'),
      'react/jsx-dev-runtime': path.join(reactPath, 'jsx-dev-runtime'),
      'react-dom/client': path.join(reactDomPath, 'client'),
    },
  },
})
