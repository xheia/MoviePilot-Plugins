// 本地开发壳用的假接口：模拟宿主注入的 props.api（路径前缀已省略，直接按 path 分发）。
// 仅用于 `npm run dev` 预览，不参与联邦构建产物。

const MOCK_CONFIG = {
  enabled: true,
  onlyonce: false,
  cron: '0 4 * * *',
  media_server: ['Plex'],
  exact_match: true,
  ncm_api_url: 'http://192.168.1.100:1630',
  login_type: 'qrcode',
  wylogin_user: '',
  wylogin_password: '',
  wylogin_cookie: '',
  wymusic_paths: '123456789:我的收藏\nhttps://music.163.com/playlist?id=987654321:午后咖啡',
  wy_daily_list: false,
  wy_daily_song: false,
  qqmusic_paths: '8888888888:QQ 精选',
  qishui_paths: '',
}

const PENDING = [
  { seq: 1, key: '我记得 赵雷', title: '我记得', artist: '赵雷', album: '署前街少年', duration: 329, duration_text: '05:29', source: '网易云', server: 'Plex', playlist: '我的收藏', hits: 2, first_time: '2026-09-20 04:00:12', last_time: '2026-09-20 04:00:12', subscribed: false, subscribe_type: '', subscribe_id: 0, subscribe_time: '', subscribe_message: '' },
  { seq: 2, key: '红豆 王菲', title: '红豆', artist: '王菲', album: '畅游', duration: 256, duration_text: '04:16', source: '网易云', server: 'Plex', playlist: '午后咖啡', hits: 1, first_time: '2026-09-20 04:00:12', last_time: '2026-09-20 04:00:12', subscribed: false, subscribe_type: '', subscribe_id: 0, subscribe_time: '', subscribe_message: '' },
  { seq: 3, key: '晴天 周杰伦', title: '晴天', artist: '周杰伦', album: '叶惠美', duration: 269, duration_text: '04:29', source: 'QQ音乐', server: 'Plex', playlist: 'QQ 精选', hits: 3, first_time: '2026-09-20 04:00:12', last_time: '2026-09-20 04:00:12', subscribed: true, subscribe_type: 'song', subscribe_id: 1024, subscribe_time: '2026-09-20 09:12:30', subscribe_message: '订阅成功' },
]

function summary() {
  const total = PENDING.length
  const subs = PENDING.filter(i => i.subscribed).length
  return { total, pending: total - subs, subscribed: subs }
}

export function createMockApi() {
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
  return {
    async get(path) {
      await delay(120)
      if (path.startsWith('/status')) {
        return { code: 0, version: '2.0.0', enabled: MOCK_CONFIG.enabled, username: '开发预览', logged_in: true, ncm_api_url: MOCK_CONFIG.ncm_api_url, login_type: MOCK_CONFIG.login_type, login_types: [{ value: 'qrcode', label: '扫码登录' }, { value: 'captcha', label: '手机验证码' }, { value: 'password', label: '账号密码' }, { value: 'cookie', label: '手动粘贴 Cookie' }], media_servers: [{ title: 'Plex', value: 'Plex' }, { title: 'Emby', value: 'Emby' }], selected_servers: MOCK_CONFIG.media_server, config: { ...MOCK_CONFIG }, stats: { start_time: '2026-09-20 04:00:12', duration: 42.6, missing: 2, servers: ['Plex'], playlists: [{ server: 'Plex', source: '网易云', name: '我的收藏', total: 30, added: 28, missing: 2, status: 'ok', message: '' }] }, pending: summary() }
      }
      if (path.startsWith('/probe')) return { code: 0, message: 'ncm-api 连接正常（版本 3.9.2）', version: '3.9.2' }
      if (path.startsWith('/qrcode/status')) return { code: 0, status: 801, message: '等待扫码', logged_in: false, username: '' }
      if (path.startsWith('/pending')) {
        return { code: 0, items: PENDING, summary: summary(), stats: {}, targets: [{ value: 'song', label: '歌曲' }, { value: 'album', label: '专辑' }] }
      }
      return { code: 1, message: 'mock: 未知路径 ' + path }
    },
    async post(path, body) {
      await delay(160)
      if (path.startsWith('/qrcode') && !path.includes('/status')) {
        return { code: 0, message: '请使用网易云音乐 App 扫码', key: 'mock-key', qrimg: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180"><rect width="180" height="180" fill="#fff"/><text x="90" y="95" font-size="14" text-anchor="middle">二维码占位</text></svg>') }
      }
      if (path.startsWith('/logout')) return { code: 0, message: '已退出网易云登录' }
      if (path.startsWith('/run')) return { code: 0, message: '已触发同步，将在 3 秒后开始' }
      if (path.startsWith('/pending/subscribe')) {
        const items = (body && body.items) || []
        return { code: 0, message: `订阅完成：成功 ${items.length}，失败 0`, results: items.map(i => ({ seq: i.seq, title: '演示', target: i.target, ok: true, message: '订阅成功' })), summary: summary() }
      }
      if (path.startsWith('/pending/remove')) return { code: 0, message: '已移除 0 条', removed: 0, summary: summary() }
      if (path.startsWith('/pending/clear')) return { code: 0, message: '已清理全部 0 条', removed: 0, summary: summary() }
      if (path.startsWith('/login')) return { code: 0, message: '登录成功：开发预览', username: '开发预览' }
      if (path.startsWith('/captcha/send')) return { code: 0, message: '验证码已发送' }
      return { code: 0, message: 'mock: 已处理 ' + path }
    },
  }
}
