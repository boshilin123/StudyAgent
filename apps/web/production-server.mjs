import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { Readable } from 'node:stream'

const port = Number(process.env.PORT || 8080)
const apiTarget = process.env.API_PROXY_TARGET || 'http://api:8000'
const staticRoot = resolve('dist')
const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.gif': 'image/gif',
  '.html': 'text/html; charset=utf-8',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
}

function safeStaticPath(pathname) {
  const candidate = resolve(staticRoot, `.${pathname}`)
  return candidate === staticRoot || candidate.startsWith(`${staticRoot}${sep}`) ? candidate : null
}

function sendFile(response, filePath) {
  const extension = extname(filePath).toLowerCase()
  response.statusCode = 200
  response.setHeader('Content-Type', contentTypes[extension] || 'application/octet-stream')
  if (extension !== '.html') {
    response.setHeader('Cache-Control', 'public, max-age=604800, immutable')
  } else {
    response.setHeader('Cache-Control', 'no-cache')
  }
  createReadStream(filePath).pipe(response)
}

async function proxyApi(request, response) {
  const headers = { ...request.headers }
  delete headers.host
  delete headers.connection
  const hasBody = !['GET', 'HEAD'].includes(request.method || 'GET')
  const upstream = await fetch(`${apiTarget}${request.url}`, {
    method: request.method,
    headers,
    body: hasBody ? request : undefined,
    duplex: hasBody ? 'half' : undefined,
    redirect: 'manual',
  })
  response.statusCode = upstream.status
  for (const [name, value] of upstream.headers) {
    if (!['connection', 'keep-alive', 'transfer-encoding'].includes(name.toLowerCase())) {
      response.setHeader(name, value)
    }
  }
  if (upstream.body) Readable.fromWeb(upstream.body).pipe(response)
  else response.end()
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || '/', 'http://localhost')
    if (url.pathname === '/healthz') {
      response.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' })
      response.end('ok\n')
      return
    }
    if (url.pathname.startsWith('/api/')) {
      await proxyApi(request, response)
      return
    }
    const filePath = safeStaticPath(decodeURIComponent(url.pathname))
    if (filePath && existsSync(filePath) && statSync(filePath).isFile()) {
      sendFile(response, filePath)
      return
    }
    sendFile(response, resolve(staticRoot, 'index.html'))
  } catch (error) {
    response.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
    response.end(JSON.stringify({ error: { code: 'WEB_PROXY_ERROR', message: '服务暂不可用' } }))
    console.error(error)
  }
})

server.listen(port, '0.0.0.0', () => {
  console.log(`StudyAgent Web listening on 0.0.0.0:${port}`)
})

