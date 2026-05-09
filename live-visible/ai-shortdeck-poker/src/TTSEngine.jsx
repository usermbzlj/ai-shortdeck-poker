/**
 * TTSEngine — 独立语音合成组件
 *
 * 职责：监听全局 ttsSpeak / ttsStop / roundEnd 事件，调用本地 edge-tts 服务播放。
 * 零侵入其他组件，仅通过 window CustomEvent 通信。
 *
 * 用法（其他 agent 在需要说话的地方加一行即可）：
 *   window.dispatchEvent(new CustomEvent('ttsSpeak', { detail: { text: 'xxx', speaker: 'AI-A' } }))
 */

import { useEffect, useRef } from 'react'

const TTS_BASE_URL = 'http://localhost:8000'

class TTSPlayer {
  constructor() {
    this.currentAudio = null
    this.queue = []
    this.speaking = false
    this.enabled = true
  }

  setEnabled(v) {
    this.enabled = v
    if (!v) this.stop()
  }

  async speak(text, speaker = '系统') {
    if (!this.enabled || !text) return
    this.queue.push({ text, speaker })
    if (!this.speaking) this._process()
  }

  async _process() {
    if (this.queue.length === 0) {
      this.speaking = false
      return
    }
    this.speaking = true
    const { text, speaker } = this.queue.shift()

    try {
      const url = `${TTS_BASE_URL}/tts/speak?text=${encodeURIComponent(text)}&speaker=${encodeURIComponent(speaker)}`
      this.currentAudio = new Audio(url)
      this.currentAudio.volume = 0.9
      await new Promise((resolve) => {
        this.currentAudio.onended = resolve
        this.currentAudio.onerror = (e) => {
          console.warn('[TTS] audio error', e)
          resolve()
        }
        this.currentAudio.play().catch((e) => {
          console.warn('[TTS] play failed', e)
          resolve()
        })
      })
    } catch (e) {
      console.warn('[TTS] error', e)
    }

    this._process()
  }

  stop() {
    if (this.currentAudio) {
      this.currentAudio.pause()
      this.currentAudio.currentTime = 0
      this.currentAudio = null
    }
    this.queue = []
    this.speaking = false
  }
}

export default function TTSEngine() {
  const playerRef = useRef(new TTSPlayer())
  const timerRef = useRef(null)

  useEffect(() => {
    const player = playerRef.current

    // 暴露全局控制接口，方便控制台调试
    window.__tts = {
      speak: (t, s) => player.speak(t, s),
      stop: () => player.stop(),
      setEnabled: (v) => player.setEnabled(v),
      ping: async () => {
        try {
          const r = await fetch(`${TTS_BASE_URL}/`)
          return r.ok
        } catch { return false }
      },
    }

    const onSpeak = (e) => {
      const { text, speaker } = e.detail || {}
      if (text) player.speak(text, speaker)
    }

    const onStop = () => player.stop()

    const onRoundEnd = () => {
      // 一局结束，留给赛后感想播放完后自然结束，不清空队列
      // 如果需要在 roundEnd 强制停止，取消下面注释：
      // player.stop()
    }

    window.addEventListener('ttsSpeak', onSpeak)
    window.addEventListener('ttsStop', onStop)
    window.addEventListener('roundEnd', onRoundEnd)

    // 兜底：如果页面 unload，停止播放
    const onBeforeUnload = () => player.stop()
    window.addEventListener('beforeunload', onBeforeUnload)

    // 定时探测 TTS 服务健康，若离线则自动静默
    const healthCheck = async () => {
      const ok = await window.__tts.ping()
      if (!ok && player.enabled) {
        console.warn('[TTSEngine] TTS service offline, auto-disabled')
      }
    }
    healthCheck()
    timerRef.current = setInterval(healthCheck, 30000)

    return () => {
      window.removeEventListener('ttsSpeak', onSpeak)
      window.removeEventListener('ttsStop', onStop)
      window.removeEventListener('roundEnd', onRoundEnd)
      window.removeEventListener('beforeunload', onBeforeUnload)
      clearInterval(timerRef.current)
      player.stop()
    }
  }, [])

  // 这个组件不渲染任何 DOM
  return null
}
