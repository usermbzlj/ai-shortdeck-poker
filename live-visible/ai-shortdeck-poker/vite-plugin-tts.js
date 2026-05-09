/**
 * Vite Plugin: TTS Proxy
 *
 * 在 dev server 中内置 MiniMax TTS 代理，无需单独启动后端服务。
 * 读取项目根目录 .env 文件中的 MINIMAX_API_KEY / MINIMAX_GROUP_ID。
 */

import fs from 'fs'
import path from 'path'

function loadEnv(root) {
  const envPath = path.resolve(root, '.env')
  const env = {}
  if (fs.existsSync(envPath)) {
    const text = fs.readFileSync(envPath, 'utf-8')
    for (const line of text.split('\n')) {
      const [k, ...v] = line.split('=')
      if (k && v.length > 0) {
        env[k.trim()] = v.join('=').trim()
      }
    }
  }
  return env
}

export default function ttsProxy() {
  return {
    name: 'vite-plugin-tts',
    configureServer(server) {
      const env = loadEnv(process.cwd())
      const API_KEY = env.MINIMAX_API_KEY || process.env.MINIMAX_API_KEY || ''
      const GROUP_ID = env.MINIMAX_GROUP_ID || process.env.MINIMAX_GROUP_ID || ''
      const MODEL = env.MINIMAX_MODEL || 'speech-2.8-hd'
      const BASE_URL = env.MINIMAX_BASE_URL || 'https://api.minimax.io/v1/t2a_v2'

      server.middlewares.use('/api/tts/minimax', async (req, res, next) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end('Method Not Allowed')
          return
        }

        console.log('[MiniMax Proxy] API_KEY loaded:', API_KEY ? `${API_KEY.slice(0, 8)}...${API_KEY.slice(-4)}` : 'MISSING')
        console.log('[MiniMax Proxy] GROUP_ID loaded:', GROUP_ID || 'MISSING')

        if (!API_KEY || !GROUP_ID) {
          res.statusCode = 503
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: 'MINIMAX_API_KEY / MINIMAX_GROUP_ID not configured. Create a .env file in project root.' }))
          return
        }

        // 读取请求体
        let body = ''
        for await (const chunk of req) body += chunk
        const { text, voiceId } = JSON.parse(body || '{}')

        const payload = {
          model: MODEL,
          text: text || '',
          stream: false,
          output_format: 'hex',
          voice_setting: {
            voice_id: voiceId || 'Chinese (Mandarin)_Crisp_Girl',
            speed: 1,
            vol: 1,
            pitch: 0,
          },
          audio_setting: {
            sample_rate: 32000,
            bitrate: 128000,
            format: 'mp3',
            channel: 1,
          },
        }

        try {
          const fetchRes = await fetch(`${BASE_URL}?GroupId=${GROUP_ID}`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${API_KEY}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
          })

          const data = await fetchRes.json()
          const baseResp = data.base_resp || {}

          if (baseResp.status_code !== 0) {
            res.statusCode = 502
            res.setHeader('Content-Type', 'application/json')
            res.end(JSON.stringify({ error: baseResp.status_msg || 'MiniMax error' }))
            return
          }

          const audioHex = data.data?.audio
          if (!audioHex) {
            res.statusCode = 502
            res.end(JSON.stringify({ error: 'No audio data' }))
            return
          }

          const audioBuf = Buffer.from(audioHex, 'hex')
          res.setHeader('Content-Type', 'audio/mpeg')
          res.setHeader('Content-Length', audioBuf.length)
          res.end(audioBuf)
        } catch (err) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: err.message }))
        }
      })
    },
  }
}
