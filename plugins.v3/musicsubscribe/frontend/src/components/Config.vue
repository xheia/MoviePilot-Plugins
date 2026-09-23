<template>
  <section class="ms-config">
    <!-- 头部 -->
    <header class="ms-head">
      <div class="ms-head__brand">
        <div class="ms-head__logo"><v-icon icon="mdi-music-note" size="20" /></div>
        <div class="ms-head__identity">
          <div class="ms-head__crumbs">
            <span>MoviePilot</span>
            <v-icon icon="mdi-chevron-right" size="13" />
            <span>插件</span>
          </div>
          <h1 class="ms-head__title">歌单订阅</h1>
        </div>
      </div>
      <div class="ms-head__actions">
        <span v-if="loggedIn" class="ms-chip ms-chip--ok">
          <v-icon icon="mdi-account-music" size="14" />{{ username }}
        </span>
        <span v-else-if="loaded" class="ms-chip ms-chip--muted">
          <v-icon icon="mdi-account-off" size="14" />网易云未登录
        </span>
        <span v-if="dirty" class="ms-chip ms-chip--warn">有改动未保存</span>
        <v-btn class="ms-head__save" color="primary" variant="flat" prepend-icon="mdi-content-save-outline"
          :loading="saving" @click="save">
          保存
        </v-btn>
        <v-btn icon="mdi-close" size="small" variant="text" :aria-label="'关闭'" @click="emit('close')" />
      </div>
    </header>

    <v-tabs v-model="tab" color="primary" density="compact">
      <v-tab value="run">运行设置</v-tab>
      <v-tab value="netease">网易云</v-tab>
      <v-tab value="sources">歌单来源</v-tab>
      <v-tab value="result">上次同步</v-tab>
    </v-tabs>

    <v-alert v-if="error" class="ma-3 mb-0" density="compact" type="warning" variant="tonal">{{ error }}</v-alert>

    <div class="ms-body">
      <v-skeleton-loader v-if="loading" type="article, article" />

      <template v-else>
        <!-- 运行设置 -->
        <template v-if="tab === 'run'">
          <section class="ms-section">
            <h3 class="ms-section__title">调度</h3>
            <v-switch v-model="form.enabled" color="primary" inset>
              <template #label><span class="ms-label">启用插件</span></template>
            </v-switch>
            <p class="ms-hint">关闭后不再注册定时任务，也无法手动运行。</p>
            <v-text-field v-model="form.cron" placeholder="0 4 * * *" hint="五位 cron 表达式，留空表示不定时运行"
              label="定时同步周期" persistent-hint />
          </section>

          <v-divider />

          <section class="ms-section">
            <h3 class="ms-section__title">缺失曲目订阅</h3>
            <v-text-field v-model="form.subscribe_user" label="订阅人" placeholder="歌单订阅"
              hint="写到宿主订阅记录的「用户」栏位上，便于在订阅列表里区分是谁订的" persistent-hint />
            <p class="ms-hint">缺失曲目的搜索、识别、订阅都走宿主的官方音乐接口，插件不指定任何音乐来源
              （搜哪些库由宿主自己的音乐元数据源设置决定）。</p>
          </section>

          <v-divider />

          <section class="ms-section">
            <h3 class="ms-section__title">媒体服务器</h3>
            <v-select v-model="form.media_server" :items="mediaServers" multiple chips closable-chips
              label="同步到哪些媒体服务器" placeholder="请选择已启用的媒体服务器" />
            <p class="ms-hint">列表来自「设置 → 媒体服务器」里已启用的服务器，支持多选。</p>
            <v-switch v-model="form.exact_match" color="primary" inset>
              <template #label><span class="ms-label">曲目精确匹配</span></template>
            </v-switch>
            <p class="ms-hint">开启时按「歌名 + 歌手」精确判断曲库是否已存在；关闭后仅按歌名模糊匹配，
              匹配更宽松但可能并入同名不同版本的曲目。</p>
          </section>
        </template>

        <!-- 网易云 -->
        <template v-else-if="tab === 'netease'">
          <section class="ms-section">
            <h3 class="ms-section__title">ncm-api 服务</h3>
            <div class="ms-row">
              <v-text-field v-model="form.ncm_api_url" class="ms-row__grow" label="服务地址"
                placeholder="http://192.168.1.100:1630" />
              <v-btn class="ms-row__btn" variant="tonal" :loading="probing" @click="probe">探测连通性</v-btn>
            </div>
            <p class="ms-hint">网易云的登录与取数都通过本地部署的 ncm-api 容器完成；
              容器内的 3000 端口建议映射到宿主的 1630 端口，避免和 MoviePilot 冲突。</p>
            <v-alert v-if="probeResult" :type="probeResult.code === 0 ? 'success' : 'error'" density="compact"
              variant="tonal" class="mt-2">{{ probeResult.message }}</v-alert>
          </section>

          <v-divider />

          <section class="ms-section">
            <h3 class="ms-section__title">登录</h3>
            <div class="ms-login-state">
              <span :class="['ms-chip', loggedIn ? 'ms-chip--ok' : 'ms-chip--muted']">
                <v-icon :icon="loggedIn ? 'mdi-account-music' : 'mdi-account-off'" size="14" />
                {{ loggedIn ? `已登录：${username}` : '未登录' }}
              </span>
              <v-btn size="small" variant="tonal" color="error" prepend-icon="mdi-logout" :disabled="!loggedIn"
                :loading="logouting" @click="logout">退出登录</v-btn>
            </div>

            <!-- 扫码登录（插件只提供这一种登录方式） -->
            <v-btn class="mt-3" color="primary" variant="tonal" prepend-icon="mdi-qrcode" :loading="qrLoading"
              @click="getQrcode">获取二维码</v-btn>
            <div v-if="qrimg" class="ms-qr">
              <img :src="qrimg" alt="网易云扫码二维码" />
              <div class="ms-qr__tip">{{ qrMessage || '请使用网易云音乐 App 扫码' }}</div>
            </div>

            <div v-if="loginResult" class="mt-3">
              <v-alert :type="loginResult.code === 0 ? 'success' : 'error'" density="compact" variant="tonal">
                {{ loginResult.message }}
              </v-alert>
            </div>
          </section>
        </template>

        <!-- 歌单来源 -->
        <template v-else-if="tab === 'sources'">
          <section class="ms-section">
            <h3 class="ms-section__title">网易云歌单</h3>
            <v-textarea v-model="form.wymusic_paths" rows="4" auto-grow label="歌单同步设置"
              placeholder="每行一条：歌单ID:播放列表名称[:emby用户名]" />
            <p class="ms-hint">
              示例：<code>2388086885:我喜欢的音乐</code>；Emby 多用户隔离时写
              <code>2388086885:我喜欢的音乐:张三,李四</code>。也支持直接粘贴歌单链接。
            </p>
            <v-switch v-model="form.wy_daily_list" color="primary" inset>
              <template #label><span class="ms-label">同步每日推荐歌单</span></template>
            </v-switch>
            <v-switch v-model="form.wy_daily_song" color="primary" inset>
              <template #label><span class="ms-label">同步每日推荐歌曲</span></template>
            </v-switch>
            <p class="ms-hint">每日推荐需要网易云登录态，未登录时该任务会跳过并在日志里说明原因。</p>
          </section>

          <v-divider />

          <section class="ms-section">
            <h3 class="ms-section__title">QQ 音乐歌单</h3>
            <v-textarea v-model="form.qqmusic_paths" rows="3" auto-grow label="歌单同步设置"
              placeholder="每行一条：歌单ID:播放列表名称[:emby用户名]" />
          </section>

          <v-divider />

          <section class="ms-section">
            <h3 class="ms-section__title">汽水音乐歌单</h3>
            <v-textarea v-model="form.qishui_paths" rows="3" auto-grow label="歌单同步设置"
              placeholder="每行一条：分享链接:播放列表名称[:emby用户名]" />
            <p class="ms-hint">粘贴汽水音乐 App 里复制的歌单分享链接即可。</p>
          </section>
        </template>

        <!-- 上次同步 -->
        <template v-else>
          <section class="ms-section" v-if="!stats.start_time">
            <v-alert density="compact" type="info" variant="tonal">还没有同步记录，配置保存后手动运行一次即可。</v-alert>
          </section>
          <section class="ms-section" v-else>
            <div class="ms-stats">
              <div class="ms-stat"><span class="ms-stat__num">{{ stats.duration || 0 }}</span><span
                  class="ms-stat__label">耗时（秒）</span></div>
              <div class="ms-stat"><span class="ms-stat__num">{{ stats.missing || 0 }}</span><span
                  class="ms-stat__label">库内缺失</span></div>
              <div class="ms-stat"><span class="ms-stat__num">{{ (stats.playlists || []).length }}</span><span
                  class="ms-stat__label">歌单数</span></div>
              <div class="ms-stat"><span class="ms-stat__num">{{ addedTotal }}</span><span
                  class="ms-stat__label">新增曲目</span></div>
            </div>
            <p class="ms-hint">上次开始时间：{{ stats.start_time }}<span v-if="stats.error">（异常：{{ stats.error }}）</span></p>
            <table v-if="(stats.playlists || []).length" class="ms-table">
              <thead>
                <tr>
                  <th>数据源</th>
                  <th>播放列表</th>
                  <th class="num">曲目</th>
                  <th class="num">新增</th>
                  <th class="num">缺失</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(p, i) in stats.playlists" :key="i">
                  <td>{{ p.source }}</td>
                  <td>{{ p.name }}</td>
                  <td class="num">{{ p.total || 0 }}</td>
                  <td class="num">{{ p.added || 0 }}</td>
                  <td class="num">{{ p.missing || 0 }}</td>
                  <td>
                    <span :class="['ms-chip', p.status === 'ok' ? 'ms-chip--ok' : 'ms-chip--err']">
                      {{ p.status === 'ok' ? '成功' : '失败' }}
                    </span>
                    <span v-if="p.message" class="ms-table__note">{{ p.message }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
        </template>
      </template>
    </div>

    <!-- 底部动作条 -->
    <footer class="ms-foot">
      <v-btn variant="tonal" prepend-icon="mdi-play-circle-outline" :disabled="!form.enabled" :loading="running"
        @click="runOnce">立即运行一次</v-btn>
      <v-spacer />
      <v-btn variant="text" prepend-icon="mdi-format-list-bulleted" @click="emit('switch')">查看缺失清单</v-btn>
    </footer>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['save', 'close', 'switch', 'layout'])
emit('layout', { maxWidth: '60rem' })

const PLUGIN = 'plugin/MusicSubscribe'

const DEFAULTS = {
  enabled: false,
  cron: '',
  media_server: [],
  exact_match: true,
  subscribe_user: '歌单订阅',
  ncm_api_url: '',
  wymusic_paths: '',
  wy_daily_list: false,
  wy_daily_song: false,
  qqmusic_paths: '',
  qishui_paths: '',
}

const tab = ref('run')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const loaded = ref(false)

const form = reactive({ ...DEFAULTS })
let baseline = JSON.stringify({ ...DEFAULTS })

const mediaServers = ref([])
const username = ref('')
const loggedIn = computed(() => !!username.value)
const stats = ref({})

// 扫码登录的结果提示（不落配置）
const loginResult = ref(null)

const qrimg = ref('')
const qrKey = ref('')
const qrMessage = ref('')
const qrLoading = ref(false)
let qrTimer = null

const probeResult = ref(null)
const probing = ref(false)
const logouting = ref(false)
const running = ref(false)

const addedTotal = computed(() =>
  (stats.value.playlists || []).reduce((sum, p) => sum + (p.added || 0), 0))

const dirty = computed(() => JSON.stringify({ ...form }) !== baseline)

function call(method, path, data) {
  const fn = props?.api?.[method]
  if (typeof fn !== 'function') throw new Error('API 不可用')
  return data === undefined ? fn(path) : fn(path, data)
}

async function loadStatus() {
  loading.value = true
  error.value = ''
  try {
    const res = await call('get', `${PLUGIN}/status`)
    const conf = res?.config || {}
    Object.assign(form, { ...DEFAULTS }, props.initialConfig && Object.keys(props.initialConfig).length
      ? { ...conf, ...pickKnown(props.initialConfig) }
      : conf)
    form.media_server = Array.isArray(form.media_server) ? form.media_server : []
    baseline = JSON.stringify({ ...form })
    mediaServers.value = Array.isArray(res?.media_servers) ? res.media_servers : []
    username.value = res?.username || ''
    stats.value = res?.stats || {}
    loaded.value = true
  } catch (e) {
    error.value = '加载插件状态失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

// 宿主回传的 initialConfig 可能夹带脏键，只取插件认识的
function pickKnown(raw) {
  const out = {}
  Object.keys(DEFAULTS).forEach(k => {
    if (raw[k] !== undefined && raw[k] !== null) out[k] = raw[k]
  })
  return out
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    emit('save', JSON.parse(JSON.stringify(form)))
    baseline = JSON.stringify({ ...form })
  } catch (e) {
    error.value = '保存失败：' + (e?.message || e)
  } finally {
    saving.value = false
  }
}

async function probe() {
  probing.value = true
  probeResult.value = null
  try {
    const url = encodeURIComponent(form.ncm_api_url || '')
    probeResult.value = await call('get', `${PLUGIN}/probe?api_url=${url}`)
  } catch (e) {
    probeResult.value = { code: 1, message: '连接失败：' + (e?.message || e) }
  } finally {
    probing.value = false
  }
}

async function getQrcode() {
  qrLoading.value = true
  error.value = ''
  try {
    const res = await call('post', `${PLUGIN}/qrcode`)
    if (res?.code !== 0) throw new Error(res?.message || '获取二维码失败')
    qrimg.value = res.qrimg || ''
    qrKey.value = res.key || ''
    qrMessage.value = res.message || ''
    startQrPoll()
  } catch (e) {
    error.value = '获取二维码失败：' + (e?.message || e)
  } finally {
    qrLoading.value = false
  }
}

function startQrPoll() {
  stopQrPoll()
  if (!qrKey.value) return
  qrTimer = setInterval(async () => {
    try {
      const res = await call('get', `${PLUGIN}/qrcode/status?key=${encodeURIComponent(qrKey.value)}`)
      qrMessage.value = res?.message || qrMessage.value
      if (res?.logged_in) {
        stopQrPoll()
        qrimg.value = ''
        username.value = res?.username || await refreshUsername()
        loginResult.value = { code: 0, message: `登录成功：${username.value}` }
      } else if (res?.status === 800) {
        // 二维码过期
        stopQrPoll()
        qrMessage.value = '二维码已过期，请重新获取'
      }
    } catch (e) {
      stopQrPoll()
      qrMessage.value = '查询扫码状态失败：' + (e?.message || e)
    }
  }, 2000)
}

function stopQrPoll() {
  if (qrTimer) {
    clearInterval(qrTimer)
    qrTimer = null
  }
}

async function refreshUsername() {
  try {
    const res = await call('get', `${PLUGIN}/status`)
    return res?.username || ''
  } catch {
    return ''
  }
}

async function logout() {
  logouting.value = true
  try {
    const res = await call('post', `${PLUGIN}/logout`)
    loginResult.value = { code: res?.code === 0 ? 0 : 1, message: res?.message || '已退出登录' }
    if (res?.code === 0) {
      username.value = ''
      qrimg.value = ''
      stopQrPoll()
    }
  } catch (e) {
    loginResult.value = { code: 1, message: '退出登录失败：' + (e?.message || e) }
  } finally {
    logouting.value = false
  }
}

async function runOnce() {
  running.value = true
  try {
    const res = await call('post', `${PLUGIN}/run`)
    error.value = res?.code === 0 ? '' : (res?.message || '触发失败')
    if (res?.code === 0) await Promise.resolve(setTimeout(refreshStats, 3500))
  } catch (e) {
    error.value = '触发同步失败：' + (e?.message || e)
  } finally {
    running.value = false
  }
}

async function refreshStats() {
  try {
    const res = await call('get', `${PLUGIN}/status`)
    stats.value = res?.stats || {}
    username.value = res?.username || username.value
  } catch { /* 静默：状态刷新失败不影响配置编辑 */ }
}

onMounted(loadStatus)
onUnmounted(stopQrPoll)
</script>

<style scoped>
.ms-config {
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
  padding: 14px 16px 10px;
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
  gap: 8px;
  margin-left: auto;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ms-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 0.75rem;
  line-height: 1.4;
  white-space: nowrap;
}

.ms-chip--ok {
  background: rgba(var(--v-theme-success), 0.14);
  color: rgb(var(--v-theme-success));
}

.ms-chip--muted {
  background: rgba(var(--v-theme-on-surface), 0.08);
  color: rgba(var(--v-theme-on-surface), 0.6);
}

.ms-chip--warn {
  background: rgba(var(--v-theme-warning), 0.16);
  color: rgb(var(--v-theme-warning));
}

.ms-chip--err {
  background: rgba(var(--v-theme-error), 0.14);
  color: rgb(var(--v-theme-error));
}

.ms-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 4px 0 8px;
}

.ms-section {
  padding: 16px;
}

.ms-section__title {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 700;
}

.ms-label {
  font-size: 0.9rem;
}

.ms-hint {
  margin: 6px 0 0;
  font-size: 0.78rem;
  line-height: 1.6;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.ms-hint code {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(var(--v-theme-on-surface), 0.08);
  font-size: 0.76rem;
}

.ms-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.ms-row__grow {
  flex: 1 1 auto;
}

.ms-row__btn {
  flex: 0 0 auto;
  margin-top: 6px;
}

.ms-login-state {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.ms-qr {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 12px;
  text-align: center;
}

.ms-qr img {
  width: 180px;
  height: 180px;
  object-fit: contain;
}

.ms-qr__tip {
  margin-top: 8px;
  font-size: 0.8rem;
  color: rgba(var(--v-theme-on-surface), 0.65);
}

.ms-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.ms-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  border-radius: 10px;
}

.ms-stat__num {
  font-size: 1.15rem;
  font-weight: 700;
}

.ms-stat__label {
  font-size: 0.75rem;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

.ms-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}

.ms-table th,
.ms-table td {
  padding: 7px 8px;
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  text-align: left;
}

.ms-table th {
  font-weight: 700;
  color: rgba(var(--v-theme-on-surface), 0.6);
}

.ms-table .num {
  text-align: right;
}

.ms-table__note {
  margin-left: 6px;
  font-size: 0.75rem;
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
</style>
