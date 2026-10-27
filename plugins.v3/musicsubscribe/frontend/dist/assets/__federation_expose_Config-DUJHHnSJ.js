import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,withCtx:_withCtx,createBlock:_createBlock,Fragment:_Fragment,normalizeClass:_normalizeClass,renderList:_renderList} = await importShared('vue');


const _hoisted_1 = { class: "ms-config" };
const _hoisted_2 = { class: "ms-head" };
const _hoisted_3 = { class: "ms-head__brand" };
const _hoisted_4 = { class: "ms-head__logo" };
const _hoisted_5 = { class: "ms-head__identity" };
const _hoisted_6 = { class: "ms-head__crumbs" };
const _hoisted_7 = { class: "ms-head__actions" };
const _hoisted_8 = {
  key: 0,
  class: "ms-chip ms-chip--ok"
};
const _hoisted_9 = {
  key: 1,
  class: "ms-chip ms-chip--muted"
};
const _hoisted_10 = {
  key: 2,
  class: "ms-chip ms-chip--warn"
};
const _hoisted_11 = { class: "ms-body" };
const _hoisted_12 = { class: "ms-section" };
const _hoisted_13 = { class: "ms-section" };
const _hoisted_14 = { class: "ms-row" };
const _hoisted_15 = { class: "ms-section" };
const _hoisted_16 = { class: "ms-section" };
const _hoisted_17 = { class: "ms-row" };
const _hoisted_18 = { class: "ms-section" };
const _hoisted_19 = { class: "ms-login-state" };
const _hoisted_20 = {
  key: 0,
  class: "ms-qr"
};
const _hoisted_21 = ["src"];
const _hoisted_22 = { class: "ms-qr__tip" };
const _hoisted_23 = {
  key: 1,
  class: "mt-3"
};
const _hoisted_24 = { class: "ms-section" };
const _hoisted_25 = { class: "ms-section" };
const _hoisted_26 = { class: "ms-section" };
const _hoisted_27 = { class: "ms-section" };
const _hoisted_28 = { class: "ms-row" };
const _hoisted_29 = {
  key: 0,
  class: "ms-section"
};
const _hoisted_30 = { class: "ms-platforms" };
const _hoisted_31 = { class: "ms-platform__name" };
const _hoisted_32 = { class: "ms-platform__state" };
const _hoisted_33 = {
  key: 0,
  class: "ms-section"
};
const _hoisted_34 = {
  key: 1,
  class: "ms-section"
};
const _hoisted_35 = { class: "ms-stats" };
const _hoisted_36 = { class: "ms-stat" };
const _hoisted_37 = { class: "ms-stat__num" };
const _hoisted_38 = { class: "ms-stat" };
const _hoisted_39 = { class: "ms-stat__num" };
const _hoisted_40 = { class: "ms-stat" };
const _hoisted_41 = { class: "ms-stat__num" };
const _hoisted_42 = { class: "ms-stat" };
const _hoisted_43 = { class: "ms-stat__num" };
const _hoisted_44 = { class: "ms-stat" };
const _hoisted_45 = { class: "ms-stat__num" };
const _hoisted_46 = { class: "ms-stat__label" };
const _hoisted_47 = { class: "ms-stat" };
const _hoisted_48 = { class: "ms-stat__num" };
const _hoisted_49 = { class: "ms-hint" };
const _hoisted_50 = { key: 0 };
const _hoisted_51 = {
  key: 1,
  class: "ms-chip ms-chip--warn"
};
const _hoisted_52 = {
  key: 2,
  class: "ms-chip ms-chip--muted"
};
const _hoisted_53 = { class: "ms-hint" };
const _hoisted_54 = {
  key: 0,
  class: "ms-table"
};
const _hoisted_55 = { class: "num" };
const _hoisted_56 = { class: "num" };
const _hoisted_57 = { class: "num" };
const _hoisted_58 = {
  key: 0,
  class: "ms-table__note"
};
const _hoisted_59 = { class: "ms-foot" };

const {computed,onMounted,onUnmounted,reactive,ref} = await importShared('vue');


const PLUGIN = 'plugin/MusicSubscribe';


const _sfc_main = {
  __name: 'Config',
  props: {
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
},
  emits: ['save', 'close', 'switch', 'layout'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
emit('layout', { maxWidth: '60rem' });

const DEFAULTS = {
  enabled: false,
  cron: '',
  media_server: [],
  exact_match: true,
  subscribe_user: '歌单订阅',
  subscribe_workers: 2,
  immediate_search: true,
  library_index: true,
  ncm_api_url: '',
  wymusic_paths: '',
  wy_daily_list: false,
  wy_daily_song: false,
  qqmusic_paths: '',
  spotify_client_id: '',
  spotify_client_secret: '',
  other_paths: '',
};

const tab = ref('run');
const loading = ref(true);
const saving = ref(false);
const error = ref('');
const loaded = ref(false);

const form = reactive({ ...DEFAULTS });
let baseline = JSON.stringify({ ...DEFAULTS });

const mediaServers = ref([]);
const platforms = ref([]);
const username = ref('');
const loggedIn = computed(() => !!username.value);
const stats = ref({});

// 扫码登录的结果提示（不落配置）
const loginResult = ref(null);

const qrimg = ref('');
const qrKey = ref('');
const qrMessage = ref('');
const qrLoading = ref(false);
let qrTimer = null;

const probeResult = ref(null);
const probing = ref(false);
const logouting = ref(false);
const running = ref(false);

const addedTotal = computed(() =>
  (stats.value.playlists || []).reduce((sum, p) => sum + (p.added || 0), 0));

// 分段耗时 / 索引 / 媒体库请求等运行指标（v2.4.0 新增）
const metrics = computed(() => stats.value.metrics || {});

const dirty = computed(() => JSON.stringify({ ...form }) !== baseline);

function call(method, path, data) {
  const fn = props?.api?.[method];
  if (typeof fn !== 'function') throw new Error('API 不可用')
  return data === undefined ? fn(path) : fn(path, data)
}

async function loadStatus() {
  loading.value = true;
  error.value = '';
  try {
    const res = await call('get', `${PLUGIN}/status`);
    const conf = res?.config || {};
    Object.assign(form, { ...DEFAULTS }, props.initialConfig && Object.keys(props.initialConfig).length
      ? { ...conf, ...pickKnown(props.initialConfig) }
      : conf);
    form.media_server = Array.isArray(form.media_server) ? form.media_server : [];
    baseline = JSON.stringify({ ...form });
    mediaServers.value = Array.isArray(res?.media_servers) ? res.media_servers : [];
    platforms.value = Array.isArray(res?.platforms) ? res.platforms : [];
    username.value = res?.username || '';
    stats.value = res?.stats || {};
    running.value = !!res?.running;
    loaded.value = true;
  } catch (e) {
    error.value = '加载插件状态失败：' + (e?.message || e);
  } finally {
    loading.value = false;
  }
}

// 宿主回传的 initialConfig 可能夹带脏键，只取插件认识的
function pickKnown(raw) {
  const out = {};
  Object.keys(DEFAULTS).forEach(k => {
    if (raw[k] !== undefined && raw[k] !== null) out[k] = raw[k];
  });
  return out
}

async function save() {
  saving.value = true;
  error.value = '';
  try {
    emit('save', JSON.parse(JSON.stringify(form)));
    baseline = JSON.stringify({ ...form });
  } catch (e) {
    error.value = '保存失败：' + (e?.message || e);
  } finally {
    saving.value = false;
  }
}

async function probe() {
  probing.value = true;
  probeResult.value = null;
  try {
    const url = encodeURIComponent(form.ncm_api_url || '');
    probeResult.value = await call('get', `${PLUGIN}/probe?api_url=${url}`);
  } catch (e) {
    probeResult.value = { code: 1, message: '连接失败：' + (e?.message || e) };
  } finally {
    probing.value = false;
  }
}

async function getQrcode() {
  qrLoading.value = true;
  error.value = '';
  try {
    const res = await call('post', `${PLUGIN}/qrcode`);
    if (res?.code !== 0) throw new Error(res?.message || '获取二维码失败')
    qrimg.value = res.qrimg || '';
    qrKey.value = res.key || '';
    qrMessage.value = res.message || '';
    startQrPoll();
  } catch (e) {
    error.value = '获取二维码失败：' + (e?.message || e);
  } finally {
    qrLoading.value = false;
  }
}

function startQrPoll() {
  stopQrPoll();
  if (!qrKey.value) return
  qrTimer = setInterval(async () => {
    try {
      const res = await call('get', `${PLUGIN}/qrcode/status?key=${encodeURIComponent(qrKey.value)}`);
      qrMessage.value = res?.message || qrMessage.value;
      if (res?.logged_in) {
        stopQrPoll();
        qrimg.value = '';
        username.value = res?.username || await refreshUsername();
        loginResult.value = { code: 0, message: `登录成功：${username.value}` };
      } else if (res?.status === 800) {
        // 二维码过期
        stopQrPoll();
        qrMessage.value = '二维码已过期，请重新获取';
      }
    } catch (e) {
      stopQrPoll();
      qrMessage.value = '查询扫码状态失败：' + (e?.message || e);
    }
  }, 2000);
}

function stopQrPoll() {
  if (qrTimer) {
    clearInterval(qrTimer);
    qrTimer = null;
  }
}

async function refreshUsername() {
  try {
    const res = await call('get', `${PLUGIN}/status`);
    return res?.username || ''
  } catch {
    return ''
  }
}

async function logout() {
  logouting.value = true;
  try {
    const res = await call('post', `${PLUGIN}/logout`);
    loginResult.value = { code: res?.code === 0 ? 0 : 1, message: res?.message || '已退出登录' };
    if (res?.code === 0) {
      username.value = '';
      qrimg.value = '';
      stopQrPoll();
    }
  } catch (e) {
    loginResult.value = { code: 1, message: '退出登录失败：' + (e?.message || e) };
  } finally {
    logouting.value = false;
  }
}

// 运行一次后轮询 /status：本轮同步要跨多个歌单与服务器，轮询让「同步进行中」
// 状态与同步统计持续保鲜，跑完自动收起
let runPollTimer = null;
let runPollSeen = false;
function stopRunPoll() {
  if (runPollTimer) {
    clearInterval(runPollTimer);
    runPollTimer = null;
  }
}

async function runOnce() {
  running.value = true;
  stopRunPoll();
  runPollSeen = false;
  try {
    const res = await call('post', `${PLUGIN}/run`);
    error.value = res?.code === 0 ? '' : (res?.message || '触发失败');
    if (res?.code === 0) {
      let rounds = 0;
      runPollTimer = setInterval(async () => {
        rounds += 1;
        try {
          await refreshStats();
        } catch { /* 单次刷新失败继续轮询 */ }
        if (running.value) runPollSeen = true;
        // 见过 running=true 后又转 false，或超过 10 分钟仍未结束，停止轮询
        if ((runPollSeen && !running.value) || rounds >= 200) {
          stopRunPoll();
          running.value = false;
        }
      }, 3000);
    } else {
      running.value = false;
    }
  } catch (e) {
    error.value = '触发同步失败：' + (e?.message || e);
    running.value = false;
  }
}

async function refreshStats() {
  try {
    const res = await call('get', `${PLUGIN}/status`);
    stats.value = res?.stats || {};
    running.value = !!res?.running;
    username.value = res?.username || username.value;
  } catch { /* 静默：状态刷新失败不影响配置编辑 */ }
}

onMounted(loadStatus);
onUnmounted(() => { stopQrPoll(); stopRunPoll(); });

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_tab = _resolveComponent("v-tab");
  const _component_v_tabs = _resolveComponent("v-tabs");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_skeleton_loader = _resolveComponent("v-skeleton-loader");
  const _component_v_switch = _resolveComponent("v-switch");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_divider = _resolveComponent("v-divider");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_textarea = _resolveComponent("v-textarea");
  const _component_v_spacer = _resolveComponent("v-spacer");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_v_icon, {
            icon: "mdi-music-note",
            size: "20"
          })
        ]),
        _createElementVNode("div", _hoisted_5, [
          _createElementVNode("div", _hoisted_6, [
            _cache[19] || (_cache[19] = _createElementVNode("span", null, "MoviePilot", -1)),
            _createVNode(_component_v_icon, {
              icon: "mdi-chevron-right",
              size: "13"
            }),
            _cache[20] || (_cache[20] = _createElementVNode("span", null, "插件", -1))
          ]),
          _cache[21] || (_cache[21] = _createElementVNode("h1", { class: "ms-head__title" }, "歌单订阅", -1))
        ])
      ]),
      _createElementVNode("div", _hoisted_7, [
        (loggedIn.value)
          ? (_openBlock(), _createElementBlock("span", _hoisted_8, [
              _createVNode(_component_v_icon, {
                icon: "mdi-account-music",
                size: "14"
              }),
              _createTextVNode(_toDisplayString(username.value), 1)
            ]))
          : (loaded.value)
            ? (_openBlock(), _createElementBlock("span", _hoisted_9, [
                _createVNode(_component_v_icon, {
                  icon: "mdi-account-off",
                  size: "14"
                }),
                _cache[22] || (_cache[22] = _createTextVNode("网易云未登录 ", -1))
              ]))
            : _createCommentVNode("", true),
        (dirty.value)
          ? (_openBlock(), _createElementBlock("span", _hoisted_10, "有改动未保存"))
          : _createCommentVNode("", true),
        _createVNode(_component_v_btn, {
          class: "ms-head__save",
          color: "primary",
          variant: "flat",
          "prepend-icon": "mdi-content-save-outline",
          loading: saving.value,
          onClick: save
        }, {
          default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
            _createTextVNode(" 保存 ", -1)
          ]))]),
          _: 1
        }, 8, ["loading"]),
        _createVNode(_component_v_btn, {
          icon: "mdi-close",
          size: "small",
          variant: "text",
          "aria-label": '关闭',
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ])
    ]),
    _createVNode(_component_v_tabs, {
      modelValue: tab.value,
      "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((tab).value = $event)),
      color: "primary",
      density: "compact"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_v_tab, { value: "run" }, {
          default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
            _createTextVNode("运行设置", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_v_tab, { value: "netease" }, {
          default: _withCtx(() => [...(_cache[25] || (_cache[25] = [
            _createTextVNode("网易云", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_v_tab, { value: "sources" }, {
          default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
            _createTextVNode("歌单来源", -1)
          ]))]),
          _: 1
        }),
        _createVNode(_component_v_tab, { value: "result" }, {
          default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
            _createTextVNode("上次同步", -1)
          ]))]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    (error.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          class: "ma-3 mb-0",
          density: "compact",
          type: "warning",
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        }))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_11, [
      (loading.value)
        ? (_openBlock(), _createBlock(_component_v_skeleton_loader, {
            key: 0,
            type: "article, article"
          }))
        : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
            (tab.value === 'run')
              ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                  _createElementVNode("section", _hoisted_12, [
                    _cache[29] || (_cache[29] = _createElementVNode("h3", { class: "ms-section__title" }, "调度", -1)),
                    _createVNode(_component_v_switch, {
                      modelValue: form.enabled,
                      "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.enabled) = $event)),
                      color: "primary",
                      inset: ""
                    }, {
                      label: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                        _createElementVNode("span", { class: "ms-label" }, "启用插件", -1)
                      ]))]),
                      _: 1
                    }, 8, ["modelValue"]),
                    _cache[30] || (_cache[30] = _createElementVNode("p", { class: "ms-hint" }, "关闭后不再注册定时任务，也无法手动运行。", -1)),
                    _createVNode(_component_v_text_field, {
                      modelValue: form.cron,
                      "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.cron) = $event)),
                      placeholder: "0 4 * * *",
                      hint: "五位 cron 表达式，留空表示不定时运行",
                      label: "定时同步周期",
                      "persistent-hint": ""
                    }, null, 8, ["modelValue"])
                  ]),
                  _createVNode(_component_v_divider),
                  _createElementVNode("section", _hoisted_13, [
                    _cache[33] || (_cache[33] = _createElementVNode("h3", { class: "ms-section__title" }, "缺失曲目订阅", -1)),
                    _createVNode(_component_v_text_field, {
                      modelValue: form.subscribe_user,
                      "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((form.subscribe_user) = $event)),
                      label: "订阅人",
                      placeholder: "歌单订阅",
                      hint: "写到宿主订阅记录的「用户」栏位上，便于在订阅列表里区分是谁订的",
                      "persistent-hint": ""
                    }, null, 8, ["modelValue"]),
                    _createElementVNode("div", _hoisted_14, [
                      _createVNode(_component_v_text_field, {
                        modelValue: form.subscribe_workers,
                        "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.subscribe_workers) = $event)),
                        modelModifiers: { number: true },
                        class: "ms-row__grow",
                        type: "number",
                        min: "1",
                        max: "8",
                        step: "1",
                        label: "订阅并发数",
                        hint: "同时搜索 / 识别 / 订阅的条数（1-8）",
                        "persistent-hint": ""
                      }, null, 8, ["modelValue"])
                    ]),
                    _createVNode(_component_v_switch, {
                      modelValue: form.immediate_search,
                      "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.immediate_search) = $event)),
                      color: "primary",
                      inset: ""
                    }, {
                      label: _withCtx(() => [...(_cache[31] || (_cache[31] = [
                        _createElementVNode("span", { class: "ms-label" }, "订阅后立即搜索", -1)
                      ]))]),
                      _: 1
                    }, 8, ["modelValue"]),
                    _cache[34] || (_cache[34] = _createElementVNode("p", { class: "ms-hint" }, "开启时订阅成功即送入宿主的原生搜索队列（等同手动点「搜索」）并后台唤醒； 关闭则等宿主自己的调度处理。", -1)),
                    _createVNode(_component_v_switch, {
                      modelValue: form.library_index,
                      "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.library_index) = $event)),
                      color: "primary",
                      inset: ""
                    }, {
                      label: _withCtx(() => [...(_cache[32] || (_cache[32] = [
                        _createElementVNode("span", { class: "ms-label" }, "启用曲库索引", -1)
                      ]))]),
                      _: 1
                    }, 8, ["modelValue"]),
                    _cache[35] || (_cache[35] = _createElementVNode("p", { class: "ms-hint" }, "开启时每轮同步先把整个音乐库拉一次建立索引，逐曲匹配不再请求媒体库 （几千首的库也能把媒体库请求压到 1 次）；关闭后按老办法每首歌检索一次。", -1)),
                    _cache[36] || (_cache[36] = _createElementVNode("p", { class: "ms-hint" }, "缺失曲目的搜索、识别、订阅都走宿主的官方音乐接口，插件不指定任何音乐来源 （搜哪些库由宿主自己的音乐元数据源设置决定）。", -1))
                  ]),
                  _createVNode(_component_v_divider),
                  _createElementVNode("section", _hoisted_15, [
                    _cache[38] || (_cache[38] = _createElementVNode("h3", { class: "ms-section__title" }, "媒体服务器", -1)),
                    _createVNode(_component_v_select, {
                      modelValue: form.media_server,
                      "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((form.media_server) = $event)),
                      items: mediaServers.value,
                      multiple: "",
                      chips: "",
                      "closable-chips": "",
                      label: "同步到哪些媒体服务器",
                      placeholder: "请选择已启用的媒体服务器"
                    }, null, 8, ["modelValue", "items"]),
                    _cache[39] || (_cache[39] = _createElementVNode("p", { class: "ms-hint" }, "列表来自「设置 → 媒体服务器」里已启用的服务器，支持多选。", -1)),
                    _createVNode(_component_v_switch, {
                      modelValue: form.exact_match,
                      "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((form.exact_match) = $event)),
                      color: "primary",
                      inset: ""
                    }, {
                      label: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                        _createElementVNode("span", { class: "ms-label" }, "曲目精确匹配", -1)
                      ]))]),
                      _: 1
                    }, 8, ["modelValue"]),
                    _cache[40] || (_cache[40] = _createElementVNode("p", { class: "ms-hint" }, "开启时按「歌名 + 歌手」精确判断曲库是否已存在；关闭后仅按歌名模糊匹配， 匹配更宽松但可能并入同名不同版本的曲目。", -1))
                  ])
                ], 64))
              : (tab.value === 'netease')
                ? (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
                    _createElementVNode("section", _hoisted_16, [
                      _cache[42] || (_cache[42] = _createElementVNode("h3", { class: "ms-section__title" }, "ncm-api 服务", -1)),
                      _createElementVNode("div", _hoisted_17, [
                        _createVNode(_component_v_text_field, {
                          modelValue: form.ncm_api_url,
                          "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((form.ncm_api_url) = $event)),
                          class: "ms-row__grow",
                          label: "服务地址",
                          placeholder: "http://192.168.1.100:1630"
                        }, null, 8, ["modelValue"]),
                        _createVNode(_component_v_btn, {
                          class: "ms-row__btn",
                          variant: "tonal",
                          loading: probing.value,
                          onClick: probe
                        }, {
                          default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                            _createTextVNode("探测连通性", -1)
                          ]))]),
                          _: 1
                        }, 8, ["loading"])
                      ]),
                      _cache[43] || (_cache[43] = _createElementVNode("p", { class: "ms-hint" }, "网易云的登录与取数都通过本地部署的 ncm-api 容器完成； 容器内的 3000 端口建议映射到宿主的 1630 端口，避免和 MoviePilot 冲突。", -1)),
                      (probeResult.value)
                        ? (_openBlock(), _createBlock(_component_v_alert, {
                            key: 0,
                            type: probeResult.value.code === 0 ? 'success' : 'error',
                            density: "compact",
                            variant: "tonal",
                            class: "mt-2"
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(probeResult.value.message), 1)
                            ]),
                            _: 1
                          }, 8, ["type"]))
                        : _createCommentVNode("", true)
                    ]),
                    _createVNode(_component_v_divider),
                    _createElementVNode("section", _hoisted_18, [
                      _cache[46] || (_cache[46] = _createElementVNode("h3", { class: "ms-section__title" }, "登录", -1)),
                      _createElementVNode("div", _hoisted_19, [
                        _createElementVNode("span", {
                          class: _normalizeClass(['ms-chip', loggedIn.value ? 'ms-chip--ok' : 'ms-chip--muted'])
                        }, [
                          _createVNode(_component_v_icon, {
                            icon: loggedIn.value ? 'mdi-account-music' : 'mdi-account-off',
                            size: "14"
                          }, null, 8, ["icon"]),
                          _createTextVNode(" " + _toDisplayString(loggedIn.value ? `已登录：${username.value}` : '未登录'), 1)
                        ], 2),
                        _createVNode(_component_v_btn, {
                          size: "small",
                          variant: "tonal",
                          color: "error",
                          "prepend-icon": "mdi-logout",
                          disabled: !loggedIn.value,
                          loading: logouting.value,
                          onClick: logout
                        }, {
                          default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                            _createTextVNode("退出登录", -1)
                          ]))]),
                          _: 1
                        }, 8, ["disabled", "loading"])
                      ]),
                      _createVNode(_component_v_btn, {
                        class: "mt-3",
                        color: "primary",
                        variant: "tonal",
                        "prepend-icon": "mdi-qrcode",
                        loading: qrLoading.value,
                        onClick: getQrcode
                      }, {
                        default: _withCtx(() => [...(_cache[45] || (_cache[45] = [
                          _createTextVNode("获取二维码", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading"]),
                      (qrimg.value)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_20, [
                            _createElementVNode("img", {
                              src: qrimg.value,
                              alt: "网易云扫码二维码"
                            }, null, 8, _hoisted_21),
                            _createElementVNode("div", _hoisted_22, _toDisplayString(qrMessage.value || '请使用网易云音乐 App 扫码'), 1)
                          ]))
                        : _createCommentVNode("", true),
                      (loginResult.value)
                        ? (_openBlock(), _createElementBlock("div", _hoisted_23, [
                            _createVNode(_component_v_alert, {
                              type: loginResult.value.code === 0 ? 'success' : 'error',
                              density: "compact",
                              variant: "tonal"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(loginResult.value.message), 1)
                              ]),
                              _: 1
                            }, 8, ["type"])
                          ]))
                        : _createCommentVNode("", true)
                    ])
                  ], 64))
                : (tab.value === 'sources')
                  ? (_openBlock(), _createElementBlock(_Fragment, { key: 2 }, [
                      _createElementVNode("section", _hoisted_24, [
                        _cache[49] || (_cache[49] = _createElementVNode("h3", { class: "ms-section__title" }, "网易云歌单", -1)),
                        _createVNode(_component_v_textarea, {
                          modelValue: form.wymusic_paths,
                          "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((form.wymusic_paths) = $event)),
                          rows: "4",
                          "auto-grow": "",
                          label: "歌单同步设置",
                          placeholder: "每行一条：歌单ID:播放列表名称[:emby用户名]"
                        }, null, 8, ["modelValue"]),
                        _cache[50] || (_cache[50] = _createElementVNode("p", { class: "ms-hint" }, [
                          _createTextVNode(" 示例："),
                          _createElementVNode("code", null, "2388086885:我喜欢的音乐"),
                          _createTextVNode("；Emby 多用户隔离时写 "),
                          _createElementVNode("code", null, "2388086885:我喜欢的音乐:张三,李四"),
                          _createTextVNode("。也支持直接粘贴歌单链接。 ")
                        ], -1)),
                        _createVNode(_component_v_switch, {
                          modelValue: form.wy_daily_list,
                          "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((form.wy_daily_list) = $event)),
                          color: "primary",
                          inset: ""
                        }, {
                          label: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                            _createElementVNode("span", { class: "ms-label" }, "同步每日推荐歌单", -1)
                          ]))]),
                          _: 1
                        }, 8, ["modelValue"]),
                        _createVNode(_component_v_switch, {
                          modelValue: form.wy_daily_song,
                          "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((form.wy_daily_song) = $event)),
                          color: "primary",
                          inset: ""
                        }, {
                          label: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                            _createElementVNode("span", { class: "ms-label" }, "同步每日推荐歌曲", -1)
                          ]))]),
                          _: 1
                        }, 8, ["modelValue"]),
                        _cache[51] || (_cache[51] = _createElementVNode("p", { class: "ms-hint" }, "每日推荐需要网易云登录态，未登录时该任务会跳过并在日志里说明原因。", -1))
                      ]),
                      _createVNode(_component_v_divider),
                      _createElementVNode("section", _hoisted_25, [
                        _cache[52] || (_cache[52] = _createElementVNode("h3", { class: "ms-section__title" }, "QQ 音乐歌单", -1)),
                        _createVNode(_component_v_textarea, {
                          modelValue: form.qqmusic_paths,
                          "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((form.qqmusic_paths) = $event)),
                          rows: "3",
                          "auto-grow": "",
                          label: "歌单同步设置",
                          placeholder: "每行一条：歌单ID:播放列表名称[:emby用户名]"
                        }, null, 8, ["modelValue"])
                      ]),
                      _createVNode(_component_v_divider),
                      _createElementVNode("section", _hoisted_26, [
                        _cache[53] || (_cache[53] = _createElementVNode("h3", { class: "ms-section__title" }, "其它平台歌单", -1)),
                        _createVNode(_component_v_textarea, {
                          modelValue: form.other_paths,
                          "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((form.other_paths) = $event)),
                          rows: "4",
                          "auto-grow": "",
                          label: "歌单同步设置",
                          placeholder: "每行一条：平台|标识符|播放列表名称[:emby用户名]\n例：spotify|https://open.spotify.com/playlist/xxx|每日推荐\nkugou|12345|华语精选"
                        }, null, 8, ["modelValue"]),
                        _cache[54] || (_cache[54] = _createElementVNode("p", { class: "ms-hint" }, [
                          _createTextVNode("用 "),
                          _createElementVNode("code", null, "|"),
                          _createTextVNode(" 分隔（因为标识符可能是 URL）。支持的标识： "),
                          _createElementVNode("code", null, "spotify"),
                          _createTextVNode(" / "),
                          _createElementVNode("code", null, "kugou"),
                          _createTextVNode(" / "),
                          _createElementVNode("code", null, "kuwo"),
                          _createTextVNode(" / "),
                          _createElementVNode("code", null, "migu"),
                          _createTextVNode("。")
                        ], -1))
                      ]),
                      _createVNode(_component_v_divider),
                      _createElementVNode("section", _hoisted_27, [
                        _cache[55] || (_cache[55] = _createElementVNode("h3", { class: "ms-section__title" }, "Spotify 凭据", -1)),
                        _createElementVNode("div", _hoisted_28, [
                          _createVNode(_component_v_text_field, {
                            modelValue: form.spotify_client_id,
                            "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((form.spotify_client_id) = $event)),
                            label: "Client ID",
                            class: "ms-row__grow",
                            placeholder: "Spotify 开发者后台申请"
                          }, null, 8, ["modelValue"]),
                          _createVNode(_component_v_text_field, {
                            modelValue: form.spotify_client_secret,
                            "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((form.spotify_client_secret) = $event)),
                            label: "Client Secret",
                            class: "ms-row__grow",
                            type: "password",
                            placeholder: "Client Secret"
                          }, null, 8, ["modelValue"])
                        ]),
                        _cache[56] || (_cache[56] = _createElementVNode("p", { class: "ms-hint" }, [
                          _createTextVNode("仅 Spotify 歌单需要。在 "),
                          _createElementVNode("code", null, "https://developer.spotify.com/dashboard"),
                          _createTextVNode(" 创建 App 后取用。")
                        ], -1))
                      ]),
                      _createVNode(_component_v_divider),
                      (platforms.value.length)
                        ? (_openBlock(), _createElementBlock("section", _hoisted_29, [
                            _cache[57] || (_cache[57] = _createElementVNode("h3", { class: "ms-section__title" }, "平台可用性", -1)),
                            _createElementVNode("div", _hoisted_30, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(platforms.value, (p) => {
                                return (_openBlock(), _createElementBlock("div", {
                                  key: p.name,
                                  class: _normalizeClass(['ms-platform', p.available ? 'ms-platform--ok' : 'ms-platform--off'])
                                }, [
                                  _createElementVNode("span", _hoisted_31, _toDisplayString(p.label), 1),
                                  _createElementVNode("span", _hoisted_32, _toDisplayString(p.available ? '可用' : (p.reason || '不可用')), 1)
                                ], 2))
                              }), 128))
                            ])
                          ]))
                        : _createCommentVNode("", true)
                    ], 64))
                  : (_openBlock(), _createElementBlock(_Fragment, { key: 3 }, [
                      (!stats.value.start_time)
                        ? (_openBlock(), _createElementBlock("section", _hoisted_33, [
                            _createVNode(_component_v_alert, {
                              density: "compact",
                              type: "info",
                              variant: "tonal"
                            }, {
                              default: _withCtx(() => [...(_cache[58] || (_cache[58] = [
                                _createTextVNode("还没有同步记录，配置保存后手动运行一次即可。", -1)
                              ]))]),
                              _: 1
                            })
                          ]))
                        : (_openBlock(), _createElementBlock("section", _hoisted_34, [
                            _createElementVNode("div", _hoisted_35, [
                              _createElementVNode("div", _hoisted_36, [
                                _createElementVNode("span", _hoisted_37, _toDisplayString(stats.value.duration || 0), 1),
                                _cache[59] || (_cache[59] = _createElementVNode("span", { class: "ms-stat__label" }, "耗时（秒）", -1))
                              ]),
                              _createElementVNode("div", _hoisted_38, [
                                _createElementVNode("span", _hoisted_39, _toDisplayString(stats.value.missing || 0), 1),
                                _cache[60] || (_cache[60] = _createElementVNode("span", { class: "ms-stat__label" }, "库内缺失", -1))
                              ]),
                              _createElementVNode("div", _hoisted_40, [
                                _createElementVNode("span", _hoisted_41, _toDisplayString((stats.value.playlists || []).length), 1),
                                _cache[61] || (_cache[61] = _createElementVNode("span", { class: "ms-stat__label" }, "歌单数", -1))
                              ]),
                              _createElementVNode("div", _hoisted_42, [
                                _createElementVNode("span", _hoisted_43, _toDisplayString(addedTotal.value), 1),
                                _cache[62] || (_cache[62] = _createElementVNode("span", { class: "ms-stat__label" }, "新增曲目", -1))
                              ]),
                              _createElementVNode("div", _hoisted_44, [
                                _createElementVNode("span", _hoisted_45, _toDisplayString(metrics.value.index_entries || 0), 1),
                                _createElementVNode("span", _hoisted_46, _toDisplayString(metrics.value.used_index ? '索引曲目' : '未用索引'), 1)
                              ]),
                              _createElementVNode("div", _hoisted_47, [
                                _createElementVNode("span", _hoisted_48, _toDisplayString(metrics.value.library_requests || 0), 1),
                                _cache[63] || (_cache[63] = _createElementVNode("span", { class: "ms-stat__label" }, "媒体库请求", -1))
                              ])
                            ]),
                            _createElementVNode("p", _hoisted_49, [
                              _createTextVNode(" 上次开始时间：" + _toDisplayString(stats.value.start_time), 1),
                              (stats.value.error)
                                ? (_openBlock(), _createElementBlock("span", _hoisted_50, "（异常：" + _toDisplayString(stats.value.error) + "）", 1))
                                : _createCommentVNode("", true),
                              (running.value)
                                ? (_openBlock(), _createElementBlock("span", _hoisted_51, "同步进行中"))
                                : (stats.value.skipped_at)
                                  ? (_openBlock(), _createElementBlock("span", _hoisted_52, _toDisplayString(stats.value.skipped_at) + " 有一次触发被跳过（已有同步在跑） ", 1))
                                  : _createCommentVNode("", true)
                            ]),
                            _createElementVNode("p", _hoisted_53, [
                              _createTextVNode(" 分段耗时：拉取歌单 " + _toDisplayString(metrics.value.fetch_seconds ?? 0) + " 秒 · 推送播放列表 " + _toDisplayString(metrics.value.push_seconds ?? 0) + " 秒 · 登记缺失 " + _toDisplayString(metrics.value.missing_seconds ?? 0) + " 秒 ", 1),
                              (metrics.value.reused_snapshot)
                                ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                                    _createTextVNode("（" + _toDisplayString(metrics.value.reused_snapshot) + " 个歌单读取失败，沿用了上次快照）", 1)
                                  ], 64))
                                : _createCommentVNode("", true)
                            ]),
                            ((stats.value.playlists || []).length)
                              ? (_openBlock(), _createElementBlock("table", _hoisted_54, [
                                  _cache[64] || (_cache[64] = _createElementVNode("thead", null, [
                                    _createElementVNode("tr", null, [
                                      _createElementVNode("th", null, "数据源"),
                                      _createElementVNode("th", null, "播放列表"),
                                      _createElementVNode("th", { class: "num" }, "曲目"),
                                      _createElementVNode("th", { class: "num" }, "新增"),
                                      _createElementVNode("th", { class: "num" }, "缺失"),
                                      _createElementVNode("th", null, "结果")
                                    ])
                                  ], -1)),
                                  _createElementVNode("tbody", null, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(stats.value.playlists, (p, i) => {
                                      return (_openBlock(), _createElementBlock("tr", { key: i }, [
                                        _createElementVNode("td", null, _toDisplayString(p.source), 1),
                                        _createElementVNode("td", null, _toDisplayString(p.name), 1),
                                        _createElementVNode("td", _hoisted_55, _toDisplayString(p.total || 0), 1),
                                        _createElementVNode("td", _hoisted_56, _toDisplayString(p.added || 0), 1),
                                        _createElementVNode("td", _hoisted_57, _toDisplayString(p.missing || 0), 1),
                                        _createElementVNode("td", null, [
                                          _createElementVNode("span", {
                                            class: _normalizeClass(['ms-chip', p.status === 'ok' ? 'ms-chip--ok' : 'ms-chip--err'])
                                          }, _toDisplayString(p.status === 'ok' ? '成功' : '失败'), 3),
                                          (p.message)
                                            ? (_openBlock(), _createElementBlock("span", _hoisted_58, _toDisplayString(p.message), 1))
                                            : _createCommentVNode("", true)
                                        ])
                                      ]))
                                    }), 128))
                                  ])
                                ]))
                              : _createCommentVNode("", true)
                          ]))
                    ], 64))
          ], 64))
    ]),
    _createElementVNode("footer", _hoisted_59, [
      _createVNode(_component_v_btn, {
        variant: "tonal",
        "prepend-icon": "mdi-play-circle-outline",
        disabled: !form.enabled,
        loading: running.value,
        onClick: runOnce
      }, {
        default: _withCtx(() => [...(_cache[65] || (_cache[65] = [
          _createTextVNode("立即运行一次", -1)
        ]))]),
        _: 1
      }, 8, ["disabled", "loading"]),
      _createVNode(_component_v_spacer),
      _createVNode(_component_v_btn, {
        variant: "text",
        "prepend-icon": "mdi-format-list-bulleted",
        onClick: _cache[18] || (_cache[18] = $event => (emit('switch')))
      }, {
        default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
          _createTextVNode("查看缺失清单", -1)
        ]))]),
        _: 1
      })
    ])
  ]))
}
}

};
const ConfigComponent = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-6d46d9d6"]]);

export { ConfigComponent as default };
