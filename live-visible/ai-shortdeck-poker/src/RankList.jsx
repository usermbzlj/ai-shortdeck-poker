import { useState, useEffect } from 'react'
import { rankStore } from './rankStore'

const THEMES = {
  dark: {
    textColor: '#f5f5f5',
    subTextColor: 'rgba(255,255,255,0.55)',
    titleColor: '#ff85a2',
  },
  light: {
    textColor: '#1a1a1a',
    subTextColor: 'rgba(0,0,0,0.5)',
    titleColor: '#e91e63',
  },
  blue: {
    textColor: '#e8f4ff',
    subTextColor: 'rgba(180,210,255,0.6)',
    titleColor: '#66d9ff',
  },
  purple: {
    textColor: '#f8e8ff',
    subTextColor: 'rgba(220,200,255,0.55)',
    titleColor: '#ff9ef0',
  },
  green: {
    textColor: '#fffcfe',
    subTextColor: 'rgba(150,255,170,0.55)',
    titleColor: '#64e179',
  },
}

const PODIUM_COLORS = {
  1: { bg: '#FFD700', text: '#7A5C00', shadow: 'rgba(255,215,0,0.35)' },
  2: { bg: '#C0C0C0', text: '#555555', shadow: 'rgba(192,192,192,0.35)' },
  3: { bg: '#CD7F32', text: '#5C3A10', shadow: 'rgba(205,127,50,0.35)' },
}

function getAvatar(name, size = 64) {
  return `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=random&color=fff&size=${size}&font-size=0.4&length=1`
}

function PodiumItem({ rank, item, theme }) {
  const colors = PODIUM_COLORS[rank]
  const isFirst = rank === 1
  const heights = { 1: 88, 2: 62, 3: 48 }
  const widths = { 1: 100, 2: 88, 3: 88 }
  const avatarSize = isFirst ? 40 : 32

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        width: `${widths[rank]}px`,
      }}
    >
      <img
        src={item.avatar || getAvatar(item.user, 128)}
        alt=""
        referrerPolicy="no-referrer"
        style={{
          width: `${avatarSize}px`,
          height: `${avatarSize}px`,
          borderRadius: '50%',
          border: `2.5px solid ${colors.bg}`,
          boxShadow: `0 0 10px ${colors.shadow}`,
          marginBottom: '3px',
        }}
      />
      <span
        style={{
          fontSize: isFirst ? '12px' : '11px',
          fontWeight: 600,
          color: theme.textColor,
          maxWidth: '100%',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          textAlign: 'center',
          padding: '0 4px',
        }}
      >
        {item.user}
      </span>
      <span
        style={{
          fontSize: isFirst ? '11px' : '10px',
          fontWeight: 700,
          color: colors.bg,
          marginBottom: '5px',
        }}
      >
        {item.correct} 次
      </span>
      <div
        style={{
          width: '100%',
          height: `${heights[rank]}px`,
          background: `linear-gradient(180deg, ${colors.bg} 0%, ${colors.bg}dd 100%)`,
          borderRadius: '8px 8px 0 0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
        }}
      >
        <span
          style={{
            fontSize: isFirst ? '28px' : '22px',
            fontWeight: 900,
            color: colors.text,
            opacity: 0.9,
          }}
        >
          {rank}
        </span>
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: '10%',
            right: '10%',
            height: '2px',
            background: 'rgba(255,255,255,0.5)',
            borderRadius: '1px',
          }}
        />
      </div>
    </div>
  )
}

function RankList({ isExpanded }) {
  const [ranks, setRanks] = useState(() => rankStore.getTopRanks())

  const params = new URLSearchParams(window.location.search)
  const themeKey = params.get('theme') || 'dark'
  const theme = THEMES[themeKey] || THEMES.dark

  useEffect(() => {
    const unsubscribe = rankStore.subscribe(setRanks)
    return unsubscribe
  }, [])

  const top3 = ranks.slice(0, 3)
  const rest = ranks.slice(3)

  return (
    <div
      style={{
        width: '100%',
        overflow: 'hidden',
        flexShrink: 0,
        fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif',
        color: theme.textColor,
      }}
    >
      {/* 领奖台：有数据就显示（不满3人时居中占位） */}
      {top3.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'center',
            gap: '6px',
            padding: '10px 8px 0',
          }}
        >
          {top3.length >= 2 && <PodiumItem rank={2} item={top3[1]} theme={theme} />}
          <PodiumItem rank={1} item={top3[0]} theme={theme} />
          {top3.length >= 3 && <PodiumItem rank={3} item={top3[2]} theme={theme} />}
        </div>
      )}

      {/* 空状态 */}
      {ranks.length === 0 && (
        <div
          style={{
            textAlign: 'center',
            padding: '20px 8px',
            color: theme.subTextColor,
            fontSize: '13px',
          }}
        >
          🏆 暂无预测记录<br />
          <span style={{ fontSize: '12px' }}>发送弹幕 A 或 B 参与预测</span>
        </div>
      )}

      {/* 第4-10名列表：展开时显示，收起时隐藏 */}
      <div
        style={{
          maxHeight: isExpanded ? '224px' : '0px',
          opacity: isExpanded ? 1 : 0,
          overflow: 'hidden',
          transition: 'max-height 0.4s ease, opacity 0.3s ease',
          padding: '0 8px',
        }}
      >
        {rest.map((item, index) => {
          const rankNum = index + 4
          return (
            <div
              key={item.uid || item.user}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '4px 8px',
                marginBottom: '2px',
              }}
            >
              <span
                style={{
                  width: '20px',
                  textAlign: 'center',
                  fontWeight: 700,
                  fontSize: '12px',
                  color: theme.subTextColor,
                }}
              >
                {rankNum}
              </span>
              <img
                src={item.avatar || getAvatar(item.user, 64)}
                alt=""
                referrerPolicy="no-referrer"
                style={{
                  width: '22px',
                  height: '22px',
                  borderRadius: '50%',
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  flex: 1,
                  fontSize: '12px',
                  fontWeight: 500,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {item.user}
              </span>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  color: theme.titleColor,
                }}
              >
                {item.correct} 次
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default RankList
