import https from 'node:https'
import zlib from 'node:zlib'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// WBI sign mixin table
const WBI_MixinKeyEncTab = [
  46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
  27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
  37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
  22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]

function getMixinKey(orig) {
  let s = ''
  WBI_MixinKeyEncTab.forEach(i => { s += orig[i] })
  return s.slice(0, 32)
}

function wbiSign(params, imgKey, subKey) {
  const mixinKey = getMixinKey(imgKey + subKey)
  const wts = Math.floor(Date.now() / 1000)
  const filter = /[!'()*]/g
  Object.assign(params, { wts })
  const sorted = Object.keys(params).sort()
  const query = sorted.map(k => {
    const v = params[k].toString().replace(filter, '')
    return `${encodeURIComponent(k)}=${encodeURIComponent(v)}`
  }).join('&')
  const w_rid = createHash('md5').update(query + mixinKey).digest('hex')
  return `${query}&w_rid=${w_rid}`
}

function getCookie() {
  try {
    const cfg = JSON.parse(readFileSync(join(__dirname, 'public', 'config.json'), 'utf8'))
    return cfg.cookie || ''
  } catch {
    return ''
  }
}

function fetchJson(url, cookie) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://live.bilibili.com',
        'Origin': 'https://live.bilibili.com',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        ...(cookie ? { 'Cookie': cookie } : {})
      }
    }, (res) => {
      let chunks = []
      res.on('data', chunk => chunks.push(chunk))
      res.on('end', () => {
        const buffer = Buffer.concat(chunks)
        const encoding = res.headers['content-encoding']
        let data = buffer
        try {
          if (encoding === 'gzip') data = zlib.gunzipSync(buffer)
          else if (encoding === 'deflate') data = zlib.inflateSync(buffer)
          else if (encoding === 'br') data = zlib.brotliDecompressSync(buffer)
        } catch {}
        try { resolve(JSON.parse(data.toString())) } catch { reject(data.toString().slice(0, 200)) }
      })
    })
    req.on('error', reject)
    req.setTimeout(15000, () => { req.destroy(); reject(new Error('Timeout')) })
  })
}

async function getWbiKeys(cookie) {
  const res = await fetchJson('https://api.bilibili.com/x/web-interface/nav', cookie)
  if (res.code !== 0 && !res.data?.wbi_img) {
    throw new Error('Failed to get WBI keys: ' + JSON.stringify(res))
  }
  const img = res.data.wbi_img.img_url
  const sub = res.data.wbi_img.sub_url
  const imgKey = img.slice(img.lastIndexOf('/') + 1, img.lastIndexOf('.'))
  const subKey = sub.slice(sub.lastIndexOf('/') + 1, sub.lastIndexOf('.'))
  return { imgKey, subKey }
}

async function getDanmuAuth(roomId, cookie) {
  // 1. Get buvid3 from spi first (required to avoid -352)
  let buvid3 = ''
  try {
    const spiRes = await fetchJson('https://api.bilibili.com/x/frontend/finger/spi', cookie)
    console.log('[bili-proxy] spi res:', spiRes.code, spiRes.data?.b_3?.slice(0, 20))
    if (spiRes.code === 0) buvid3 = spiRes.data.b_3
  } catch (e) {
    console.warn('[bili-proxy] spi warning:', e.message)
  }

  // Build full cookie with buvid3
  const fullCookie = cookie + (buvid3 ? `; buvid3=${buvid3}` : '')
  console.log('[bili-proxy] fullCookie length:', fullCookie.length)

  // 2. Get real uid from nav API (uid=0 is now rejected by B站)
  let uid = 0
  try {
    const navRes = await fetchJson('https://api.bilibili.com/x/web-interface/nav', fullCookie)
    if (navRes.code === 0 && navRes.data?.isLogin) {
      uid = navRes.data.mid || 0
      console.log('[bili-proxy] uid from nav:', uid)
    }
  } catch (e) {
    console.warn('[bili-proxy] nav warning:', e.message)
  }

  // 3. mobileRoomInit
  const initRes = await fetchJson(`https://api.live.bilibili.com/room/v1/Room/mobileRoomInit?id=${roomId}`, fullCookie)
  console.log('[bili-proxy] initRes code:', initRes.code)
  if (initRes.code !== 0) {
    throw new Error('mobileRoomInit failed: ' + JSON.stringify(initRes))
  }
  const realRoomId = initRes.data.room_id

  // 4. WBI keys (no cache to avoid stale keys)
  const { imgKey, subKey } = await getWbiKeys(fullCookie)
  console.log('[bili-proxy] wbi keys:', imgKey.slice(0, 8), subKey.slice(0, 8))

  // 5. getDanmuInfo with WBI sign
  const signed = wbiSign({ id: realRoomId, type: 0 }, imgKey, subKey)
  console.log('[bili-proxy] signed:', signed)
  const danmuRes = await fetchJson('https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo?' + signed, fullCookie)
  console.log('[bili-proxy] danmuRes code:', danmuRes.code)
  if (danmuRes.code !== 0) {
    throw new Error('getDanmuInfo failed: ' + JSON.stringify(danmuRes))
  }

  const host = danmuRes.data.host_list?.[0]

  return {
    code: 0,
    data: {
      roomId: realRoomId,
      token: danmuRes.data.token,
      buvid: buvid3,
      uid: uid,
      host: host?.host,
      port: host?.wss_port || host?.port || 2245,
      wsPort: host?.ws_port || 2244
    }
  }
}

function registerMiddleware(serverOrPreview) {
  serverOrPreview.middlewares.use('/api/bili/auth', async (req, res, next) => {
    if (req.method !== 'GET') return next()
    const url = new URL(req.url, `http://${req.headers.host}`)
    const roomId = url.searchParams.get('roomId')
    if (!roomId) {
      res.statusCode = 400
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ code: -1, message: 'roomId required' }))
      return
    }
    try {
      const cookie = getCookie()
      const result = await getDanmuAuth(roomId, cookie)
      res.statusCode = 200
      res.setHeader('Content-Type', 'application/json')
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.end(JSON.stringify(result))
    } catch (err) {
      console.error('[bili-proxy] auth error:', err.message)
      res.statusCode = 500
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ code: -1, message: err.message }))
    }
  })

  serverOrPreview.middlewares.use('/api/bili/user', async (req, res, next) => {
    if (req.method !== 'GET') return next()
    const url = new URL(req.url, `http://${req.headers.host}`)
    const uid = url.searchParams.get('uid')
    if (!uid) {
      res.statusCode = 400
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ code: -1, message: 'uid required' }))
      return
    }
    try {
      const cookie = getCookie()
      const userRes = await fetchJson(`https://api.bilibili.com/x/web-interface/card?mid=${uid}&photo=true`, cookie)
      const face = userRes.data?.card?.face || ''
      res.statusCode = 200
      res.setHeader('Content-Type', 'application/json')
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.end(JSON.stringify({ code: 0, data: { uid: Number(uid), face } }))
    } catch (err) {
      console.error('[bili-proxy] user error:', err.message)
      res.statusCode = 500
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ code: -1, message: err.message }))
    }
  })
}

export default function biliProxyPlugin() {
  return {
    name: 'bili-proxy',
    configureServer(server) {
      registerMiddleware(server)
    },
    configurePreviewServer(server) {
      registerMiddleware(server)
    }
  }
}
