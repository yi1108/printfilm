import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

const legalDocuments: Record<string, { file: string; url: URL }> = {
  '/terms': { file: 'terms.html', url: new URL('./public/terms.html', import.meta.url) },
  '/privacy': { file: 'privacy.html', url: new URL('./public/privacy.html', import.meta.url) },
}

// 开发环境与 nginx 一样直接提供原始法务文件，不进入 React 或鉴权流程。
function serveLegalDocuments(): Plugin {
  return {
    name: 'serve-legal-documents',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const pathname = (req.url || '').split('?', 1)[0]
        const document = legalDocuments[pathname]
        if (!document) {
          next()
          return
        }
        try {
          const html = await readFile(fileURLToPath(document.url), 'utf8')
          res.statusCode = 200
          res.setHeader('Content-Type', 'text/html; charset=utf-8')
          res.end(html)
        } catch {
          next()
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), serveLegalDocuments()],
})
