import { StrictMode, useState, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Danmu from './danmuka.jsx'
import RankList from './RankList.jsx'
import { speak, stop, setProvider, getProvider, isWebReady } from './useTTS.js'

const PANEL_THEMES = {
  dark: {
    bg: 'rgba(18, 18, 26, 0.92)',
    rankBg: 'rgba(10, 10, 16, 0.98)',
    border: '1px solid rgba(255,255,255,0.08)',
    divider: 'rgba(255,255,255,0.08)',
  },
  light: {
    bg: 'rgba(250, 248, 245, 0.92)',
    rankBg: 'rgba(235, 232, 228, 0.98)',
    border: '1px solid rgba(0,0,0,0.06)',
    divider: 'rgba(0,0,0,0.08)',
  },
  blue: {
    bg: 'rgba(10, 25, 50, 0.92)',
    rankBg: 'rgba(6, 16, 35, 0.98)',
    border: '1px solid rgba(100,180,255,0.15)',
    divider: 'rgba(100,180,255,0.2)',
  },
  purple: {
    bg: 'rgba(35, 15, 45, 0.92)',
    rankBg: 'rgba(24, 10, 32, 0.98)',
    border: '1px solid rgba(200,120,255,0.12)',
    divider: 'rgba(200,120,255,0.18)',
  },
  green: {
    bg: 'rgba(20, 64, 27, 0.85)',
    rankBg: 'rgba(14, 48, 22, 0.95)',
    border: '1px solid rgba(78,217,101,0.25)',
    divider: 'rgba(78,217,101,0.3)',
  },
}

/* ===== 项目已有的测试文本 ===== */
const TEST_TEXTS = {
  intro: [
    '今晚的底池我全包了。', '短牌才是我的主场。', '准备好输光筹码了吗？', '36张牌，我看你怎么赢。',
    '话别说太早，短牌里运气才是一切。', '我会让你后悔坐上这张桌子。', '来吧，36张牌决胜负。', '别得意，短牌反转多的是。',
  ],
  think: [
    '短牌里成牌率太高了，对手范围很宽...这次我要谨慎一点',
    'A-K同花！短牌里这手牌可以强势加注', '没中牌...但短牌里诈唬成功率更高',
    '全下！短牌里不能怂！', '这手牌在短牌里也打不了...弃牌',
    '底池全部收下~', '位置不利，但短牌底池赔率很好，跟注看看',
  ],
  system: [
    '请投入前注...', '发牌...', '翻牌...', '转牌...', '河牌...',
    '摊牌！双方亮出手牌...', 'AI-A 获胜！对手弃牌。', '双方势均力敌，平局！',
  ],
  danmu: [
    '主播好强！', '666666', '前方高能', '全体起立', '这也太帅了吧',
    '主播辛苦了', '蚌埠住了', '泪目', '火钳刘明', '这就是专业',
  ],
}

function randomPick(arr) {
  return arr[Math.floor(Math.random() * arr.length)]
}

/* ===== TTS 测试浮动面板 ===== */
function TTSControlPanel() {
  const [provider, setLocalProvider] = useState(getProvider())
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(isWebReady())

  useEffect(() => {
    const timer = setInterval(() => setReady(isWebReady()), 500)
    return () => clearInterval(timer)
  }, [])

  const switchProvider = (p) => {
    setProvider(p)
    setLocalProvider(p)
  }

  const handlePlay = (speaker, category) => {
    const text = randomPick(TEST_TEXTS[category] || TEST_TEXTS.intro)
    setPlaying(true)
    speak(text, speaker)
    setTimeout(() => setPlaying(false), 1200)
  }

  const pillStyle = (active) => ({
    padding: '4px 10px',
    borderRadius: '12px',
    border: 'none',
    fontSize: '11px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: '"Microsoft YaHei", sans-serif',
    transition: 'all 0.2s',
    background: active ? 'rgba(100,200,255,0.35)' : 'rgba(255,255,255,0.08)',
    color: active ? '#fff' : 'rgba(255,255,255,0.6)',
  })

  const btnStyle = {
    padding: '6px 14px',
    borderRadius: '20px',
    border: '1px solid rgba(255,255,255,0.12)',
    background: playing ? 'rgba(100,200,255,0.25)' : 'rgba(0,0,0,0.45)',
    color: '#fff',
    fontSize: '12px',
    fontWeight: 600,
    cursor: playing ? 'wait' : 'pointer',
    opacity: playing ? 0.8 : 1,
    fontFamily: '"Microsoft YaHei", sans-serif',
    transition: 'all 0.2s',
    whiteSpace: 'nowrap',
    backdropFilter: 'blur(8px)',
  }

  return (
    <div style={{
      position: 'absolute',
      bottom: '12px',
      right: '12px',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      alignItems: 'flex-end',
    }}>
      {/* Provider 切换 */}
      <div style={{
        display: 'flex',
        gap: '4px',
        padding: '4px',
        borderRadius: '14px',
        background: 'rgba(0,0,0,0.4)',
        backdropFilter: 'blur(8px)',
      }}>
        <button style={pillStyle(provider === 'edge')} onClick={() => switchProvider('edge')}>Edge</button>
        <button style={pillStyle(provider === 'web')} onClick={() => switchProvider('web')}>浏览器</button>
        <button style={pillStyle(provider === 'minimax')} onClick={() => switchProvider('minimax')}>MiniMax</button>
      </div>

      {/* 状态提示 */}
      {!ready && provider === 'web' && (
        <span style={{ fontSize: '10px', color: 'rgba(255,200,100,0.7)' }}>加载语音中...</span>
      )}

      {/* 测试按钮 */}
      <button style={btnStyle} onClick={() => handlePlay('AI-A', 'intro')} disabled={playing}>🔊 开场</button>
      <button style={btnStyle} onClick={() => handlePlay('AI-B', 'think')} disabled={playing}>🔊 思考</button>
      <button style={btnStyle} onClick={() => handlePlay('系统', 'system')} disabled={playing}>🔊 系统</button>
      <button style={btnStyle} onClick={() => handlePlay('AI-A', 'danmu')} disabled={playing}>🔊 弹幕</button>
      <button style={{ ...btnStyle, background: 'rgba(255,80,80,0.25)' }} onClick={stop}>⏹ 停止</button>
    </div>
  )
}

function LeftPanel() {
  const [isExpanded, setIsExpanded] = useState(false)

  const params = new URLSearchParams(window.location.search)
  const themeKey = params.get('theme') || 'dark'
  const theme = PANEL_THEMES[themeKey] || PANEL_THEMES.dark

  // 5秒周期自动切换展开/收起
  useEffect(() => {
    const timer = setInterval(() => {
      setIsExpanded((prev) => !prev)
    }, 5000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div style={{
      width: '380px',
      height: '100vh',
      padding: '14px',
      boxSizing: 'border-box',
      flexShrink: 0,
      zIndex: 10,
    }}>
      {/* 统一背景容器 - 弹幕 + 排行榜共享 */}
      <div style={{
        width: '100%',
        height: '100%',
        borderRadius: '16px',
        background: theme.bg,
        border: theme.border,
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
        gap: '0px',
        overflow: 'hidden',
      }}>
        {/* 弹幕区 */}
        <div style={{ flex: 2, minHeight: 0, overflow: 'hidden', padding: '12px 12px 6px' }}>
          <Danmu isExpanded={isExpanded} />
        </div>
        {/* 排行榜：深色背景，宽度占满，底部贴边 */}
        <div style={{
          background: theme.rankBg,
          borderRadius: '12px 12px 0 0',
          overflow: 'hidden',
        }}>
          <RankList isExpanded={isExpanded} />
        </div>


      </div>
    </div>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <div style={{ position: 'fixed', inset: 0, display: 'flex' }}>
      <LeftPanel />

      {/* 3D 牌桌全屏 */}
      <div style={{
        flex: 1,
        height: '100vh',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <App />
      </div>

      {/* TTS 测试浮动面板 — 绝对定位右下角，不影响其他元素 */}
      <TTSControlPanel />
    </div>
  </StrictMode>,
)
