# 弹幕模块开发记录

## 项目环境

- **框架**: React 19 + Vite 8
- **目标平台**: OBS 浏览器源（分辨率 2560×1440）
- **B站弹幕库**: `blive-message-listener@0.5.4` + `tiny-bilibili-ws@1.0.2`
- **开发服务器**: Vite 预览服务器（端口 4173）
- **局域网地址**: `http://192.168.31.88:4173/?theme=green&roomId=544853`

---

## 已完成工作

### 1. 弹幕 UI 重构

- 头像尺寸固定 **44px**，带 **3px `#4CAF50` 绿色描边**
- 信息栏采用主题色背景 + 低圆角设计
- 文字区域内嵌缩进，整体视觉层次清晰
- 单条弹幕结构：`头像(左) + 信息栏(用户名+徽章+内容)`

### 2. 成就标示（黄/红圆点）

- 条件渲染黄点和红点成就标识
- 数据结构预留 `hasBadges` 字段，支持后续拓展更多徽章类型
- 徽章样式与信息栏主题色协调

### 3. 双模式弹幕系统

| 模式 | 触发条件 | 行为 |
|------|----------|------|
| **模拟模式** | URL 无 `roomId` 参数 | 每 800ms 自动生成随机测试弹幕 |
| **真实模式** | URL 包含 `roomId=xxx` | 自动连接 B站直播间，接收真实弹幕 |

两种模式无缝切换，无需手动配置。

### 4. `-352` WBI 签名修复

**问题**: B站 `getDanmuInfo` API 返回 `-352`（签名验证失败），导致无法获取弹幕服务器 token。

**解决**: 在 `vite-plugin-bili-proxy.js` 中实现完整 WBI 签名流程：

1. 调用 `spi` API 获取 `buvid3`
2. 调用 `nav` API 获取 WBI 密钥（`img_key` + `sub_key`）
3. 使用 MD5 + 混合密钥算法生成签名
4. 带签名请求 `getDanmuInfo`，认证通过

### 5. `uid: 0` 断连修复

**问题**: B站弹幕服务器拒绝 `uid: 0` 的匿名连接，WebSocket 直接断开（`close 1006`）。

**解决**: 从 `nav` API 获取登录用户的真实 `mid`，作为 `uid` 传入 WebSocket 认证参数。

### 6. 用户头像显示

**实现逻辑**:

- 弹幕到达时先显示基于用户名生成的**默认头像**（哈希颜色）
- 同时异步调用 `/api/bili/user?uid=xxx` 获取真实头像 URL
- 使用 `faceCache`（`useRef<Map>`）缓存已获取的头像，避免重复请求
- 获取成功后，通过 `setMessages` 更新该用户**所有历史弹幕**的头像

### 7. 头像 403 修复

**问题**: B站头像 CDN（`hdslb.com`）对 `Referer` 严格校验，非 B站域名请求返回 403。

**解决**: 在 `<img>` 标签上添加 `referrerPolicy="no-referrer"`，并在 `onError` 中回退到默认头像：

```jsx
<img
  src={msg.avatar}
  alt=""
  referrerPolicy="no-referrer"
  onError={(e) => { e.target.src = getAvatar(msg.user) }}
/>
```

### 8. `expression_map.json` 修复

**问题**: `src/assets/expression_map.json` 原为空数组 `[]`，右侧牌桌组件尝试 `.find()` 时报错。

**解决**: 改为标准对象结构 `{ "mapping": [] }`，作为临时占位。后续由负责牌桌模块的同事补充真实表情数据。

---

## 关键文件变更

| 文件 | 说明 |
|------|------|
| `vite-plugin-bili-proxy.js` | B站代理插件：WBI 签名、弹幕认证、用户信息查询 |
| `src/danmuku.jsx` | 弹幕组件：UI 渲染、WebSocket 连接、头像管理 |
| `src/main.jsx` | 移除 `React.StrictMode`，避免双重 effect 导致重复连接 |
| `src/assets/expression_map.json` | 表情映射占位文件 |
| `public/config.json` | B站 Cookie 与静态部署 fallback 配置 |

---

## 重要技术细节

### WBI 签名依赖链

```
spi → buvid3
  ↓
nav → WBI 密钥 + 真实 uid(mid)
  ↓
getDanmuInfo → token + host_list
```

- `getDanmuInfo` **必须同时携带** `SESSDATA` 和 `buvid3`，否则返回 `-352`
- `uid` 必须是从 `nav` 获取的真实 `mid`，`uid: 0` 会被服务器拒绝

### 静态部署注意事项

`/api/bili/auth` 仅在 Vite 开发/预览服务器中生效。若使用 nginx 等静态部署，需手动在 `public/config.json` 中填写：

- `token`
- `buvid`
- `host`
- `port`

### 已知待优化项

1. **头像请求频率**: 大量不同用户涌入时，可能触发 B站 API 限制
2. **`uid === 0` 的匿名弹幕**: 未做过滤，会发起无效请求
3. **请求失败无重试**: 头像获取失败后，该用户永久使用默认头像
4. **`expression_map.json`**: 当前为空映射，等待补充真实数据

---

## 调试手段

若再次出现重复弹幕或其他异常，已通过 `console.log` 注入以下计数器：

- `useEffect` 执行计数
- `onIncomeDanmu` 调用计数

凭日志可定位是 React 重渲染导致还是 WebSocket 重复推送导致。
