// 本地开发壳用的假接口：模拟宿主注入的 props.api（路径前缀已省略，直接按 path 分发）。
// 仅用于 `npm run dev` 预览，不参与联邦构建产物。

const MOCK_CONFIG = {
  enabled: true,
  cron: '0 4 * * *',
  media_server: ['Plex'],
  exact_match: true,
  subscribe_user: '歌单订阅',
  ncm_api_url: 'http://192.168.1.100:1630',
  wymusic_paths: '123456789:我的收藏\nhttps://music.163.com/playlist?id=987654321:午后咖啡',
  wy_daily_list: false,
  wy_daily_song: false,
  qqmusic_paths: '8888888888:QQ 精选',
  qishui_paths: '',
}

const PENDING = [
  { seq: 1, key: '我记得 赵雷', title: '我记得', artist: '赵雷', album: '署前街少年', duration: 329, duration_text: '05:29', source: '网易云', server: 'Plex', playlist: '我的收藏', hits: 2, first_time: '2026-09-20 04:00:12', last_time: '2026-09-20 04:00:12', subscribe_message: '' },
  { seq: 2, key: '红豆 王菲', title: '红豆', artist: '王菲', album: '畅游', duration: 256, duration_text: '04:16', source: '网易云', server: 'Plex', playlist: '午后咖啡', hits: 1, first_time: '2026-09-20 04:00:12', last_time: '2026-09-20 04:00:12', subscribe_message: '' },
  { seq: 3, key: '晴天 周杰伦', title: '晴天', artist: '周杰伦', album: '叶惠美', duration: 269, duration_text: '04:29', source: 'QQ音乐', server: 'Plex', playlist: 'QQ 精选', hits: 3, first_time: '2026-09-20 04:00:12', last_time: '2026-09-20 04:00:12', subscribe_message: '没有找到可订阅的音乐信息' },
]

const HISTORY = [
  { seq: 2, key: '起风了 买辣椒也用券', title: '起风了', artist: '买辣椒也用券', album: '起风了', duration_text: '05:26', target: 'song', music_type: 'recording', subscribe_id: 42, keyword: '买辣椒也用券 起风了', source: 'musicbrainz', media_id: 'mb-001', origin: '网易云', playlist: '我的收藏', user: '歌单订阅', time: '2026-09-22 21:04:11', links: { song: 'https://musicbrainz.org/recording/mb-001', album: 'https://musicbrainz.org/release/mb-album-1', artist: 'https://musicbrainz.org/artist/mb-artist-1' } },
  { seq: 1, key: '署前街少年 赵雷', title: '署前街少年', artist: '赵雷', album: '署前街少年', duration_text: '05:29', target: 'album', music_type: 'album', subscribe_id: 41, keyword: '署前街少年', source: 'musicbrainz', media_id: 'mb-album-2', origin: '网易云', playlist: '我的收藏', user: '歌单订阅', time: '2026-09-22 21:03:50', links: { song: '', album: 'https://musicbrainz.org/release/mb-album-2', artist: 'https://musicbrainz.org/artist/mb-artist-2' } },
]

function summary() {
  const total = PENDING.length
  const failed = PENDING.filter(i => !!(i.subscribe_message || '')).length
  return { total, failed }
}

function historySummary() {
  return {
    total: HISTORY.length,
    song: HISTORY.filter(i => i.target === 'song').length,
    album: HISTORY.filter(i => i.target === 'album').length,
  }
}

export function createMockApi() {
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
  return {
    async get(path) {
      await delay(120)
      if (path.startsWith('/status')) {
        return { code: 0, version: '2.2.0', enabled: MOCK_CONFIG.enabled, username: '开发预览', logged_in: true, ncm_api_url: MOCK_CONFIG.ncm_api_url, media_servers: [{ title: 'Plex', value: 'Plex' }, { title: 'Emby', value: 'Emby' }], selected_servers: MOCK_CONFIG.media_server, config: { ...MOCK_CONFIG }, stats: { start_time: '2026-09-20 04:00:12', duration: 42.6, missing: 2, servers: ['Plex'], playlists: [{ server: 'Plex', source: '网易云', name: '我的收藏', total: 30, added: 28, missing: 2, status: 'ok', message: '' }] }, pending: summary(), history: historySummary() }
      }
      if (path.startsWith('/probe')) return { code: 0, message: 'ncm-api 连接正常（版本 3.9.2）', version: '3.9.2' }
      if (path.startsWith('/qrcode/status')) return { code: 0, status: 801, message: '等待扫码', logged_in: false, username: '' }
      if (path.startsWith('/history')) {
        return { code: 0, items: HISTORY, summary: historySummary() }
      }
      if (path.startsWith('/pending')) {
        return { code: 0, items: PENDING, summary: summary(), stats: {}, history: historySummary(), targets: [{ value: 'song', label: '歌曲' }, { value: 'album', label: '专辑' }] }
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
        return { code: 0, message: `订阅完成：成功 ${items.length}，失败 0`, results: items.map(i => ({ seq: i.seq, title: '演示', target: i.target, ok: true, message: '订阅成功' })), summary: summary(), history: historySummary() }
      }
      if (path.startsWith('/pending/remove')) return { code: 0, message: '已移除 0 条', removed: 0, summary: summary() }
      if (path.startsWith('/pending/clear')) return { code: 0, message: '已清理全部 0 条', removed: 0, summary: summary() }
      if (path.startsWith('/pending/link')) {
        return { code: 0, seq: (body && body.seq) || 0, title: '演示', links: { song: 'https://musicbrainz.org/recording/mb-001', album: '', artist: 'https://musicbrainz.org/artist/mb-artist-1' } }
      }
      if (path.startsWith('/history/clear')) return { code: 0, message: '已清空订阅历史 0 条', removed: 0, summary: historySummary() }
      return { code: 0, message: 'mock: 已处理 ' + path }
    },
  }
}
