<template>
  <section class="ms-page">
    <!-- 头部 -->
    <header class="ms-head">
      <div class="ms-head__brand">
        <div class="ms-head__logo"><v-icon icon="mdi-playlist-music" size="20" /></div>
        <div>
          <div class="ms-head__crumbs">
            <span>MoviePilot</span>
            <v-icon icon="mdi-chevron-right" size="13" />
            <span>插件</span>
          </div>
          <h1 class="ms-head__title">库内缺失曲目</h1>
        </div>
      </div>
      <div class="ms-head__actions">
        <v-btn v-if="show_switch" variant="text" prepend-icon="mdi-cog-outline" @click="emit('switch')">同步配置</v-btn>
        <v-btn icon="mdi-refresh" size="small" variant="text" :loading="loading" aria-label="刷新"
          @click="load()" />
        <v-btn icon="mdi-close" size="small" variant="text" aria-label="关闭" @click="emit('close')" />
      </div>
    </header>

    <!-- 视图切换 -->
    <div class="ms-tabs">
      <button type="button" :class="['ms-tab', { 'ms-tab--active': view === 'pending' }]"
        @click="switchView('pending')">待订阅清单</button>
      <button type="button" :class="['ms-tab', { 'ms-tab--active': view === 'history' }]"
        @click="switchView('history')">订阅历史</button>
    </div>

    <!-- 概览 -->
    <div class="ms-stats">
      <button v-for="s in statCards" :key="s.key" type="button"
        :class="['ms-stat', { 'ms-stat--active': view === 'pending' && scope === s.key }]"
        @click="switchScope(s.key)">
        <span class="ms-stat__num">{{ s.count }}</span>
        <span class="ms-stat__label">{{ s.label }}</span>
      </button>
      <button type="button" :class="['ms-stat', { 'ms-stat--active': view === 'history' }]"
        @click="switchView('history')">
        <span class="ms-stat__num">{{ historySummary.total }}</span>
        <span class="ms-stat__label">订阅历史</span>
      </button>
      <div class="ms-stat ms-stat--plain">
        <span class="ms-stat__num">{{ syncMissing }}</span>
        <span class="ms-stat__label">上次同步缺失</span>
      </div>
    </div>

    <v-alert v-if="error" class="mx-3 mb-2" density="compact" type="warning" variant="tonal">{{ error }}</v-alert>
    <v-alert v-if="result" class="mx-3 mb-2" density="compact"
      :type="resultLevel" variant="tonal">{{ result }}</v-alert>

    <!-- 工具条 -->
    <div class="ms-toolbar">
      <div v-if="view === 'pending'" class="ms-toolbar__group">
        <v-btn size="small" variant="tonal" @click="selectAll('song')">全选</v-btn>
        <v-btn size="small" variant="tonal" @click="invert">
          反选
          <v-tooltip activator="parent" location="bottom"
            text="未勾选 → 歌曲；已选歌曲 → 专辑；已选专辑 → 取消" />
        </v-btn>
        <v-btn size="small" variant="text" :disabled="!pickedCount" @click="clearPick">清空选择</v-btn>
      </div>
      <v-text-field v-model="keyword" class="ms-toolbar__search" density="compact" variant="outlined"
        :placeholder="view === 'history' ? '搜索订阅历史：歌名 / 歌手 / 专辑' : '搜索歌名 / 歌手 / 专辑'"
        prepend-inner-icon="mdi-magnify" hide-details single-line />
      <v-select v-if="view === 'pending'" v-model="sourceFilter" :items="sourceOptions"
        class="ms-toolbar__source" density="compact" variant="outlined" label="数据源" hide-details
        single-line clearable />
      <v-select v-else v-model="targetFilter" :items="targetOptions" class="ms-toolbar__source"
        density="compact" variant="outlined" label="订阅粒度" hide-details single-line clearable />
    </div>

    <!-- 清单表格 -->
    <div class="ms-body">
      <div v-if="loading" class="ms-empty">加载中…</div>
      <template v-else>
        <table v-if="view === 'pending' && pagedRows.length" class="ms-table">
          <thead>
            <tr>
              <th class="col-seq">序号</th>
              <th class="col-pick">选择歌曲</th>
              <th class="col-pick">选择专辑</th>
              <th>歌曲名称</th>
              <th class="col-dur">时长</th>
              <th>歌手</th>
              <th>专辑名称</th>
              <th class="col-link">官方链接</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pagedRows" :key="row.seq" :class="{ 'ms-row--fail': row.subscribe_message }">
              <td class="col-seq">{{ row.seq }}</td>
              <td class="col-pick">
                <input type="radio" :name="`pick-${row.seq}`" :checked="picks[row.seq] === 'song'"
                  @change="pick(row, 'song')" />
              </td>
              <td class="col-pick">
                <input type="radio" :name="`pick-${row.seq}`" :checked="picks[row.seq] === 'album'"
                  @change="pick(row, 'album')" />
              </td>
              <td>
                <div class="ms-title">{{ row.title }}</div>
                <div class="ms-sub">
                  <span class="ms-src">{{ row.source }}</span>
                  <span v-if="row.hits > 1"> · 命中 {{ row.hits }} 次</span>
                  <span v-if="row.subscribe_message" class="ms-fail"> ·
                    上次订阅失败：{{ row.subscribe_message }}</span>
                </div>
              </td>
              <td class="col-dur">{{ row.duration_text || '-' }}</td>
              <td>{{ row.artist || '-' }}</td>
              <td>{{ row.album || '-' }}</td>
              <td class="col-link">
                <button v-if="!linkCache[row.seq]" type="button" class="ms-linkbtn"
                  :disabled="linking === row.seq" @click="loadLink(row)">
                  {{ linking === row.seq ? '查询中…' : '查询链接' }}
                </button>
                <template v-else>
                  <span v-for="l in linkEntries(linkCache[row.seq])" :key="`${row.seq}-${l.key}`">
                    <a v-if="l.url" :href="l.url" target="_blank" rel="noopener">{{ l.label }}</a>
                    <span v-else class="ms-link-off">{{ l.label }}</span>
                  </span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 订阅历史 -->
        <table v-else-if="view === 'history' && pagedRows.length" class="ms-table">
          <thead>
            <tr>
              <th class="col-seq">序号</th>
              <th>歌曲名称</th>
              <th>歌手</th>
              <th>专辑名称</th>
              <th class="col-dur">时长</th>
              <th class="col-pick">粒度</th>
              <th>订阅人</th>
              <th class="col-time">订阅时间</th>
              <th class="col-link">官方链接</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pagedRows" :key="`h-${row.seq}`">
              <td class="col-seq">{{ row.seq }}</td>
              <td>
                <div class="ms-title">{{ row.title }}</div>
                <div class="ms-sub">
                  <span class="ms-src">{{ row.playlist || row.origin || '歌单' }}</span>
                  <span v-if="row.subscribe_id"> · 订阅 #{{ row.subscribe_id }}</span>
                  <span v-else-if="row.message"> · {{ row.message }}</span>
                </div>
              </td>
              <td>{{ row.artist || '-' }}</td>
              <td>{{ row.album || '-' }}</td>
              <td class="col-dur">{{ row.duration_text || '-' }}</td>
              <td class="col-pick">{{ row.target === 'album' ? '专辑' : '歌曲' }}</td>
              <td>{{ row.user || '-' }}</td>
              <td class="col-time">{{ row.time || '-' }}</td>
              <td class="col-link">
                <span v-for="l in linkEntries(row.links)" :key="`h-${row.seq}-${l.key}`">
                  <a v-if="l.url" :href="l.url" target="_blank" rel="noopener">{{ l.label }}</a>
                  <span v-else class="ms-link-off">{{ l.label }}</span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>

        <v-alert v-else-if="keyword || sourceFilter" density="compact" type="info" variant="tonal">
          没有匹配的记录，换个关键词试试。
        </v-alert>
        <div v-else-if="view === 'history'" class="ms-empty">
          还没有订阅历史 —— 在「待订阅清单」里勾选曲目点「订阅」，成功的条目会留档在这里。
        </div>
        <div v-else class="ms-empty">
          清单是空的 —— 先跑一次歌单同步，媒体库里搜不到的曲目会出现在这里。
        </div>
      </template>
    </div>

    <!-- 分页 -->
    <div v-if="rows.length" class="ms-pager">
      <v-select v-model="pageSize" :items="[20, 50, 100]" density="compact" variant="outlined" hide-details
        label="每页" class="ms-pager__size" />
      <span class="ms-pager__info">第 {{ page }} / {{ Math.max(1, pageCount) }} 页 · 共 {{ rows.length }} 条</span>
      <v-btn size="small" variant="text" :disabled="page <= 1" @click="page = page - 1">上一页</v-btn>
      <v-btn size="small" variant="text" :disabled="page >= pageCount" @click="page = page + 1">下一页</v-btn>
    </div>

    <!-- 底部动作 -->
    <footer v-if="view === 'pending'" class="ms-foot">
      <span class="ms-foot__count">已勾选 {{ pickedCount }} 条（歌曲 {{ countByTarget.song }} / 专辑
        {{ countByTarget.album }}）</span>
      <v-spacer />
      <v-menu location="top">
        <template #activator="{ props: menuProps }">
          <v-btn variant="text" prepend-icon="mdi-broom" v-bind="menuProps">清理</v-btn>
        </template>
        <v-list density="compact">
          <v-list-item title="清理订阅失败记录" @click="clearPending('failed')" />
          <v-list-item title="清空整个清单" @click="clearPending('all')" />
        </v-list>
      </v-menu>
      <v-btn variant="tonal" color="warning" prepend-icon="mdi-delete-outline" :disabled="!pickedCount"
        :loading="removing" @click="removePicked">移除</v-btn>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-bell-plus-outline" :disabled="!pickedCount"
        :loading="subscribing" @click="subscribePicked">订阅</v-btn>
    </footer>
    <footer v-else class="ms-foot">
      <span class="ms-foot__count">共 {{ historySummary.total }} 条订阅历史（歌曲
        {{ historySummary.song }} / 专辑 {{ historySummary.album }}），清理历史不会影响宿主的订阅列表</span>
      <v-spacer />
      <v-btn variant="tonal" color="warning" prepend-icon="mdi-broom"
        :disabled="!historySummary.total" :loading="clearingHistory" @click="clearHistory">清空历史</v-btn>
    </footer>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  show_switch: { type: Boolean, default: true },
})
const emit = defineEmits(['switch', 'close', 'action'])

const PLUGIN = 'plugin/MusicSubscribe'

const loading = ref(false)
const subscribing = ref(false)
const removing = ref(false)
const clearingHistory = ref(false)
const linking = ref(null)
const error = ref('')
const result = ref('')
const resultLevel = ref('success')

// pending = 待订阅清单，history = 订阅历史
const view = ref('pending')

const items = ref([])
const historyItems = ref([])
const summary = reactive({ total: 0, failed: 0 })
const historySummary = reactive({ total: 0, song: 0, album: 0 })
const stats = ref({})
const targets = ref([{ value: 'song', label: '歌曲' }, { value: 'album', label: '专辑' }])
const targetOptions = [{ value: 'song', label: '歌曲' }, { value: 'album', label: '专辑' }]
const targetFilter = ref(null)
// seq -> { song, album, artist }（按需查询，避免同步时给每首歌都做一次识别）
const linkCache = reactive({})

const scope = ref('all')
const keyword = ref('')
const sourceFilter = ref(null)
const page = ref(1)
const pageSize = ref(20)

// seq -> 'song' | 'album'
const picks = reactive({})

const syncMissing = computed(() => Number(stats.value?.missing) || 0)

const statCards = computed(() => [
  { key: 'all', label: '待处理', count: summary.total },
  { key: 'failed', label: '订阅失败', count: summary.failed },
])

const sourceOptions = computed(() => {
  const set = new Set(items.value.map(i => i.source).filter(Boolean))
  return [...set]
})

const pendingRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  let list = items.value
  if (scope.value === 'failed') list = list.filter(i => !!(i.subscribe_message || ''))
  if (sourceFilter.value) list = list.filter(i => i.source === sourceFilter.value)
  if (kw) {
    list = list.filter(i =>
      String(i.title || '').toLowerCase().includes(kw) ||
      String(i.artist || '').toLowerCase().includes(kw) ||
      String(i.album || '').toLowerCase().includes(kw))
  }
  return list
})

const historyRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  let list = historyItems.value
  if (targetFilter.value) list = list.filter(i => (i.target || 'song') === targetFilter.value)
  if (kw) {
    list = list.filter(i =>
      String(i.title || '').toLowerCase().includes(kw) ||
      String(i.artist || '').toLowerCase().includes(kw) ||
      String(i.album || '').toLowerCase().includes(kw))
  }
  return list
})

const rows = computed(() => (view.value === 'history' ? historyRows.value : pendingRows.value))

const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / Number(pageSize.value))))
const pagedRows = computed(() => {
  const size = Number(pageSize.value)
  return rows.value.slice((page.value - 1) * size, page.value * size)
})

const pickedCount = computed(() => {
  const alive = new Set(items.value.map(i => Number(i.seq)))
  return Object.keys(picks).filter(seq => picks[seq] && alive.has(Number(seq))).length
})

const countByTarget = computed(() => {
  const out = { song: 0, album: 0 }
  const alive = new Set(items.value.map(i => Number(i.seq)))
  Object.keys(picks).forEach(seq => {
    const t = picks[seq]
    if (t && alive.has(Number(seq)) && out[t] !== undefined) out[t] += 1
  })
  return out
})

function call(method, path, data) {
  const fn = props?.api?.[method]
  if (typeof fn !== 'function') throw new Error('API 不可用')
  return data === undefined ? fn(path) : fn(path, data)
}

async function load() {
  if (view.value === 'history') return loadHistory()
  loading.value = true
  error.value = ''
  try {
    const res = await call('get', `${PLUGIN}/pending?scope=${encodeURIComponent(scope.value)}`)
    items.value = Array.isArray(res?.items) ? res.items : []
    Object.assign(summary, res?.summary || { total: 0, failed: 0 })
    Object.assign(historySummary, res?.history || { total: 0, song: 0, album: 0 })
    stats.value = res?.stats || {}
    if (Array.isArray(res?.targets) && res.targets.length) targets.value = res.targets
    const alive = new Set(items.value.map(i => Number(i.seq)))
    Object.keys(picks).forEach(seq => { if (!alive.has(Number(seq))) delete picks[seq] })
    Object.keys(linkCache).forEach(seq => { if (!alive.has(Number(seq))) delete linkCache[seq] })
    if (page.value > pageCount.value) page.value = pageCount.value
  } catch (e) {
    error.value = '加载缺失清单失败：' + (e?.message || e)
    items.value = []
  } finally {
    loading.value = false
    emit('action')
  }
}

async function loadHistory() {
  loading.value = true
  error.value = ''
  try {
    const res = await call('get', `${PLUGIN}/history`)
    historyItems.value = Array.isArray(res?.items) ? res.items : []
    Object.assign(historySummary, res?.summary || { total: 0, song: 0, album: 0 })
    if (page.value > pageCount.value) page.value = pageCount.value
  } catch (e) {
    error.value = '加载订阅历史失败：' + (e?.message || e)
    historyItems.value = []
  } finally {
    loading.value = false
    emit('action')
  }
}

function switchView(next) {
  if (view.value === next) return load()
  view.value = next
  page.value = 1
  keyword.value = ''
  return load()
}

function switchScope(next) {
  view.value = 'pending'
  scope.value = next
}

async function loadLink(row) {
  const seq = Number(row.seq)
  linking.value = seq
  result.value = ''
  try {
    const res = await call('post', `${PLUGIN}/pending/link`, { seq })
    if (res?.code === 0) {
      linkCache[seq] = res.links || {}
    } else {
      resultLevel.value = 'warning'
      result.value = res?.message || '没查到官方链接'
    }
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '查询链接失败：' + (e?.message || e)
  } finally {
    linking.value = null
  }
}

async function clearHistory() {
  clearingHistory.value = true
  result.value = ''
  try {
    const res = await call('post', `${PLUGIN}/history/clear`)
    resultLevel.value = res?.code === 0 ? 'success' : 'error'
    result.value = res?.message || '已清空订阅历史'
    historyItems.value = []
    Object.assign(historySummary, res?.summary || { total: 0, song: 0, album: 0 })
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '清空订阅历史失败：' + (e?.message || e)
  } finally {
    clearingHistory.value = false
  }
}

function pick(row, target) {
  const seq = Number(row.seq)
  // 同一序号歌曲与专辑二选一：再次勾选时切换粒度
  picks[seq] = target
}

function selectAll() {
  pendingRows.value.forEach(row => { picks[Number(row.seq)] = 'song' })
}

function invert() {
  pendingRows.value.forEach(row => {
    const seq = Number(row.seq)
    const cur = picks[seq]
    if (!cur) picks[seq] = 'song'
    else if (cur === 'song') picks[seq] = row.album ? 'album' : undefined
    else delete picks[seq]
  })
}

function clearPick() {
  pendingRows.value.forEach(row => { delete picks[Number(row.seq)] })
}

function linkEntries(links) {
  const got = links || {}
  return [
    { key: 'song', label: '歌曲', url: got.song || '' },
    { key: 'album', label: '专辑', url: got.album || '' },
    { key: 'artist', label: '歌手', url: got.artist || '' },
  ]
}

async function subscribePicked() {
  const payload = Object.keys(picks)
    .map(seq => ({ seq: Number(seq), target: picks[seq] }))
    .filter(i => i.target)
  if (!payload.length) return
  subscribing.value = true
  error.value = ''
  result.value = ''
  try {
    const res = await call('post', `${PLUGIN}/pending/subscribe`, { items: payload })
    if (res?.code === 0) {
      const failed = (res.results || []).filter(r => !r.ok)
      const detail = failed.map(f => `${f.title}（${f.message}）`).slice(0, 3).join('；')
      resultLevel.value = failed.length ? 'warning' : 'success'
      result.value = failed.length
        ? `订阅完成：${payload.length - failed.length} 条订阅成功（可在「订阅历史」里查看），${failed.length} 条失败：${detail}`
        : (res.message || '订阅完成')
      clearPick()
      await load()
    } else {
      resultLevel.value = 'error'
      result.value = res?.message || '订阅失败'
    }
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '订阅失败：' + (e?.message || e)
  } finally {
    subscribing.value = false
  }
}

async function removePicked() {
  const seqs = Object.keys(picks).filter(seq => picks[seq]).map(Number)
  if (!seqs.length) return
  removing.value = true
  result.value = ''
  try {
    const res = await call('post', `${PLUGIN}/pending/remove`, { seqs })
    if (res?.code === 0) {
      seqs.forEach(s => delete picks[s])
      resultLevel.value = 'success'
      result.value = res.message || '已移除'
      await load()
    } else {
      resultLevel.value = 'error'
      result.value = res?.message || '移除失败'
    }
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '移除失败：' + (e?.message || e)
  } finally {
    removing.value = false
  }
}

async function clearPending(sc) {
  removing.value = true
  result.value = ''
  try {
    const res = await call('post', `${PLUGIN}/pending/clear?scope=${encodeURIComponent(sc)}`)
    resultLevel.value = res?.code === 0 ? 'success' : 'error'
    result.value = res?.message || '已清理'
    Object.keys(picks).forEach(s => delete picks[s])
    await load()
  } catch (e) {
    resultLevel.value = 'error'
    result.value = '清理失败：' + (e?.message || e)
  } finally {
    removing.value = false
  }
}

watch([scope, keyword, sourceFilter, targetFilter, pageSize], () => { page.value = 1 })
watch(scope, load)

onMounted(load)
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

.ms-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 8px;
  padding: 4px 16px 10px;
}

.ms-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  border-radius: 10px;
  background: rgba(var(--v-theme-on-surface), 0.03);
  text-align: left;
}

button.ms-stat {
  cursor: pointer;
}

.ms-stat--active {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.1);
}

.ms-stat--plain {
  cursor: default;
}

.ms-stat__num {
  font-size: 1.1rem;
  font-weight: 700;
}

.ms-stat__label {
  font-size: 0.73rem;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.ms-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 0 16px 8px;
}

.ms-toolbar__group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.ms-toolbar__search {
  flex: 1 1 200px;
  min-width: 160px;
}

.ms-toolbar__source {
  flex: 0 0 140px;
  min-width: 120px;
}

.ms-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 0 16px;
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

.ms-table td input[type='radio'] {
  width: 15px;
  height: 15px;
  accent-color: rgb(var(--v-theme-primary));
  cursor: pointer;
}

.col-seq {
  width: 52px;
}

.col-pick {
  width: 78px;
  text-align: center;
}

.ms-table th.col-pick {
  text-align: center;
}

.col-dur {
  width: 66px;
  white-space: nowrap;
}

.ms-title {
  font-weight: 600;
}

.ms-sub {
  margin-top: 2px;
  font-size: 0.73rem;
  color: rgba(var(--v-theme-on-surface), 0.5);
}

.ms-src {
  color: rgba(var(--v-theme-primary), 0.9);
}

/* 订阅失败的行留在清单里，用淡红底 + 红字标出原因 */
.ms-fail {
  color: rgb(var(--v-theme-error));
}

.ms-row--fail {
  background: rgba(var(--v-theme-error), 0.05);
}

.ms-empty {
  padding: 28px 8px;
  text-align: center;
  font-size: 0.85rem;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.ms-pager {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px 0;
  flex-wrap: wrap;
}

.ms-pager__size {
  flex: 0 0 96px;
}

.ms-pager__info {
  font-size: 0.78rem;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.ms-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  flex-wrap: wrap;
}

.ms-foot__count {
  font-size: 0.8rem;
  color: rgba(var(--v-theme-on-surface), 0.6);
}

/* 官方详情页链接：歌曲 / 专辑 / 歌手 */
.col-link {
  width: 150px;
  white-space: nowrap;
}

.col-link a {
  margin-right: 8px;
  color: rgb(var(--v-theme-primary));
  text-decoration: none;
}

.col-link a:hover {
  text-decoration: underline;
}

/* 取不到链接时置灰，保留占位避免列宽跳动 */
.ms-link-off {
  margin-right: 8px;
  color: rgba(var(--v-theme-on-surface), 0.28);
}

.ms-linkbtn {
  padding: 2px 8px;
  border: 1px solid rgba(var(--v-theme-primary), 0.5);
  border-radius: 6px;
  background: transparent;
  color: rgb(var(--v-theme-primary));
  font-size: 0.75rem;
  cursor: pointer;
}

.ms-linkbtn:disabled {
  opacity: 0.6;
  cursor: progress;
}

.col-time {
  width: 132px;
  white-space: nowrap;
  font-size: 0.78rem;
  color: rgba(var(--v-theme-on-surface), 0.6);
}
</style>
