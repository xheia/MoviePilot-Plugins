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
  search_enabled: true,
  download_enabled: true,
  download_path: '/media/music',
  download_format: 'flac',
  download_client: 'auto',
  spotify_client_id: '',
  spotify_client_secret: '',
  other_paths: 'spotify|https://open.spotify.com/playlist/demo|示例歌单\nkugou|12345|华语精选',
  bitmagnet_enabled: true,
  bitmagnet_url: 'http://192.168.1.100:3333',
  bitmagnet_api_key: '',
  bitmagnet_limit: 20,
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
        return { code: 0, version: '2.3.0', enabled: MOCK_CONFIG.enabled, username: '开发预览', logged_in: true, ncm_api_url: MOCK_CONFIG.ncm_api_url, media_servers: [{ title: 'Plex', value: 'Plex' }, { title: 'Emby', value: 'Emby' }], selected_servers: MOCK_CONFIG.media_server, config: { ...MOCK_CONFIG }, stats: { start_time: '2026-09-20 04:00:12', duration: 42.6, missing: 2, servers: ['Plex'], playlists: [{ server: 'Plex', source: '网易云', name: '我的收藏', total: 30, added: 28, missing: 2, status: 'ok', message: '' }] }, pending: summary(), history: historySummary(), bitmagnet: { enabled: MOCK_CONFIG.bitmagnet_enabled, url: MOCK_CONFIG.bitmagnet_url, configured: !!MOCK_CONFIG.bitmagnet_url, limit: MOCK_CONFIG.bitmagnet_limit } }
      }
      if (path.startsWith('/probe')) return { code: 0, message: 'ncm-api 连接正常（版本 3.9.2）', version: '3.9.2' }
      if (path.startsWith('/qrcode/status')) return { code: 0, status: 801, message: '等待扫码', logged_in: false, username: '' }
      if (path.startsWith('/history')) {
        return { code: 0, items: HISTORY, summary: historySummary() }
      }
      if (path.startsWith('/platforms')) {
        return {
          code: 0,
          platforms: [
            { name: 'netease', label: '网易云', available: true, reason: '' },
            { name: 'qq', label: 'QQ音乐', available: true, reason: '' },
            { name: 'spotify', label: 'Spotify', available: false, reason: '未配置 Spotify 的 client_id / client_secret' },
            { name: 'kugou', label: '酷狗', available: true, reason: '' },
            { name: 'kuwo', label: '酷我', available: true, reason: '' },
            { name: 'migu', label: '咪咕', available: true, reason: '' },
          ],
          search_platforms: ['netease', 'qq', 'spotify', 'kugou', 'kuwo', 'migu'],
          search_enabled: true,
          download_enabled: true,
        }
      }
      if (path.startsWith('/search')) {
        const kw = decodeURIComponent((path.split('keyword=')[1] || '').split('&')[0] || '')
        const q = kw || '示例歌'
        const results = [
          { platform: 'netease', source_id: 'n1', album_id: 'na1', title: q, artist: '周杰伦', album: '十一月的萧邦', duration_text: '04:20', links: { song: 'https://music.163.com/#/song?id=n1', album: '', artist: '' } },
          { platform: 'qq', source_id: 'q1', album_id: 'qa1', title: q, artist: '陈奕迅', album: 'U87', duration_text: '04:00', links: { song: 'https://y.qq.com/n/ryqq/songDetail/q1', album: '', artist: '' } },
          { platform: 'kugou', source_id: 'k1', album_id: 'ka1', title: q, artist: '薛之谦', album: '绅士', duration_text: '03:50', links: { song: '', album: '', artist: 'https://www.kugou.com/search?keyword=薛之谦' } },
        ]
        return { code: 0, keyword: q, count: results.length, results, platforms: ['netease', 'qq', 'kugou'], errors: {} }
      }
      if (path.startsWith('/smartlist')) {
        const getp = k => { const m = (path.split('?')[1] || '').match(new RegExp(k + '=([^&]*)')); return m ? decodeURIComponent(m[1]) : '' }
        const seedTitle = getp('title') || '晴天'
        const seedArtist = getp('artist') || ''
        const base = [
          { platform: 'netease', source_id: 'a1', album_id: 'al1', title: '七里香', artist: '周杰伦', album: '七里香', duration_text: '04:10', score: 0.55, platform_label: '网易云', links: { song: 'https://music.163.com/#/song?id=a1', album: '', artist: '' } },
          { platform: 'netease', source_id: 'a2', album_id: 'al2', title: '稻香', artist: '周杰伦', album: '魔杰座', duration_text: '03:43', score: 0.53, platform_label: '网易云', links: { song: 'https://music.163.com/#/song?id=a2', album: '', artist: '' } },
          { platform: 'qq', source_id: 'b1', album_id: 'bl1', title: '晴天', artist: '林俊杰', album: '第二天堂', duration_text: '04:29', score: 0.23, platform_label: 'QQ音乐', links: { song: 'https://y.qq.com/n/ryqq/songDetail/b1', album: '', artist: '' } },
          { platform: 'kugou', source_id: 'c1', album_id: 'cl1', title: '演员', artist: '薛之谦', album: '绅士', duration_text: '04:00', score: 0.0, platform_label: '酷狗', links: { song: '', album: '', artist: 'https://www.kugou.com/search?keyword=薛之谦' } },
        ]
        return { code: 0, seed: { title: seedTitle, artist: seedArtist, album: '', platform: '' }, pool_size: base.length + 5, count: base.length, playlist: base }
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
      if (path.startsWith('/download')) {
        const p = (body && body.platform) || ''
        if (p === 'netease') {
          return { code: 0, ok: true, kind: 'direct', message: '已保存到 /media/music（演示：经 ncm-api 取直链）', path: '/media/music' }
        }
        if (MOCK_CONFIG.bitmagnet_enabled && MOCK_CONFIG.bitmagnet_url) {
          return {
            code: 0, ok: true, kind: 'torrent', source: 'bitmagnet', title: '周杰伦 - 叶惠美 [FLAC]',
            seeders: 12, leechers: 3,
            message: `${p || '该平台'} 未开放音频直链；已改用 bitmagnet 检索到种子「周杰伦 - 叶惠美 [FLAC]」（412.7MB，做种 12）`,
          }
        }
        return { code: 1, ok: false, kind: 'none', message: `${p || '该平台'} 未开放音频直链（或该内容为付费 / 试听片段），插件不做解密与绕过` }
      }
      if (path.startsWith('/bitmagnet/test')) {
        const url = (body && body.url) || MOCK_CONFIG.bitmagnet_url || ''
        if (!url) return { code: 1, message: '未配置 bitmagnet 服务地址', endpoint: '' }
        return { code: 0, ok: true, version: '0.10.1', endpoint: `${url.replace(/\/+$/, '')}/graphql`, message: 'bitmagnet 已连通（版本 0.10.1）' }
      }
      return { code: 0, message: 'mock: 已处理 ' + path }
    },
  }
}
