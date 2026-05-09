/**
 * TTS Client - connects to local edge-tts FastAPI service
 * Auto-queues audio to prevent overlapping playback.
 */

const TTS_BASE_URL = 'http://localhost:8000'

class TTSClient {
  constructor() {
    this.currentAudio = null
    this.queue = []
    this.speaking = false
    this.enabled = true
  }

  /** Toggle TTS on/off */
  setEnabled(val) {
    this.enabled = val
    if (!val) this.stop()
  }

  /** Queue a line to speak. Auto-selects voice by speaker name. */
  async speak(text, speaker) {
    if (!this.enabled || !text || !speaker) return
    this.queue.push({ text, speaker })
    if (!this.speaking) this._processQueue()
  }

  async _processQueue() {
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
          console.warn('[TTS] audio error:', e)
          resolve() // don't block queue on error
        }
        this.currentAudio.play().catch((e) => {
          console.warn('[TTS] play failed:', e)
          resolve()
        })
      })
    } catch (e) {
      console.warn('[TTS] request failed:', e)
    }

    this._processQueue()
  }

  /** Stop current audio and clear queue */
  stop() {
    if (this.currentAudio) {
      this.currentAudio.pause()
      this.currentAudio.currentTime = 0
      this.currentAudio = null
    }
    this.queue = []
    this.speaking = false
  }

  /** Quick health-check */
  async ping() {
    try {
      const res = await fetch(`${TTS_BASE_URL}/`)
      return res.ok
    } catch {
      return false
    }
  }
}

export const tts = new TTSClient()
