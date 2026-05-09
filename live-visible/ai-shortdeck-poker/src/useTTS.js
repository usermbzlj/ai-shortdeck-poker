/**
 * useTTS — 零后端语音合成
 *
 * 策略：
 * 1. Web Speech API（浏览器内置，免费，无需任何服务）
 * 2. MiniMax（通过 Vite dev server 代理，需配置 .env）
 */

let _queue = []
let _speaking = false
let _currentAudio = null
let _provider = 'edge' // 'edge' | 'web' | 'minimax'
let _voicesReady = false
let _voiceList = []

/* ========== 加载语音列表 ========== */

function loadVoices() {
  if (!window.speechSynthesis) return
  const v = window.speechSynthesis.getVoices()
  if (v && v.length > 0) {
    _voiceList = v
    _voicesReady = true
    console.log('[TTS] voices loaded:', v.length, v.map((x) => x.name).join(', '))
  }
}

if (typeof window !== 'undefined' && window.speechSynthesis) {
  loadVoices()
  window.speechSynthesis.onvoiceschanged = loadVoices
}

function waitForVoices(timeout = 3000) {
  return new Promise((resolve) => {
    if (_voicesReady) { resolve(true); return }
    const timer = setInterval(() => {
      loadVoices()
      if (_voicesReady) { clearInterval(timer); resolve(true) }
    }, 200)
    setTimeout(() => { clearInterval(timer); resolve(false) }, timeout)
  })
}

/* ========== Web Speech API ========== */

function pickVoice(speaker) {
  if (!_voiceList.length) return null
  const prefs = {
    'AI-A': ['Xiaoxiao', 'Yunxia', 'Huihui'],
    'AI-B': ['Yunxi', 'Yunjian', 'Kangkang'],
    '系统': ['Yunyang', 'Yaoyao'],
  }
  const keywords = prefs[speaker] || prefs['系统']
  for (const kw of keywords) {
    const v = _voiceList.find((x) => x.name.includes(kw) && x.lang.startsWith('zh'))
    if (v) return v
  }
  const fallback = _voiceList.find((x) => x.lang.startsWith('zh'))
  if (fallback) return fallback
  return _voiceList[0]
}

async function speakWeb(text, speaker) {
  if (!window.speechSynthesis) {
    console.warn('[TTS] speechSynthesis not supported')
    return
  }
  const ok = await waitForVoices()
  if (!ok) {
    console.warn('[TTS] voices not loaded after timeout')
    return
  }

  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text)
    const voice = pickVoice(speaker)
    if (voice) {
      u.voice = voice
      u.lang = voice.lang
    } else {
      u.lang = 'zh-CN'
    }
    u.rate = 1.1
    u.pitch = 1.0
    u.volume = 1.0
    u.onend = () => { console.log('[TTS] ended'); resolve() }
    u.onerror = (e) => { console.warn('[TTS] error:', e.error); resolve() }
    console.log('[TTS] speaking:', text, 'voice:', voice?.name)
    window.speechSynthesis.cancel() // 先清空，避免队列堆积
    window.speechSynthesis.speak(u)
  })
}

/* ========== Edge TTS（本地 Python 服务） ========== */

async function speakEdge(text, speaker) {
  const url = `http://localhost:8000/tts/speak?text=${encodeURIComponent(text)}&speaker=${encodeURIComponent(speaker)}`
  return new Promise((resolve) => {
    _currentAudio = new Audio(url)
    _currentAudio.onended = resolve
    _currentAudio.onerror = () => resolve()
    _currentAudio.play().catch(() => resolve())
  })
}

/* ========== MiniMax（通过 Vite proxy） ========== */

async function speakMiniMax(text, speaker) {
  const voiceMap = {
    'AI-A': 'Chinese (Mandarin)_Crisp_Girl',
    'AI-B': 'Chinese (Mandarin)_Pure-hearted_Boy',
    '系统': 'Chinese (Mandarin)_Male_Announcer',
  }
  const voiceId = voiceMap[speaker] || voiceMap['系统']

  const res = await fetch('/api/tts/minimax', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voiceId }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.error || `MiniMax API ${res.status}`)
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)

  return new Promise((resolve) => {
    _currentAudio = new Audio(url)
    _currentAudio.onended = () => { URL.revokeObjectURL(url); resolve() }
    _currentAudio.onerror = () => { URL.revokeObjectURL(url); resolve() }
    _currentAudio.play().catch(() => resolve())
  })
}

/* ========== 队列播放 ========== */

async function _process() {
  if (_queue.length === 0) {
    _speaking = false
    return
  }
  _speaking = true
  const { text, speaker } = _queue.shift()

  try {
    if (_provider === 'minimax') {
      await speakMiniMax(text, speaker)
    } else if (_provider === 'edge') {
      await speakEdge(text, speaker)
    } else {
      await speakWeb(text, speaker)
    }
  } catch (e) {
    console.warn('[TTS] play failed:', e)
  }

  _process()
}

export function speak(text, speaker = '系统') {
  if (!text) return
  console.log('[TTS] queue:', text, 'provider:', _provider)
  _queue.push({ text, speaker })
  if (!_speaking) _process()
}

export function stop() {
  if (_provider === 'web') {
    window.speechSynthesis?.cancel()
  }
  if (_currentAudio) {
    _currentAudio.pause()
    _currentAudio.currentTime = 0
    _currentAudio = null
  }
  _queue = []
  _speaking = false
}

export function setProvider(p) {
  stop()
  _provider = p
}

export function getProvider() {
  return _provider
}

export function isWebReady() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && _voicesReady
}
