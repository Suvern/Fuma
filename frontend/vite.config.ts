import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ command, mode, isPreview }) => {
  const localTarget = 'http://127.0.0.1:8000'
  // Only the development proxy needs local configuration. Builds and tests
  // must not load workstation-specific settings or expose them to the client.
  const env = command === 'serve' && !isPreview && mode !== 'test' && mode !== 'local-backend'
    ? loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'FUMA_API_PROXY_TARGET')
    : {}
  const target = env.FUMA_API_PROXY_TARGET?.trim() || localTarget
  let targetUrl: URL
  try {
    targetUrl = new URL(target)
  } catch {
    throw new Error('FUMA_API_PROXY_TARGET must be an HTTP(S) origin, for example https://fuma.example.com')
  }
  if (!['http:', 'https:'].includes(targetUrl.protocol) || targetUrl.username || targetUrl.password
    || targetUrl.pathname !== '/' || targetUrl.search || targetUrl.hash) {
    throw new Error('FUMA_API_PROXY_TARGET must be an HTTP(S) origin without credentials, a path, query, or fragment')
  }
  const targetOrigin = targetUrl.origin
  const remote = targetOrigin !== localTarget

  return {
    envDir: false,
    build: { license: { fileName: 'dependency-licenses.json' } },
    plugins: [react()],
    // API requests stay same-origin; do not expose third-party secrets via VITE_*.
    server: {
      port: 5174,
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
