<template>
  <section class="ms-page">
    <!-- 头部 -->
    <header class="ms-head">
      <div class="ms-head__brand">
        <div class="ms-head__logo"><v-icon icon="mdi-magnify" size="20" /></div>
        <div>
          <div class="ms-head__crumbs">
            <span>MoviePilot</span>
            <v-icon icon="mdi-chevron-right" size="13" />
            <span>插件</span>
          </div>
          <h1 class="ms-head__title">搜索 / 下载 / 智能歌单</h1>
        </div>
      </div>
      <div class="ms-head__actions">
        <v-btn v-if="show_switch" variant="text" prepend-icon="mdi-cog-outline" @click="emit('switch')">同步配置</v-btn>
        <v-btn icon="mdi-refresh" size="small" variant="text" :loading="searching" aria-label="刷新" @click="loadPlatforms()" />
        <v-btn icon="mdi-close" size="small" variant="text" aria-label="关闭" @click="emit('close')" />
      </div>
    </header>

    <div class="ms-tabs">
      <button type="button" :class="['ms-tab', { 'ms-tab--active': view === 'search' }]" @click="view = 'search'">跨平台搜索</button>
      <button type="button" :class="['ms-tab', { 'ms-tab--active': view === 'smartlist' }]" @click="loadPlatforms(); view = 'smartlist'">智能歌单</button>
    </div>

    <v-alert v-if="error" class="mx-3 mb-2" density="compact" type="warning" variant="tonal">{{ error }}</v-alert>
    <v-alert v-if="result" class="mx-3 mb-2" density="compact" :type="resultLevel" variant="tonal">{{ result }}</v-alert>

    <!-- 跨平台搜索 -->
    <div v-if="view === 'search'" class="ms-body">
      <div class="ms-search">
        <v-text-field v-model="keyword" class="ms-search__kw" density="compact" variant="outlined"
          label="关键词（歌名 / 歌手 / 专辑）" prepend-inner-icon="mdi-magnify" hide-details single-line
          @keyup.enter="doSearch" />
        <v-select v-model="selPlatforms" :items="availablePlatforms" class="ms-search__pf" density="compact"
          variant="outlined" label="平台" hide-details multiple chips closable-chips />
        <v-btn color="primary" variant="flat" prepend-icon="mdi-magnify" :loading="searching" @click="doSearch">搜索</v-btn>
      </div>
      <p v-if="!searchEnabled" class="ms-hint-inline">搜索功能未开启（请在「搜索与下载」配置页打开开关）。</p>

      <div v-if="searchResults.length" class="ms-table-wrap">
        <table class="ms-table">
          <thead>
            <tr>
              <th>平台</th>
              <th>歌曲名称</th>
              <th>歌手</th>
              <th>专辑</th>
              <th class="col-dur">时长</th>
              <th class="col-link">来源链接</th>
              <th class="col-act">下载</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in searchResults" :key="`${row.platform}-${row.source_id}-${i}`">
              <td><span class="ms-src">{{ platformLabel(row.platform) }}</span></td>
              <td>
                <div class="ms-title">{{ row.title }}</div>
              </td>
              <td>{{ row.artist || '-' }}</td>
              <td>{{ row.album || '-' }}</td>
              <td class="col-dur">{{ row.duration_text || '-' }}</td>
              <td class="col-link">
                <span v-for="l in linkEntries(row.links)" :key="l.key">
                  <a v-if="l.url" :href="l.url" target="_blank" rel="noopener">{{ l.label }}</a>
                  <span v-else class="ms-link-off">{{ l.label }}</span>
                </span>
              </td>
              <td class="col-act">
                <v-btn size="x-small" variant="tonal" :loading="downloading === i"
                  @click="doDownload(row, i)">下载</v-btn>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="searched" class="ms-empty">没有搜到结果，换个关键词或平台试试。</div>
      <div v-else class="ms-empty">输入关键词开始跨平台搜索。</div>
    </div>

    <!-- 智能歌单生成 -->
    <div v-else class="ms-body">
      <div class="ms-smart">
        <v-text-field v-model="seedTitle" class="ms-smart__title" density="compact" variant="outlined"
          label="种子：歌名（必填）" hide-details />
        <v-text-field v-model="seedArtist" class="ms-smart__artist" density="compact" variant="outlined"
          label="种子：歌手（可选）" hide-details />
        <v-text-field v-model="seedKeyword" class="ms-smart__kw" density="compact" variant="outlined"
          label="候选池关键词（可选，默认按种子歌手）" hide-details />
        <v-text-field v-model.number="seedSize" type="number" class="ms-smart__size" density="compact"
          variant="outlined" label="歌单长度" hide-details />
        <v-btn color="primary" variant="flat" prepend-icon="mdi-auto-fix" :loading="generating"
          @click="doSmartlist">生成歌单</v-btn>
      </div>
      <p class="ms-hint-inline">算法：以种子曲目为基调，按「同歌手 / 同专辑 / 标题 · 专辑 token 重合」打相似度，
        并限制同一歌手最多保留 3 首以保证多样性。候选来自本地已采集曲目 + 跨平台搜索。</p>

      <div v-if="smartRows.length" class="ms-table-wrap">
        <table class="ms-table">
          <thead>
            <tr>
              <th class="col-score">相似度</th>
              <th>平台</th>
              <th>歌曲名称</th>
              <th>歌手</th>
              <th>专辑</th>
              <th class="col-link">来源链接</th>
              <th class="col-act">下载</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in smartRows" :key="`smart-${row.platform}-${row.source_id}-${i}`">
              <td class="col-score">
                <v-progress-linear :model-value="row.score * 100" color="primary" height="6" rounded />
                <span class="ms-score-num">{{ row.score.toFixed(2) }}</span>
              </td>
              <td><span class="ms-src">{{ row.platform_label }}</span></td>
              <td><div class="ms-title">{{ row.title }}</div></td>
              <td>{{ row.artist || '-' }}</td>
              <td>{{ row.album || '-' }}</td>
              <td class="col-link">
                <span v-for="l in linkEntries(row.links)" :key="l.key">
                  <a v-if="l.url" :href="l.url" target="_blank" rel="noopener">{{ l.label }}</a>
                  <span v-else class="ms-link-off">{{ l.label }}</span>
                </span>
              </td>
              <td class="col-act">
                <v-btn size="x-small" variant="tonal" :loading="downloading === `s${i}`"
                  @click="doDownload(row, `s${i}`)">下载</v-btn>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="generated" class="ms-empty">没有生成候选，换个种子或关键词试试。</div>
      <div v-else class="ms-empty">填写种子歌名后点「生成歌单」。</div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  show_switch: { type: Boolean, default: true },
})
const emit = defineEmits(['switch', 'close', 'action'])

const PLUGIN = 'plugin/MusicSubscribe'
const PLATFORM_LABELS = {
  netease: '网易云', qq: 'QQ音乐', spotify: 'Spotify',
  kugou: '酷狗', kuwo: '酷我', migu: '咪咕',
}

const view = ref('search')
const keyword = ref('')
const selPlatforms = ref([])
const searchResults = ref([])
const searching = ref(false)
const searched = ref(false)
const searchEnabled = ref(false)
const downloading = ref(null)
const platforms = ref([])

const seedTitle = ref('')
const seedArtist = ref('')
const seedKeyword = ref('')
const seedSize = ref(20)
const smartRows = ref([])
const generating = ref(false)
const generated = ref(false)

const error = ref('')
const result = ref('')
const resultLevel = ref('success')

const availablePlatforms = computed(() =>
  platforms.value.filter(p => p.available).map(p => ({ title: p.label, value: p.name })))

function platformLabel(name) {
  return PLATFORM_LABELS[name] || name || '未知'
}

function linkEntries(links) {
  const got = links || {}
  return [
    { key: 'song', label: '歌曲', url: got.song || '' },
    { key: 'album', label: '专辑', url: got.album || '' },
    { key: 'artist', label: '歌手', url: got.artist || '' },
  ]
}

function call(method, path, data) {
  const fn = props?.api?.[method]
  if (typeof fn !== 'function') throw new Error('API 不可用')
  return data === undefined ? fn(path) : fn(path, data)
}

async function loadPlatforms() {
  try {
    const res = await call('get', `${PLUGIN}/platforms`)
    platforms.value = Array.isArray(res?.platforms) ? res.platforms : []
    searchEnabled.value = !!res?.search_enabled
    if (selPlatforms.value.length === 0) {
      selPlatforms.value = platforms.value.filter(p => p.available).map(p => p.name)
    }
  } catch (e) {
    error.value = '加载平台列表失败：' + (e?.message || e)
  }
}

async function doSearch() {
  if (!keyword.value.trim()) {
    result.value = '请先输入搜索关键词'
    resultLevel.value = 'warning'
    return
  }
  searching.value = true
  error.value = ''
  result.value = ''
  try {
    const params = `keyword=${encodeURIComponent(keyword.value.trim())}`
      + `&limit=20`
      + (selPlatforms.value.length ? `&platforms=${encodeURIComponent(selPlatforms.value.join(','))}` : '')
    const res = await call('get', `${PLUGIN}/search?${params}`)
    if (res?.code === 0) {
      searchResults.value = Array.isArray(res.results) ? res.results : []
      searched.value = true
      const errCount = Object.keys(res.errors || {}).length
      resultLevel.value = searchResults.value.length ? 'success' : 'info'
      result.value = `搜索到 ${searchResults.value.length} 条${errCount ? `（${errCount} 个平台出错）` : ''}`
    } else {
      resultLevel.value = 'error'
      result.value = res?.message || '搜索失败'
    }
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '搜索失败：' + (e?.message || e)
  } finally {
    searching.value = false
    emit('action')
  }
}

async function doDownload(row, idx) {
  downloading.value = idx
  result.value = ''
  try {
    const res = await call('post', `${PLUGIN}/download`, {
      platform: row.platform, source_id: row.source_id, album_id: row.album_id,
      title: row.title, artist: row.artist, album: row.album,
    })
    resultLevel.value = res?.code === 0 ? 'success' : 'error'
    result.value = res?.message || (res?.code === 0 ? '已处理' : '下载失败')
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '下载失败：' + (e?.message || e)
  } finally {
    downloading.value = null
  }
}

async function doSmartlist() {
  if (!seedTitle.value.trim()) {
    result.value = '请先填写种子歌名'
    resultLevel.value = 'warning'
    return
  }
  generating.value = true
  error.value = ''
  result.value = ''
  try {
    const params = `title=${encodeURIComponent(seedTitle.value.trim())}`
      + `&artist=${encodeURIComponent(seedArtist.value.trim())}`
      + `&size=${Number(seedSize.value) || 20}`
      + (seedKeyword.value.trim() ? `&keyword=${encodeURIComponent(seedKeyword.value.trim())}` : '')
    const res = await call('get', `${PLUGIN}/smartlist?${params}`)
    if (res?.code === 0) {
      smartRows.value = Array.isArray(res.playlist) ? res.playlist : []
      generated.value = true
      resultLevel.value = smartRows.value.length ? 'success' : 'info'
      result.value = `生成 ${smartRows.value.length} 首（候选池 ${res.pool_size || 0} 首）`
    } else {
      resultLevel.value = 'error'
      result.value = res?.message || '生成失败'
    }
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '生成失败：' + (e?.message || e)
  } finally {
    generating.value = false
    emit('action')
  }
}

onMounted(loadPlatforms)
</script>

<style scoped>
.ms-page {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: rgb(var(--v-theme-surface));
  color: rgba(var(--v-theme-on-surface), 0.92);
}

.ms-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px 8px;
}

.ms-head__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.ms-head__logo {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: rgba(var(--v-theme-primary), 0.14);
  color: rgb(var(--v-theme-primary));
}

.ms-head__crumbs {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 0.72rem;
  color: rgba(var(--v-theme-on-surface), 0.5);
}

.ms-head__title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.2;
}

.ms-head__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.ms-tabs {
  display: flex;
  gap: 4px;
  padding: 0 16px 8px;
}

.ms-tab {
  padding: 5px 14px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 999px;
  background: transparent;
  color: rgba(var(--v-theme-on-surface), 0.7);
  font-size: 0.8rem;
  cursor: pointer;
}

.ms-tab--active {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.12);
  color: rgb(var(--v-theme-primary));
  font-weight: 600;
}

.ms-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 0 16px 16px;
}

.ms-search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 0 12px;
}

.ms-search__kw { flex: 1 1 240px; min-width: 200px; }
.ms-search__pf { flex: 0 0 220px; min-width: 180px; }

.ms-smart {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 0 12px;
}

.ms-smart__title { flex: 1 1 200px; min-width: 160px; }
.ms-smart__artist { flex: 0 0 160px; min-width: 140px; }
.ms-smart__kw { flex: 1 1 240px; min-width: 180px; }
.ms-smart__size { flex: 0 0 110px; min-width: 90px; }

.ms-hint-inline {
  margin: 0 0 12px;
  font-size: 0.78rem;
  line-height: 1.6;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.ms-table-wrap {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  border-radius: 10px;
  overflow: hidden;
}

.ms-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}

.ms-table th,
.ms-table td {
  padding: 8px 6px;
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  text-align: left;
  vertical-align: middle;
}

.ms-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: rgb(var(--v-theme-surface));
  font-weight: 700;
  color: rgba(var(--v-theme-on-surface), 0.6);
  white-space: nowrap;
}

.ms-title { font-weight: 600; }
.ms-src { color: rgba(var(--v-theme-primary), 0.9); }
.col-dur { width: 66px; white-space: nowrap; }
.col-act { width: 80px; white-space: nowrap; }
.col-score { width: 120px; }

.ms-score-num {
  display: inline-block;
  margin-top: 2px;
  font-size: 0.72rem;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.col-link { width: 150px; white-space: nowrap; }

.col-link a {
  margin-right: 8px;
  color: rgb(var(--v-theme-primary));
  text-decoration: none;
}

.col-link a:hover { text-decoration: underline; }

.ms-link-off {
  margin-right: 8px;
  color: rgba(var(--v-theme-on-surface), 0.28);
}

.ms-empty {
  padding: 28px 8px;
  text-align: center;
  font-size: 0.85rem;
  color: rgba(var(--v-theme-on-surface), 0.55);
}
</style>
