import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig(({ mode }) => {
  const remote = mode !== 'local-backend'
  const target = remote
    ? process.env.FUMA_API_PROXY_TARGET || 'https://fuma.joice.tech'
    : 'http://127.0.0.1:8000'
  const targetOrigin = new URL(target).origin

  return {
    envDir: false,
    plugins: [react()],
    // API requests stay same-origin; do not expose third-party secrets via VITE_*.
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target,
          changeOrigin: remote,
          cookieDomainRewrite: '',
          configure(proxy) {
            if (!remote) return

            proxy.on('proxyReq', (proxyReq, req) => {
              // The backend validates Origin in addition to the CSRF token.
              if (req.headers.origin === `http://${req.headers.host}`) {
                proxyReq.setHeader('origin', targetOrigin)
              }
              if (req.headers.cookie) {
                proxyReq.setHeader('cookie', req.headers.cookie.replace(
                  /(^|;\s*)fuma_dev_session=/g, '$1__Host-fuma_session=',
                ))
              }
            })
            proxy.on('proxyRes', (proxyRes) => {
              // __Host- cookies require HTTPS. Translate only the remote session
              // cookie for this loopback HTTP server, retaining HttpOnly/SameSite.
              const cookies = proxyRes.headers['set-cookie']
              if (cookies) {
                proxyRes.headers['set-cookie'] = cookies.map((cookie) =>
                  cookie.startsWith('__Host-fuma_session=')
                    ? cookie.replace(/^__Host-fuma_session=/, 'fuma_dev_session=')
                      .replace(/;\s*Secure\b/gi, '')
                    : cookie,
                )
              }
            })
          },
        },
      },
    },
  }
})
