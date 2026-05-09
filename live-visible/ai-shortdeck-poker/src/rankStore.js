const STORAGE_KEY = 'poker_rank_v1'

class RankStore {
  constructor() {
    this.ranks = new Map() // uid -> { uid, uname, avatar, correct }
    this.listeners = new Set()
    this._loadFromStorage()
  }

  /**
   * 增加用户猜对次数
   * @param {number} uid
   * @param {string} uname
   * @param {string} avatar
   * @param {number} count 默认加 1
   */
  addCorrect(uid, uname, avatar, count = 1) {
    const prev = this.ranks.get(uid)
    if (prev) {
      prev.correct += count
      // 更新名称和头像（可能变了）
      if (uname) prev.uname = uname
      if (avatar) prev.avatar = avatar
    } else {
      this.ranks.set(uid, {
        uid,
        uname: uname || `用户${uid}`,
        avatar: avatar || null,
        correct: count,
      })
    }
    this._saveToStorage()
    this._notify()
  }

  /** 获取前 N 名 */
  getTopRanks(limit = 10) {
    return [...this.ranks.values()]
      .sort((a, b) => b.correct - a.correct)
      .slice(0, limit)
      .map(r => ({
        user: r.uname,
        uid: r.uid,
        avatar: r.avatar,
        correct: r.correct,
      }))
  }

  /** 获取某用户的猜对次数 */
  getUserCorrect(uid) {
    return this.ranks.get(uid)?.correct || 0
  }

  /** 重置排行榜 */
  reset() {
    this.ranks.clear()
    this._saveToStorage()
    this._notify()
  }

  /** 订阅变化 */
  subscribe(fn) {
    this.listeners.add(fn)
    fn(this.getTopRanks())
    return () => this.listeners.delete(fn)
  }

  _notify() {
    const data = this.getTopRanks()
    this.listeners.forEach(fn => fn(data))
  }

  _saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...this.ranks.values()]))
    } catch (e) {
      console.warn('[RankStore] localStorage 写入失败:', e)
    }
  }

  _loadFromStorage() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const arr = JSON.parse(raw)
        arr.forEach(r => {
          if (r.uid != null && r.correct != null) {
            this.ranks.set(r.uid, r)
          }
        })
      }
    } catch (e) {
      console.warn('[RankStore] localStorage 读取失败:', e)
    }
  }
}

export const rankStore = new RankStore()
