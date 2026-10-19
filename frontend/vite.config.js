import { defineConfig } from 'vite';

const apiTarget = process.env.SPENDWISE_API_TARGET || 'http://127.0.0.1:5001';

export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
