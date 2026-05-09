import { rankStore } from './rankStore'

const STORAGE_KEY = 'poker_votes_v1'

class VoteStore {
  constructor() {
    this.votes = new Map() // uid -> { uid, uname, avatar, vote, votedAt }
    this.listeners = new Set()
    this._loadFromStorage()
  }

  /**
   * 投票
   * @param {number} uid B站用户ID
   * @param {string} uname 用户名
   * @param {string} avatar 头像URL
   * @param {'A'|'B'} vote 投给哪一方
   * @returns {{isNew: boolean, isChanged: boolean, prevVote?: string}} 投票结果状态
   */
  vote(uid, uname, avatar, vote) {
    const prev = this.votes.get(uid)
    const isNew = !prev
    const isChanged = prev ? prev.vote !== vote : true

    this.votes.set(uid, { uid, uname, avatar, vote, votedAt: Date.now() })
    this._saveToStorage()
    this._notify()

    return { isNew, isChanged, prevVote: prev?.vote }
  }

  /** 是否已投票 */
  hasVoted(uid) {
    return this.votes.has(uid)
  }

  /** 获取某用户的投票 */
  getVote(uid) {
    return this.votes.get(uid)?.vote || null
  }

  /** 获取统计信息 */
  getStats() {
    const votersA = []
    const votersB = []
    for (const v of this.votes.values()) {
      if (v.vote === 'A') votersA.push(v)
      else votersB.push(v)
    }
    const total = votersA.length + votersB.length
    return {
      totalA: votersA.length,
      totalB: votersB.length,
      total,
      percentA: total > 0 ? Math.round((votersA.length / total) * 100) : 50,
      percentB: total > 0 ? Math.round((votersB.length / total) * 100) : 50,
      votersA,
      votersB,
    }
  }

  /** 获取最近投票的用户列表（用于头像展示） */
  getRecentVoters(side, limit = 5) {
    const voters = side === 'A'
      ? [...this.votes.values()].filter(v => v.vote === 'A')
      : [...this.votes.values()].filter(v => v.vote === 'B')
    return voters
      .sort((a, b) => b.votedAt - a.votedAt)
      .slice(0, limit)
  }

  /**
   * 结算投票：猜对的用户加分
   * @param {'A'|'B'} winningSide 实际获胜方
   * @returns {{correctUsers: Array, correctCount: number, wrongCount: number}} 结算结果
   */
  settle(winningSide) {
    const stats = this.getStats()
    const correctVoters = winningSide === 'A' ? stats.votersA : stats.votersB
    const wrongVoters = winningSide === 'A' ? stats.votersB : stats.votersA

    correctVoters.forEach(v => {
      rankStore.addCorrect(v.uid, v.uname, v.avatar, 1)
    })

    const result = {
      correctUsers: correctVoters,
      correctCount: correctVoters.length,
      wrongCount: wrongVoters.length,
    }

    // 广播结算事件（供 UI 展示结算结果）
    window.dispatchEvent(new CustomEvent('vote:settled', {
      detail: { winningSide, ...result }
    }))

    return result
  }

  /** 重置所有投票 */
  reset() {
    this.votes.clear()
    this._saveToStorage()
    this._notify()
  }

  /** 订阅统计变化 */
  subscribe(fn) {
    this.listeners.add(fn)
    // 立即推送一次当前状态
    fn(this.getStats())
    return () => this.listeners.delete(fn)
  }

  _notify() {
    const stats = this.getStats()
    this.listeners.forEach(fn => fn(stats))
  }

  _saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...this.votes.values()]))
    } catch (e) {
      console.warn('[VoteStore] localStorage 写入失败:', e)
    }
  }

  _loadFromStorage() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const arr = JSON.parse(raw)
        arr.forEach(v => {
          if (v.uid && v.vote) this.votes.set(v.uid, v)
        })
      }
    } catch (e) {
      console.warn('[VoteStore] localStorage 读取失败:', e)
    }
  }
}

export const voteStore = new VoteStore()
