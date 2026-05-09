import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import ttsProxy from './vite-plugin-tts.js'
import biliProxy from './vite-plugin-bili-proxy.js'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), ttsProxy(), biliProxy()],
  server: {
    allowedHosts: ['shortdeck-pocker.leisure.xin'],
    proxy: {
      '/bili-api': {
        target: 'https://api.live.bilibili.com',
        changeOrigin: true,
        secure: false,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq, req, res) => {
            proxyReq.setHeader('Referer', 'https://live.bilibili.com')
            proxyReq.setHeader('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
          })
        },
        rewrite: (path) => path.replace(/^\/bili-api/, ''),
      },
    },
  }
})