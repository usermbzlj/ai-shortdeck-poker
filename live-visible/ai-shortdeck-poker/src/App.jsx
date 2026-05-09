import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import expressionMap from './assets/expression_map.json'
import { voteStore } from './voteStore'
import { rankStore } from './rankStore'

/* ===== 配置 ===== */
const WS_URL = (() => {
  const params = new URLSearchParams(window.location.search)
  const wsParam = params.get('ws')
  if (wsParam) return wsParam
  const host = window.location.hostname || 'localhost'
  return `ws://${host}:8002/ws`
})()

/* ===== 牌组工具 ===== */
const SUIT_COLOR = { '♠': '#a0a0a0', '♣': '#a0a0a0', '♥': '#ff6b7a', '♦': '#ff6b7a' }

function parseCard(text) {
  if (!text || text.length < 2) return null
  const rank = text[0].toUpperCase()
  const suitChar = text[1].toLowerCase()
  const suitMap = { s: '♠', h: '♥', d: '♦', c: '♣' }
  const valMap = { '6': 6, '7': 7, '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14 }
  return { suit: suitMap[suitChar], rank, val: valMap[rank] || 0 }
}

function centsToDollars(cents) {
  return Math.round(cents / 100)
}

/* ===== 筹码组件 ===== */
function ChipStack({ amount, size = 'md', className = '' }) {
  if (amount <= 0) return null
  const count = Math.min(14, Math.max(2, Math.floor(amount / 10)))
  const colors = ['red', 'blue', 'green', 'white', 'black', 'gold']
  const chipClass = size === 'sm' ? 'chip-sm' : size === 'lg' ? 'chip-lg' : ''
  return (
    <div className={`chip-stack ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={`chip ${chipClass} chip-${colors[i % colors.length]}`} />
      ))}
    </div>
  )
}

/* ===== 表情映射 ===== */
const EXPRESSIONS = expressionMap.mapping

function getFaceImage(side, exprId, variant = 0) {
  const map = EXPRESSIONS.find(e => e.id === exprId)
  if (!map) return null
  const file = variant === 0
    ? (side === 'A' ? map.charA : map.charB)
    : (side === 'A' ? map.charA_alt : map.charB_alt)
  return new URL(`./assets/${side === 'A' ? 'charA' : 'charB'}/${file}`, import.meta.url).href
}

/* ===== 底牌组件 ===== */
function HoleCard({ card, hidden = false }) {
  if (!card) {
    return <div className="hole-card empty" />
  }
  if (hidden) {
    return <div className="hole-card back" />
  }
  return (
    <div className="hole-card">
      <span className="hole-rank" style={{ color: SUIT_COLOR[card.suit] }}>{card.rank}</span>
      <span className="hole-suit" style={{ color: SUIT_COLOR[card.suit] }}>{card.suit}</span>
    </div>
  )
}

/* ===== 主组件 ===== */
export default function App() {
  /* -- WebSocket -- */
  const [connected, setConnected] = useState(false)
  const ws = useRef(null)

  /* -- 牌局状态（来自后端） -- */
  const [phase, setPhase] = useState('idle')
  const [turn, setTurn] = useState(null)
  const [pot, setPot] = useState(0)
  const [comm, setComm] = useState([])
  const [leftChips, setLeftChips] = useState(0)
  const [rightChips, setRightChips] = useState(0)
  const [leftBet, setLeftBet] = useState(0)
  const [rightBet, setRightBet] = useState(0)
  const [leftHole, setLeftHole] = useState(['', ''])
  const [rightHole, setRightHole] = useState(['', ''])
  const [leftName, setLeftName] = useState('AI-A')
  const [rightName, setRightName] = useState('AI-B')
  const [msg, setMsg] = useState('等待连接后端引擎...')
  const [commentaryList, setCommentaryList] = useState([])
  const [leftTrashTalk, setLeftTrashTalk] = useState('')
  const [rightTrashTalk, setRightTrashTalk] = useState('')
  const [leftThinking, setLeftThinking] = useState('')
  const [rightThinking, setRightThinking] = useState('')
  const [history, setHistory] = useState([])
  const [thinking, setThinking] = useState(false)
  const [handOver, setHandOver] = useState(false)
  const [winner, setWinner] = useState(null)

  /* -- 测试模式 -- */
  const isTestMode = new URLSearchParams(window.location.search).get('test') === '1'

  /* -- 表情 -- */
  const [leftExpr, setLeftExpr] = useState(1)
  const [rightExpr, setRightExpr] = useState(1)

  /* -- 气泡/思考定时器 -- */
  const leftBubbleTimer = useRef(null)
  const rightBubbleTimer = useRef(null)
  const leftThinkTimer = useRef(null)
  const rightThinkTimer = useRef(null)


  /* ---- WebSocket 连接 ---- */
  useEffect(() => {
    let socket
    let reconnectTimer

    const connect = () => {
      try {
        socket = new WebSocket(WS_URL)
        ws.current = socket

        socket.onopen = () => {
          setConnected(true)
          setMsg('已连接后端引擎，等待对局开始...')
        }

        socket.onclose = () => {
          setConnected(false)
          setMsg('连接已断开，5秒后重连...')
          reconnectTimer = setTimeout(connect, 5000)
        }

        socket.onerror = (e) => {
          console.warn('[WS] error', e)
        }

        socket.onmessage = (event) => {
          try {
            const packet = JSON.parse(event.data)
            handleEvent(packet.type, packet.payload)
          } catch (err) {
            console.warn('[WS] parse error', err)
          }
        }
      } catch (err) {
        console.warn('[WS] connect error', err)
        reconnectTimer = setTimeout(connect, 5000)
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer)
      if (socket) socket.close()
    }
  }, [])

  /* ---- 事件处理 ---- */
  const showTrashTalk = useCallback((side, text) => {
    if (side === 'A') {
      setLeftTrashTalk(text)
      clearTimeout(leftBubbleTimer.current)
      leftBubbleTimer.current = setTimeout(() => setLeftTrashTalk(''), 5000)
    } else {
      setRightTrashTalk(text)
      clearTimeout(rightBubbleTimer.current)
      rightBubbleTimer.current = setTimeout(() => setRightTrashTalk(''), 5000)
    }
  }, [])

  const showThinking = useCallback((side, text) => {
    if (side === 'A') {
      setLeftThinking(text)
      clearTimeout(leftThinkTimer.current)
      leftThinkTimer.current = setTimeout(() => setLeftThinking(''), 5000)
    } else {
      setRightThinking(text)
      clearTimeout(rightThinkTimer.current)
      rightThinkTimer.current = setTimeout(() => setRightThinking(''), 5000)
    }
  }, [])

  const updateExpressions = useCallback((payload) => {
    const street = payload.street || 'idle'
    const hand_over = payload.hand_over
    const winner = payload.winner
    const next = payload.next_to_act
    const isThinking = payload.thinking

    if (hand_over) {
      if (winner === 'AI_A') { setLeftExpr(8); setRightExpr(9) }
      else if (winner === 'AI_B') { setLeftExpr(9); setRightExpr(8) }
      else { setLeftExpr(12); setRightExpr(12) }
    } else if (isThinking) {
      if (next === 'AI_A') { setLeftExpr(6); setRightExpr(1) }
      else if (next === 'AI_B') { setRightExpr(6); setLeftExpr(1) }
    } else {
      const map = { preflop: 1, flop: 6, turn: 6, river: 6 }
      const expr = map[street] || 1
      setLeftExpr(expr)
      setRightExpr(expr)
    }
  }, [])

  const handleEvent = useCallback((type, payload) => {
    switch (type) {
      case 'pong':
        break

      case 'state_sync': {
        setPhase(payload.street || 'idle')
        setTurn(payload.next_to_act === 'AI_A' ? 'A' : payload.next_to_act === 'AI_B' ? 'B' : null)
        setPot(centsToDollars(payload.pot_cents || 0))
        setComm((payload.board_cards || []).map(parseCard).filter(Boolean))
        setLeftChips(centsToDollars(payload.stacks_cents?.AI_A || 0))
        setRightChips(centsToDollars(payload.stacks_cents?.AI_B || 0))
        setLeftBet(centsToDollars(payload.contributed_street_cents?.AI_A || 0))
        setRightBet(centsToDollars(payload.contributed_street_cents?.AI_B || 0))
        setLeftHole(payload.hole_cards?.AI_A || ['', ''])
        setRightHole(payload.hole_cards?.AI_B || ['', ''])
        setLeftName(payload.player_names?.AI_A || 'AI-A')
        setRightName(payload.player_names?.AI_B || 'AI-B')
        setHistory(payload.action_history || [])
        setThinking(payload.thinking || false)
        setHandOver(payload.hand_over || false)
        setWinner(payload.winner || null)
        if (payload.status_text) setMsg(payload.status_text)
        updateExpressions(payload)
        break
      }

      case 'match_started': {
        setMsg('新比赛开始')
        setCommentaryList([])
        setLeftTrashTalk('')
        setRightTrashTalk('')
        setLeftThinking('')
        setRightThinking('')
        setLeftExpr(1)
        setRightExpr(1)
        break
      }

      case 'hand_started': {
        setMsg(`Hand #${payload.hand_id} 开始`)
        setCommentaryList([])
        setLeftTrashTalk('')
        setRightTrashTalk('')
        setLeftThinking('')
        setRightThinking('')
        // 广播新局开始，重置投票
        window.dispatchEvent(new CustomEvent('vote:reset'))
        break
      }

      case 'thinking_started': {
        setThinking(true)
        const name = payload.player_name || payload.player
        setMsg(`${name} 思考中...`)
        if (payload.player === 'AI_A') {
          setLeftExpr(6)
          setRightExpr(1)
        } else {
          setRightExpr(6)
          setLeftExpr(1)
        }
        break
      }

      case 'thinking_result': {
        if (payload.trash_talk) {
          const side = payload.player === 'AI_A' ? 'A' : 'B'
          showTrashTalk(side, payload.trash_talk)
        }
        const thinkText = payload.reasoning
          ? payload.reasoning.substring(0, 70) + (payload.reasoning.length > 70 ? '...' : '')
          : payload.analysis || ''
        if (thinkText) {
          const side = payload.player === 'AI_A' ? 'A' : 'B'
          showThinking(side, thinkText)
        }
        break
      }

      case 'action_executed': {
        const pname = payload.player_name || payload.player
        const actionText = (payload.action || '').toUpperCase()
        const toText = payload.to_cents ? ` to $${centsToDollars(payload.to_cents)}` : ''
        setMsg(`${pname} ${actionText}${toText}`)
        break
      }

      case 'street_advanced': {
        const streetMap = { preflop: '翻牌前', flop: '翻牌', turn: '转牌', river: '河牌' }
        setMsg(`${streetMap[payload.street] || payload.street} — 发公共牌`)
        break
      }

      case 'hand_ended': {
        if (payload.winner) {
          const wname = payload.winner_name || payload.winner
          setMsg(`${wname} 获胜！`)
          if (payload.winner === 'AI_A') { setLeftExpr(8); setRightExpr(9) }
          else { setLeftExpr(9); setRightExpr(8) }
          // 自动结算投票：AI_A -> A, AI_B -> B
          const winningSide = payload.winner === 'AI_A' ? 'A' : 'B'
          const result = voteStore.settle(winningSide)
          console.log(`[vote] 本局结算：${winningSide} 获胜，${result.correctCount} 人猜对`)
        } else {
          setMsg('平局，平分底池')
          setLeftExpr(12)
          setRightExpr(12)
        }
        break
      }

      case 'commentary': {
        if (payload.text) {
          setCommentaryList(prev => [...prev, `🎙️ ${payload.text}`])
        }
        break
      }

      case 'player_reaction': {
        if (payload.text) {
          setCommentaryList(prev => [...prev, `${payload.label || ''}: "${payload.text}"`])
        }
        break
      }

      case 'error': {
        setMsg(`⚠️ ${payload.error || '未知错误'}`)
        break
      }

      default:
        console.log('[WS] unknown event', type, payload)
    }
  }, [showTrashTalk, showThinking, updateExpressions])

  /* ---- 渲染 ---- */
  const isFocusA = turn === 'A'
  const isFocusB = turn === 'B'
  const leftFace = getFaceImage('A', leftExpr)
  const rightFace = getFaceImage('B', rightExpr)
  const leftCards = leftHole.map(parseCard)
  const rightCards = rightHole.map(parseCard)

  return (
    <div className="table-root">
      {/* 连接状态指示 */}
      <div className={`ws-status ${connected ? 'online' : 'offline'}`}>
        {connected ? '● 已连接' : '● 未连接'}
      </div>

      {/* 测试按钮：仅 test=1 时显示 */}
      {isTestMode && (
        <div style={{
          position: 'absolute',
          top: '12px',
          right: '12px',
          display: 'flex',
          gap: '6px',
          zIndex: 50,
        }}>
          <button
            onClick={() => {
              const r = voteStore.settle('A')
              setMsg(`[测试] A 获胜 — ${r.correctCount} 人猜对`)
            }}
            style={{
              padding: '4px 10px',
              fontSize: '12px',
              fontWeight: 600,
              color: '#fff',
              background: '#0288d1',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              opacity: 0.8,
            }}
            onMouseEnter={e => e.target.style.opacity = '1'}
            onMouseLeave={e => e.target.style.opacity = '0.8'}
          >
            结算 A 赢
          </button>
          <button
            onClick={() => {
              const r = voteStore.settle('B')
              setMsg(`[测试] B 获胜 — ${r.correctCount} 人猜对`)
            }}
            style={{
              padding: '4px 10px',
              fontSize: '12px',
              fontWeight: 600,
              color: '#fff',
              background: '#d32f2f',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              opacity: 0.8,
            }}
            onMouseEnter={e => e.target.style.opacity = '1'}
            onMouseLeave={e => e.target.style.opacity = '0.8'}
          >
            结算 B 赢
          </button>
          <button
            onClick={() => {
              rankStore.reset()
              setMsg('[测试] 排行榜已重置')
            }}
            style={{
              padding: '4px 10px',
              fontSize: '12px',
              fontWeight: 600,
              color: '#fff',
              background: '#666',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              opacity: 0.8,
            }}
            onMouseEnter={e => e.target.style.opacity = '1'}
            onMouseLeave={e => e.target.style.opacity = '0.8'}
          >
            重置排行
          </button>
        </div>
      )}

      {/* 牌桌 — 固定屏幕中央 */}
      <div className="poker-table">
        <div className="table-line" />

        {/* 底池 */}
        <div className="pot-area">
          <span className="pot-label">POT</span>
          <span className="pot-value">${pot}</span>
          <ChipStack amount={pot} />
        </div>

        {/* 公共牌 */}
        <div className="comm-area">
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className={`card ${comm[i] ? 'filled' : ''}`}>
              {comm[i] ? (
                <>
                  <span className="card-rank" style={{ color: SUIT_COLOR[comm[i].suit] }}>{comm[i].rank}</span>
                  <span className="card-suit" style={{ color: SUIT_COLOR[comm[i].suit] }}>{comm[i].suit}</span>
                </>
              ) : null}
            </div>
          ))}
        </div>

        {/* 桌面消息 */}
        {msg && <div className="table-msg">{msg}</div>}
      </div>

      {/* 解说栏 — 固定在牌桌正下方 */}
      {commentaryList.length > 0 && (
        <div className="commentary-bar">
          {[...commentaryList.slice(-3)].reverse().map((text, i, arr) => {
            const opacity = 0.3 + (0.7 * ((arr.length - 1 - i) / (arr.length - 1 || 1)))
            return (
              <div key={i} className="commentary-item" style={{ opacity }}>
                {text}
              </div>
            )
          })}
        </div>
      )}

      {/* 左侧角色 — 仅包含立绘与基本信息 */}
      <div className={`character char-left ${isFocusA ? 'focus' : ''} ${isFocusB ? 'dim' : ''}`}>
        <div className="char-img-wrap">
          <img src={leftFace} alt={leftName} draggable={false} />
        </div>

        <div className="char-info">
          <span className="char-name">{leftName}</span>
          <span className="char-chips">${leftChips}</span>
        </div>

        {/* 底牌 */}
        <div className="hole-cards">
          <HoleCard card={leftCards[0]} />
          <HoleCard card={leftCards[1]} />
        </div>

        {/* 下注筹码 */}
        {leftBet > 0 && (
          <div className="bet-chips">
            <ChipStack amount={leftBet} size="sm" />
            <span className="bet-amount">+${leftBet}</span>
          </div>
        )}

        {isFocusA && <div className="turn-dot" />}
      </div>

      {/* 右侧角色 */}
      <div className={`character char-right ${isFocusB ? 'focus' : ''} ${isFocusA ? 'dim' : ''}`}>
        <div className="char-img-wrap">
          <img src={rightFace} alt={rightName} draggable={false} />
        </div>

        <div className="char-info">
          <span className="char-name">{rightName}</span>
          <span className="char-chips">${rightChips}</span>
        </div>

        {/* 底牌 */}
        <div className="hole-cards">
          <HoleCard card={rightCards[0]} />
          <HoleCard card={rightCards[1]} />
        </div>

        {/* 下注筹码 */}
        {rightBet > 0 && (
          <div className="bet-chips">
            <ChipStack amount={rightBet} size="sm" />
            <span className="bet-amount">+${rightBet}</span>
          </div>
        )}

        {isFocusB && <div className="turn-dot" />}
      </div>

      {/* ===== 覆盖层：气泡与思考文本（独立于角色，不受缩放影响） ===== */}

      {/* 左侧垃圾话气泡 */}
      {leftTrashTalk && (
        <div className="trash-talk-bubble bubble-left">
          {leftTrashTalk}
        </div>
      )}

      {/* 右侧垃圾话气泡 */}
      {rightTrashTalk && (
        <div className="trash-talk-bubble bubble-right">
          {rightTrashTalk}
        </div>
      )}

      {/* 左侧思考内容 */}
      {leftThinking && (
        <div className="thinking-box think-left">
          <span className="thinking-label">🧠</span>
          {leftThinking}
        </div>
      )}

      {/* 右侧思考内容 */}
      {rightThinking && (
        <div className="thinking-box think-right">
          <span className="thinking-label">🧠</span>
          {rightThinking}
        </div>
      )}
    </div>
  )
}
