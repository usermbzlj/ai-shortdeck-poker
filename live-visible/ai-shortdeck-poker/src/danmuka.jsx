import { useState, useEffect, useRef, useCallback } from 'react'
import { voteStore } from './voteStore'

const USERS = [
  '喵喵拳', '星际旅人', '夜航船', '可乐加冰', '风一样的男子',
  '吃瓜群众', '弹幕测试员', 'AAA建材王哥', '摸鱼大师', '被窝探险家',
  '早八毁灭者', '奶茶续命', '香菜不吃', '猫猫头', '无敌暴龙战士',
]

const CONTENTS = [
  '主播好强！', '666666', '来了来了', '这波操作可以', '哈哈哈哈哈哈',
  '前方高能', '全体起立', '主播声音好听', '什么时候抽奖', '下次一定',
  '这也太帅了吧', '主播辛苦了', '蚌埠住了', '泪目', '火钳刘明',
  '第一！', '梦幻联动', '双厨狂喜', '血压升高', '标准结局',
  '这能输？', '主播是我爹', '保护', '这就是专业', '学废了',
]

const THEMES = {
  dark: {
    name: '深邃黑',
    cardBg: 'rgba(18, 18, 22, 0.88)',
    cardBorder: '1px solid rgba(255,255,255,0.08)',
    userColor: '#ff85a2',
    textColor: '#f5f5f5',
    avatarBorder: '2px solid rgba(255,255,255,0.2)',
  },
  light: {
    name: '奶油白',
    cardBg: 'rgba(255, 252, 245, 0.92)',
    cardBorder: '1px solid rgba(0,0,0,0.06)',
    userColor: '#e91e63',
    textColor: '#1a1a1a',
    avatarBorder: '2px solid rgba(0,0,0,0.1)',
  },
  blue: {
    name: '深海蓝',
    cardBg: 'rgba(10, 25, 50, 0.88)',
    cardBorder: '1px solid rgba(100,180,255,0.15)',
    userColor: '#66d9ff',
    textColor: '#e8f4ff',
    avatarBorder: '2px solid rgba(100,200,255,0.3)',
  },
  purple: {
    name: '幻紫夜',
    cardBg: 'rgba(35, 15, 45, 0.88)',
    cardBorder: '1px solid rgba(200,120,255,0.12)',
    userColor: '#ff9ef0',
    textColor: '#f8e8ff',
    avatarBorder: '2px solid rgba(220,100,255,0.25)',
  },
  green: {
    name: '翠玉青',
    cardBg: 'rgba(20, 64, 27, 0.8)',
    cardBorder: '1px solid rgba(78,217,101,0.25)',
    userColor: '#64e179',
    textColor: '#fffcfe',
    avatarBorder: '2px solid rgba(78,217,101,0.4)',
  },
}

function randomPick(arr) {
  return arr[Math.floor(Math.random() * arr.length)]
}

function getAvatar(name) {
  return `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=random&color=fff&size=64&font-size=0.4&length=1`
}

/* ===== 投票条组件 ===== */
function VoteBar({ stats, theme }) {
  const { totalA, totalB, total, percentA, percentB } = stats
  const recentA = voteStore.getRecentVoters('A', 4)
  const recentB = voteStore.getRecentVoters('B', 4)

  if (total === 0) {
    return (
      <div style={{
        padding: '8px 10px',
        marginBottom: '6px',
        background: theme.cardBg,
        border: theme.cardBorder,
        borderRadius: '6px',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
      }}>
        <div style={{
          textAlign: 'center',
          color: theme.textColor,
          fontSize: '13px',
          opacity: 0.7,
        }}>
          💬 弹幕发送 <b style={{ color: '#4fc3f7' }}>A</b> 或 <b style={{ color: '#ff8a80' }}>B</b> 预测胜利方
        </div>
      </div>
    )
  }

  return (
    <div style={{
      padding: '8px 10px',
      marginBottom: '6px',
      background: theme.cardBg,
      border: theme.cardBorder,
      borderRadius: '6px',
      backdropFilter: 'blur(6px)',
      WebkitBackdropFilter: 'blur(6px)',
    }}>
      {/* 百分比条 */}
      <div style={{
        display: 'flex',
        height: '22px',
        borderRadius: '4px',
        overflow: 'hidden',
        marginBottom: '6px',
      }}>
        <div style={{
          width: `${percentA}%`,
          background: 'linear-gradient(90deg, #0288d1, #4fc3f7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-start',
          paddingLeft: '8px',
          transition: 'width 0.5s ease',
          minWidth: percentA > 0 ? '30px' : '0',
        }}>
          {percentA >= 15 && (
            <span style={{ color: '#fff', fontSize: '12px', fontWeight: 700 }}>{percentA}%</span>
          )}
        </div>
        <div style={{
          width: `${percentB}%`,
          background: 'linear-gradient(90deg, #ff8a80, #d32f2f)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          paddingRight: '8px',
          transition: 'width 0.5s ease',
          minWidth: percentB > 0 ? '30px' : '0',
        }}>
          {percentB >= 15 && (
            <span style={{ color: '#fff', fontSize: '12px', fontWeight: 700 }}>{percentB}%</span>
          )}
        </div>
      </div>

      {/* 票数 + 头像 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        {/* A 侧 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ color: '#4fc3f7', fontSize: '13px', fontWeight: 700, minWidth: '22px' }}>
            A {totalA}
          </span>
          <div style={{ display: 'flex', marginLeft: '2px' }}>
            {recentA.map((v, i) => (
              <img
                key={v.uid}
                src={v.avatar || getAvatar(v.uname)}
                alt=""
                referrerPolicy="no-referrer"
                style={{
                  width: '20px',
                  height: '20px',
                  borderRadius: '50%',
                  border: '1.5px solid #4fc3f7',
                  marginLeft: i > 0 ? '-6px' : '0',
                  zIndex: recentA.length - i,
                }}
              />
            ))}
          </div>
        </div>

        {/* 中间 VS */}
        <span style={{ color: theme.textColor, fontSize: '11px', opacity: 0.5, fontWeight: 600 }}>VS</span>

        {/* B 侧 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexDirection: 'row-reverse' }}>
          <span style={{ color: '#ff8a80', fontSize: '13px', fontWeight: 700, minWidth: '22px', textAlign: 'right' }}>
            {totalB} B
          </span>
          <div style={{ display: 'flex', marginRight: '2px', flexDirection: 'row-reverse' }}>
            {recentB.map((v, i) => (
              <img
                key={v.uid}
                src={v.avatar || getAvatar(v.uname)}
                alt=""
                referrerPolicy="no-referrer"
                style={{
                  width: '20px',
                  height: '20px',
                  borderRadius: '50%',
                  border: '1.5px solid #ff8a80',
                  marginRight: i > 0 ? '-6px' : '0',
                  zIndex: recentB.length - i,
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function Danmu({ isExpanded }) {
  const [messages, setMessages] = useState([])
  const [status, setStatus] = useState('')
  const [voteStats, setVoteStats] = useState(() => voteStore.getStats())
  const idRef = useRef(0)
  const faceCache = useRef(new Map())

  const params = new URLSearchParams(window.location.search)
  const roomId = params.get('roomId') || '模拟房间'
  const themeKey = params.get('theme') || 'dark'
  const theme = THEMES[themeKey] || THEMES.dark

  // 从 localStorage 读取 B站 Cookie（config.json 不存在时的 fallback）
  const localCookie = localStorage.getItem('bili_cookie') || ''

  // 订阅投票统计变化
  useEffect(() => {
    const unsubscribe = voteStore.subscribe(setVoteStats)
    return unsubscribe
  }, [])

  // 监听新局重置事件
  useEffect(() => {
    const handleReset = () => {
      voteStore.reset()
      setMessages(prev => [{
        id: idRef.current++,
        user: '系统',
        content: '🗳️ 新一局开始，投票已重置',
        avatar: getAvatar('系统'),
        hasBadges: false,
        isSystem: true,
      }, ...prev].slice(0, 30))
    }
    window.addEventListener('vote:reset', handleReset)
    return () => window.removeEventListener('vote:reset', handleReset)
  }, [])

  // 监听结算事件，显示结算结果
  useEffect(() => {
    const handleSettled = (e) => {
      const { winningSide, correctCount, wrongCount } = e.detail
      setMessages(prev => [{
        id: idRef.current++,
        user: '系统',
        content: `🎉 ${winningSide} 方获胜！${correctCount} 人猜对，${wrongCount} 人猜错`,
        avatar: getAvatar('系统'),
        hasBadges: false,
        isSystem: true,
      }, ...prev].slice(0, 30))
    }
    window.addEventListener('vote:settled', handleSettled)
    return () => window.removeEventListener('vote:settled', handleSettled)
  }, [])

  /* 处理投票弹幕 */
  const handleVote = useCallback((uid, uname, avatar, content) => {
    const vote = content.toUpperCase()
    if (vote !== 'A' && vote !== 'B') return false

    const result = voteStore.vote(uid, uname, avatar, vote)

    // 生成投票反馈消息
    let feedback = ''
    if (result.isNew) {
      feedback = `🗳️ 预测 ${vote} 方获胜`
    } else if (result.isChanged) {
      feedback = `🔄 改投 ${vote} 方`
    } else {
      feedback = `✅ 已投 ${vote} 方`
    }

    setMessages(prev => {
      const next = [{
        id: idRef.current++,
        uid,
        user: uname,
        content: feedback,
        avatar,
        hasBadges: false,
        isVote: true,
      }, ...prev]
      if (next.length > 30) next.pop()
      return next
    })

    return true
  }, [])

  useEffect(() => {
    let cleanupFn = null

    const startMockDanmu = () => {
      setStatus('模拟房间 · 主题: ' + theme.name)

      const initial = Array.from({ length: 5 }, (_, i) => {
        const user = USERS[i % USERS.length]
        return {
          id: idRef.current++,
          user,
          content: randomPick(CONTENTS),
          avatar: getAvatar(user),
          hasBadges: Math.random() > 0.4,
        }
      })
      setMessages(initial)

      const timer = setInterval(() => {
        setMessages((prev) => {
          const user = randomPick(USERS)
          // 模拟投票：10% 概率投 A，10% 概率投 B
          const r = Math.random()
          const content = r < 0.1 ? 'A' : r < 0.2 ? 'B' : randomPick(CONTENTS)
          const uid = 100000 + Math.floor(Math.random() * 900000)
          const avatar = getAvatar(user)

          if (content === 'A' || content === 'B') {
            handleVote(uid, user, avatar, content)
            return prev
          }

          const next = [
            {
              id: idRef.current++,
              uid,
              user,
              content,
              avatar,
              hasBadges: Math.random() > 0.4,
            },
            ...prev,
          ]
          if (next.length > 30) next.pop()
          return next
        })
      }, 800)

      cleanupFn = () => clearInterval(timer)
    }

    // 没有真实房间号时使用模拟数据
    if (!roomId || roomId === '模拟房间') {
      startMockDanmu()
      return cleanupFn
    }

    // 有真实房间号，连接 B站直播弹幕
    setStatus(`房间 ${roomId} · 连接中...`)
    let instance = null

    const connect = async () => {
      // 读取配置：优先 config.json，fallback localStorage
      let cookie = localCookie
      let preToken = ''
      let preBuvid = ''
      let preHost = ''
      let prePort = 0
      try {
        const res = await fetch('/config.json')
        const cfg = await res.json()
        if (cfg.cookie) cookie = cfg.cookie
        if (cfg.token) preToken = cfg.token
        if (cfg.buvid) preBuvid = cfg.buvid
        if (cfg.host) preHost = cfg.host
        if (cfg.port) prePort = Number(cfg.port)
      } catch (e) {
        // config.json 不存在或读取失败
      }

      // 获取 B站弹幕认证参数（token / buvid / uid / 真实房间号）
      let uid = 0
      let token = preToken
      let buvid = preBuvid
      let realRoomId = Number(roomId)
      let wsHost = preHost
      let wsPort = prePort
      try {
        const authRes = await fetch(`/api/bili/auth?roomId=${roomId}`)
        const authJson = await authRes.json()
        console.log('[danmu] /api/bili/auth 返回:', JSON.stringify(authJson))
        if (authJson.code === 0 && authJson.data) {
          uid = authJson.data.uid || uid
          token = authJson.data.token || token
          buvid = authJson.data.buvid || buvid
          realRoomId = authJson.data.roomId || realRoomId
          wsHost = authJson.data.host || wsHost
          wsPort = authJson.data.port || wsPort
        } else {
          console.warn('[danmu] /api/bili/auth 返回错误，使用预配置参数')
        }
      } catch (e) {
        console.warn('[danmu] /api/bili/auth 请求失败，使用预配置参数', e.message)
      }

      // fallback: 如果 API 没返回 uid，尝试从 cookie 中提取
      if (!uid && cookie) {
        const m = cookie.match(/DedeUserID=(\d+)/)
        if (m) uid = Number(m[1])
      }

      // 如果仍然没有 buvid，尝试从 cookie 中提取
      if (!buvid && cookie) {
        const m = cookie.match(/buvid3=([^;]+)/)
        if (m) buvid = decodeURIComponent(m[1])
      }

      const wsOptions = {
        platform: 'web',
        protover: 3,
        type: 2,
        uid,
      }
      if (token) wsOptions.key = token
      if (buvid) wsOptions.buvid = buvid
      if (cookie) wsOptions.headers = { Cookie: cookie }
      if (wsHost) {
        wsOptions.host = wsHost
        wsOptions.port = wsPort
        wsOptions.ssl = true
      }
      console.log('[danmu] 连接参数:', {
        roomId: realRoomId,
        uid,
        token: token ? token.slice(0, 20) + '...' : '空',
        buvid: buvid ? buvid.slice(0, 20) + '...' : '空',
        host: wsHost,
        port: wsPort,
        ssl: wsOptions.ssl,
        protover: wsOptions.protover,
      })

      if (!token && !buvid) {
        console.warn('[danmu] token 和 buvid 均为空，无法建立真实弹幕连接，切换模拟弹幕')
        setStatus(`房间 ${realRoomId} · 缺少认证参数，已切换模拟弹幕`)
        startMockDanmu()
        return
      }

      try {
        const { startListen } = await import('blive-message-listener/browser')
        instance = startListen(realRoomId, {
          onOpen: () => {
            console.log('[danmu] WebSocket onOpen')
            setStatus(`房间 ${realRoomId} · 已连接`)
          },
          onClose: () => {
            console.log('[danmu] WebSocket onClose')
            setStatus(`房间 ${realRoomId} · 已断开`)
          },
          onStartListen: () => {
            console.log('[danmu] 认证成功，开始监听')
          },
          onError: (err) => {
            console.error('[danmu] 连接错误', err)
            setStatus(`房间 ${realRoomId} · 连接失败，已切换模拟弹幕`)
            if (instance) { instance.close(); instance = null }
            startMockDanmu() // fallback
          },
          onAttentionChange: (msg) => {
            console.log('[danmu] 心跳/在线人数:', msg.data?.attention)
          },
          onIncomeDanmu: (msg) => {
            const uid = msg.body.user.uid
            const uname = msg.body.user.uname
            const content = msg.body.content.trim()
            let avatar = faceCache.current.get(uid)

            // 检测投票指令 A/B
            if (/^[AaBb]$/.test(content)) {
              handleVote(uid, uname, avatar || getAvatar(uname), content)
              return
            }

            if (!avatar) {
              avatar = getAvatar(uname)
              // 异步获取真实头像并更新
              fetch(`/api/bili/user?uid=${uid}`)
                .then(r => r.json())
                .then(res => {
                  if (res.code === 0 && res.data?.face) {
                    faceCache.current.set(uid, res.data.face)
                    setMessages(prev => prev.map(m =>
                      m.uid === uid ? { ...m, avatar: res.data.face } : m
                    ))
                    // 同步更新投票缓存中的头像
                    const voteRec = voteStore.votes?.get?.(uid)
                    if (voteRec) {
                      voteStore.vote(uid, voteRec.uname, res.data.face, voteRec.vote)
                    }
                  }
                })
                .catch(() => {})
            }
            setMessages((prev) => {
              const next = [
                {
                  id: msg.id,
                  uid,
                  user: uname,
                  content: msg.body.content,
                  avatar,
                  hasBadges: (msg.body.user.identity?.guard_level ?? 0) > 0,
                },
                ...prev,
              ]
              if (next.length > 30) next.pop()
              return next
            })
          },
          raw: {
            DANMU_MSG: (data) => {
              console.log('[danmu] 原始 DANMU_MSG:', JSON.stringify(data).slice(0, 500))
            },
            CONNECT_SUCCESS: (data) => {
              console.log('[danmu] 原始 CONNECT_SUCCESS:', JSON.stringify(data))
            },
            HEARTBEAT_REPLY: (data) => {
              console.log('[danmu] 原始 HEARTBEAT_REPLY:', data)
            },
            USER_AUTHENTICATION: (data) => {
              console.log('[danmu] 原始 USER_AUTHENTICATION:', JSON.stringify(data))
            },
          },
        }, { ws: wsOptions })
        cleanupFn = () => { if (instance) instance.close() }
      } catch (err) {
        console.error('导入 blive-message-listener 失败', err)
        setStatus(`房间 ${realRoomId} · 连接失败: ${err.message}`)
        startMockDanmu() // fallback
      }
    }

    connect()

    return () => {
      if (cleanupFn) cleanupFn()
    }
  }, [roomId, theme.name, handleVote])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* 弹幕消息列表：从上向下排列 */}
      <div
        style={{
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-start',
          padding: '6px 0 0 0',
          boxSizing: 'border-box',
          fontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif',
          fontSize: '17px',
          pointerEvents: 'none',
        }}
      >
        {/* 投票条 */}
        <VoteBar stats={voteStats} theme={theme} />

        {/* 调试提示：{status} | 切换主题 ?theme=dark / light / blue / purple / green */}
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: 'flex',
              alignItems: 'flex-end',
              marginBottom: '8px',
              animation: 'danmuSlideDown 0.1s ease-out',
              maxWidth: 'fit-content',
              opacity: msg.isSystem ? 0.7 : 1,
            }}
          >
            {/* 头像：在信息栏左上方，z-index 更高 */}
            <img
              src={msg.avatar}
              alt=""
              referrerPolicy="no-referrer"
              onError={(e) => { e.target.src = getAvatar(msg.user) }}
              style={{
                width: '50px',
                height: '50px',
                borderRadius: '50%',
                border: msg.isVote ? '3px solid #FFD700' : '3px solid #4CAF50',
                background: '#C8E6C9',
                flexShrink: 0,
                zIndex: 2,
                position: 'relative',
              }}
            />

            {/* 右侧：用户名行 + 绿色信息栏 */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                marginLeft: '-18px',
                minWidth: 0,
                paddingTop: '4px',
              }}
            >
              {/* 用户名 + 成就标示（可拓展数组渲染） */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  marginBottom: '2px',
                  paddingLeft: '19px',
                }}
              >
                <span
                  style={{
                    color: msg.isSystem ? '#aaa' : theme.userColor,
                    fontWeight: 700,
                    fontSize: '14px',
                    flexShrink: 0,
                  }}
                >
                  {msg.user}
                </span>
                {msg.hasBadges && [
                  { color: '#FFD700', key: 'gold' },
                  { color: '#E53935', key: 'red' },
                ].map((badge) => (
                  <span
                    key={badge.key}
                    style={{
                      width: '10px',
                      height: '10px',
                      borderRadius: '50%',
                      background: badge.color,
                      display: 'inline-block',
                      flexShrink: 0,
                    }}
                  />
                ))}
              </div>

              {/* 信息栏：弹幕内容 */}
              <div
                style={{
                  background: msg.isVote ? 'rgba(255,215,0,0.15)' : theme.cardBg,
                  border: msg.isVote ? '1px solid rgba(255,215,0,0.4)' : theme.cardBorder,
                  borderRadius: '5px',
                  padding: '7px 14px',
                  paddingLeft: '21px',
                  color: msg.isVote ? '#FFD700' : theme.textColor,
                  fontSize: '14px',
                  fontWeight: 500,
                  wordBreak: 'break-all',
                  backdropFilter: 'blur(6px)',
                  WebkitBackdropFilter: 'blur(6px)',
                }}
              >
                {msg.content}
              </div>
            </div>
          </div>
        ))}
        <style>{`
          @keyframes danmuSlideDown {
            from { opacity: 0; transform: translateY(-10px); }
            to   { opacity: 1; transform: translateY(0); }
          }
        `}</style>
      </div>


    </div>
  )
}

export default Danmu
