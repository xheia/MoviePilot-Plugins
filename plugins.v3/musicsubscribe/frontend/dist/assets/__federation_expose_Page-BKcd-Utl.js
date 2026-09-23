import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,toDisplayString:_toDisplayString,mergeProps:_mergeProps} = await importShared('vue');


const _hoisted_1 = { class: "ms-page" };
const _hoisted_2 = { class: "ms-head" };
const _hoisted_3 = { class: "ms-head__brand" };
const _hoisted_4 = { class: "ms-head__logo" };
const _hoisted_5 = { class: "ms-head__crumbs" };
const _hoisted_6 = { class: "ms-head__actions" };
const _hoisted_7 = { class: "ms-tabs" };
const _hoisted_8 = { class: "ms-stats" };
const _hoisted_9 = ["onClick"];
const _hoisted_10 = { class: "ms-stat__num" };
const _hoisted_11 = { class: "ms-stat__label" };
const _hoisted_12 = { class: "ms-stat__num" };
const _hoisted_13 = { class: "ms-stat ms-stat--plain" };
const _hoisted_14 = { class: "ms-stat__num" };
const _hoisted_15 = { class: "ms-toolbar" };
const _hoisted_16 = {
  key: 0,
  class: "ms-toolbar__group"
};
const _hoisted_17 = { class: "ms-body" };
const _hoisted_18 = {
  key: 0,
  class: "ms-empty"
};
const _hoisted_19 = {
  key: 0,
  class: "ms-table"
};
const _hoisted_20 = { class: "col-seq" };
const _hoisted_21 = { class: "col-pick" };
const _hoisted_22 = ["name", "checked", "onChange"];
const _hoisted_23 = { class: "col-pick" };
const _hoisted_24 = ["name", "checked", "onChange"];
const _hoisted_25 = { class: "ms-title" };
const _hoisted_26 = { class: "ms-sub" };
const _hoisted_27 = { class: "ms-src" };
const _hoisted_28 = { key: 0 };
const _hoisted_29 = {
  key: 1,
  class: "ms-fail"
};
const _hoisted_30 = { class: "col-dur" };
const _hoisted_31 = { class: "col-link" };
const _hoisted_32 = ["disabled", "onClick"];
const _hoisted_33 = ["href"];
const _hoisted_34 = {
  key: 1,
  class: "ms-link-off"
};
const _hoisted_35 = {
  key: 1,
  class: "ms-table"
};
const _hoisted_36 = { class: "col-seq" };
const _hoisted_37 = { class: "ms-title" };
const _hoisted_38 = { class: "ms-sub" };
const _hoisted_39 = { class: "ms-src" };
const _hoisted_40 = { key: 0 };
const _hoisted_41 = { key: 1 };
const _hoisted_42 = { class: "col-dur" };
const _hoisted_43 = { class: "col-pick" };
const _hoisted_44 = { class: "col-time" };
const _hoisted_45 = { class: "col-link" };
const _hoisted_46 = ["href"];
const _hoisted_47 = {
  key: 1,
  class: "ms-link-off"
};
const _hoisted_48 = {
  key: 3,
  class: "ms-empty"
};
const _hoisted_49 = {
  key: 4,
  class: "ms-empty"
};
const _hoisted_50 = {
  key: 2,
  class: "ms-pager"
};
const _hoisted_51 = { class: "ms-pager__info" };
const _hoisted_52 = {
  key: 3,
  class: "ms-foot"
};
const _hoisted_53 = { class: "ms-foot__count" };
const _hoisted_54 = {
  key: 4,
  class: "ms-foot"
};
const _hoisted_55 = { class: "ms-foot__count" };

const {computed,onMounted,reactive,ref,watch} = await importShared('vue');


const PLUGIN = 'plugin/MusicSubscribe';


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
  show_switch: { type: Boolean, default: true },
},
  emits: ['switch', 'close', 'action'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;

const loading = ref(false);
const subscribing = ref(false);
const removing = ref(false);
const clearingHistory = ref(false);
const linking = ref(null);
const error = ref('');
const result = ref('');
const resultLevel = ref('success');

// pending = 待订阅清单，history = 订阅历史
const view = ref('pending');

const items = ref([]);
const historyItems = ref([]);
const summary = reactive({ total: 0, failed: 0 });
const historySummary = reactive({ total: 0, song: 0, album: 0 });
const stats = ref({});
const targets = ref([{ value: 'song', label: '歌曲' }, { value: 'album', label: '专辑' }]);
const targetOptions = [{ value: 'song', label: '歌曲' }, { value: 'album', label: '专辑' }];
const targetFilter = ref(null);
// seq -> { song, album, artist }（按需查询，避免同步时给每首歌都做一次识别）
const linkCache = reactive({});

const scope = ref('all');
const keyword = ref('');
const sourceFilter = ref(null);
const page = ref(1);
const pageSize = ref(20);

// seq -> 'song' | 'album'
const picks = reactive({});

const syncMissing = computed(() => Number(stats.value?.missing) || 0);

const statCards = computed(() => [
  { key: 'all', label: '待处理', count: summary.total },
  { key: 'failed', label: '订阅失败', count: summary.failed },
]);

const sourceOptions = computed(() => {
  const set = new Set(items.value.map(i => i.source).filter(Boolean));
  return [...set]
});

const pendingRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  let list = items.value;
  if (scope.value === 'failed') list = list.filter(i => !!(i.subscribe_message || ''));
  if (sourceFilter.value) list = list.filter(i => i.source === sourceFilter.value);
  if (kw) {
    list = list.filter(i =>
      String(i.title || '').toLowerCase().includes(kw) ||
      String(i.artist || '').toLowerCase().includes(kw) ||
      String(i.album || '').toLowerCase().includes(kw));
  }
  return list
});

const historyRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  let list = historyItems.value;
  if (targetFilter.value) list = list.filter(i => (i.target || 'song') === targetFilter.value);
  if (kw) {
    list = list.filter(i =>
      String(i.title || '').toLowerCase().includes(kw) ||
      String(i.artist || '').toLowerCase().includes(kw) ||
      String(i.album || '').toLowerCase().includes(kw));
  }
  return list
});

const rows = computed(() => (view.value === 'history' ? historyRows.value : pendingRows.value));

const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / Number(pageSize.value))));
const pagedRows = computed(() => {
  const size = Number(pageSize.value);
  return rows.value.slice((page.value - 1) * size, page.value * size)
});

const pickedCount = computed(() => {
  const alive = new Set(items.value.map(i => Number(i.seq)));
  return Object.keys(picks).filter(seq => picks[seq] && alive.has(Number(seq))).length
});

const countByTarget = computed(() => {
  const out = { song: 0, album: 0 };
  const alive = new Set(items.value.map(i => Number(i.seq)));
  Object.keys(picks).forEach(seq => {
    const t = picks[seq];
    if (t && alive.has(Number(seq)) && out[t] !== undefined) out[t] += 1;
  });
  return out
});

function call(method, path, data) {
  const fn = props?.api?.[method];
  if (typeof fn !== 'function') throw new Error('API 不可用')
  return data === undefined ? fn(path) : fn(path, data)
}

async function load() {
  if (view.value === 'history') return loadHistory()
  loading.value = true;
  error.value = '';
  try {
    const res = await call('get', `${PLUGIN}/pending?scope=${encodeURIComponent(scope.value)}`);
    items.value = Array.isArray(res?.items) ? res.items : [];
    Object.assign(summary, res?.summary || { total: 0, failed: 0 });
    Object.assign(historySummary, res?.history || { total: 0, song: 0, album: 0 });
    stats.value = res?.stats || {};
    if (Array.isArray(res?.targets) && res.targets.length) targets.value = res.targets;
    const alive = new Set(items.value.map(i => Number(i.seq)));
    Object.keys(picks).forEach(seq => { if (!alive.has(Number(seq))) delete picks[seq]; });
    Object.keys(linkCache).forEach(seq => { if (!alive.has(Number(seq))) delete linkCache[seq]; });
    if (page.value > pageCount.value) page.value = pageCount.value;
  } catch (e) {
    error.value = '加载缺失清单失败：' + (e?.message || e);
    items.value = [];
  } finally {
    loading.value = false;
    emit('action');
  }
}

async function loadHistory() {
  loading.value = true;
  error.value = '';
  try {
    const res = await call('get', `${PLUGIN}/history`);
    historyItems.value = Array.isArray(res?.items) ? res.items : [];
    Object.assign(historySummary, res?.summary || { total: 0, song: 0, album: 0 });
    if (page.value > pageCount.value) page.value = pageCount.value;
  } catch (e) {
    error.value = '加载订阅历史失败：' + (e?.message || e);
    historyItems.value = [];
  } finally {
    loading.value = false;
    emit('action');
  }
}

function switchView(next) {
  if (view.value === next) return load()
  view.value = next;
  page.value = 1;
  keyword.value = '';
  return load()
}

function switchScope(next) {
  view.value = 'pending';
  scope.value = next;
}

async function loadLink(row) {
  const seq = Number(row.seq);
  linking.value = seq;
  result.value = '';
  try {
    const res = await call('post', `${PLUGIN}/pending/link`, { seq });
    if (res?.code === 0) {
      linkCache[seq] = res.links || {};
    } else {
      resultLevel.value = 'warning';
      result.value = res?.message || '没查到官方链接';
    }
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '查询链接失败：' + (e?.message || e);
  } finally {
    linking.value = null;
  }
}

async function clearHistory() {
  clearingHistory.value = true;
  result.value = '';
  try {
    const res = await call('post', `${PLUGIN}/history/clear`);
    resultLevel.value = res?.code === 0 ? 'success' : 'error';
    result.value = res?.message || '已清空订阅历史';
    historyItems.value = [];
    Object.assign(historySummary, res?.summary || { total: 0, song: 0, album: 0 });
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '清空订阅历史失败：' + (e?.message || e);
  } finally {
    clearingHistory.value = false;
  }
}

function pick(row, target) {
  const seq = Number(row.seq);
  // 同一序号歌曲与专辑二选一：再次勾选时切换粒度
  picks[seq] = target;
}

function selectAll() {
  pendingRows.value.forEach(row => { picks[Number(row.seq)] = 'song'; });
}

function invert() {
  pendingRows.value.forEach(row => {
    const seq = Number(row.seq);
    const cur = picks[seq];
    if (!cur) picks[seq] = 'song';
    else if (cur === 'song') picks[seq] = row.album ? 'album' : undefined;
    else delete picks[seq];
  });
}

function clearPick() {
  pendingRows.value.forEach(row => { delete picks[Number(row.seq)]; });
}

function linkEntries(links) {
  const got = links || {};
  return [
    { key: 'song', label: '歌曲', url: got.song || '' },
    { key: 'album', label: '专辑', url: got.album || '' },
    { key: 'artist', label: '歌手', url: got.artist || '' },
  ]
}

async function subscribePicked() {
  const payload = Object.keys(picks)
    .map(seq => ({ seq: Number(seq), target: picks[seq] }))
    .filter(i => i.target);
  if (!payload.length) return
  subscribing.value = true;
  error.value = '';
  result.value = '';
  try {
    const res = await call('post', `${PLUGIN}/pending/subscribe`, { items: payload });
    if (res?.code === 0) {
      const failed = (res.results || []).filter(r => !r.ok);
      const detail = failed.map(f => `${f.title}（${f.message}）`).slice(0, 3).join('；');
      resultLevel.value = failed.length ? 'warning' : 'success';
      result.value = failed.length
        ? `订阅完成：${payload.length - failed.length} 条订阅成功（可在「订阅历史」里查看），${failed.length} 条失败：${detail}`
        : (res.message || '订阅完成');
      clearPick();
      await load();
    } else {
      resultLevel.value = 'error';
      result.value = res?.message || '订阅失败';
    }
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '订阅失败：' + (e?.message || e);
  } finally {
    subscribing.value = false;
  }
}

async function removePicked() {
  const seqs = Object.keys(picks).filter(seq => picks[seq]).map(Number);
  if (!seqs.length) return
  removing.value = true;
  result.value = '';
  try {
    const res = await call('post', `${PLUGIN}/pending/remove`, { seqs });
    if (res?.code === 0) {
      seqs.forEach(s => delete picks[s]);
      resultLevel.value = 'success';
      result.value = res.message || '已移除';
      await load();
    } else {
      resultLevel.value = 'error';
      result.value = res?.message || '移除失败';
    }
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '移除失败：' + (e?.message || e);
  } finally {
    removing.value = false;
  }
}

async function clearPending(sc) {
  removing.value = true;
  result.value = '';
  try {
    const res = await call('post', `${PLUGIN}/pending/clear?scope=${encodeURIComponent(sc)}`);
    resultLevel.value = res?.code === 0 ? 'success' : 'error';
    result.value = res?.message || '已清理';
    Object.keys(picks).forEach(s => delete picks[s]);
    await load();
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '清理失败：' + (e?.message || e);
  } finally {
    removing.value = false;
  }
}

watch([scope, keyword, sourceFilter, targetFilter, pageSize], () => { page.value = 1; });
watch(scope, load);

onMounted(load);

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_tooltip = _resolveComponent("v-tooltip");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_spacer = _resolveComponent("v-spacer");
  const _component_v_list_item = _resolveComponent("v-list-item");
  const _component_v_list = _resolveComponent("v-list");
  const _component_v_menu = _resolveComponent("v-menu");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_v_icon, {
            icon: "mdi-playlist-music",
            size: "20"
          })
        ]),
        _createElementVNode("div", null, [
          _createElementVNode("div", _hoisted_5, [
            _cache[15] || (_cache[15] = _createElementVNode("span", null, "MoviePilot", -1)),
            _createVNode(_component_v_icon, {
              icon: "mdi-chevron-right",
              size: "13"
            }),
            _cache[16] || (_cache[16] = _createElementVNode("span", null, "插件", -1))
          ]),
          _cache[17] || (_cache[17] = _createElementVNode("h1", { class: "ms-head__title" }, "库内缺失曲目", -1))
        ])
      ]),
      _createElementVNode("div", _hoisted_6, [
        (__props.show_switch)
          ? (_openBlock(), _createBlock(_component_v_btn, {
              key: 0,
              variant: "text",
              "prepend-icon": "mdi-cog-outline",
              onClick: _cache[0] || (_cache[0] = $event => (emit('switch')))
            }, {
              default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                _createTextVNode("同步配置", -1)
              ]))]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_btn, {
          icon: "mdi-refresh",
          size: "small",
          variant: "text",
          loading: loading.value,
          "aria-label": "刷新",
          onClick: _cache[1] || (_cache[1] = $event => (load()))
        }, null, 8, ["loading"]),
        _createVNode(_component_v_btn, {
          icon: "mdi-close",
          size: "small",
          variant: "text",
          "aria-label": "关闭",
          onClick: _cache[2] || (_cache[2] = $event => (emit('close')))
        })
      ])
    ]),
    _createElementVNode("div", _hoisted_7, [
      _createElementVNode("button", {
        type: "button",
        class: _normalizeClass(['ms-tab', { 'ms-tab--active': view.value === 'pending' }]),
        onClick: _cache[3] || (_cache[3] = $event => (switchView('pending')))
      }, "待订阅清单", 2),
      _createElementVNode("button", {
        type: "button",
        class: _normalizeClass(['ms-tab', { 'ms-tab--active': view.value === 'history' }]),
        onClick: _cache[4] || (_cache[4] = $event => (switchView('history')))
      }, "订阅历史", 2)
    ]),
    _createElementVNode("div", _hoisted_8, [
      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(statCards.value, (s) => {
        return (_openBlock(), _createElementBlock("button", {
          key: s.key,
          type: "button",
          class: _normalizeClass(['ms-stat', { 'ms-stat--active': view.value === 'pending' && scope.value === s.key }]),
          onClick: $event => (switchScope(s.key))
        }, [
          _createElementVNode("span", _hoisted_10, _toDisplayString(s.count), 1),
          _createElementVNode("span", _hoisted_11, _toDisplayString(s.label), 1)
        ], 10, _hoisted_9))
      }), 128)),
      _createElementVNode("button", {
        type: "button",
        class: _normalizeClass(['ms-stat', { 'ms-stat--active': view.value === 'history' }]),
        onClick: _cache[5] || (_cache[5] = $event => (switchView('history')))
      }, [
        _createElementVNode("span", _hoisted_12, _toDisplayString(historySummary.total), 1),
        _cache[19] || (_cache[19] = _createElementVNode("span", { class: "ms-stat__label" }, "订阅历史", -1))
      ], 2),
      _createElementVNode("div", _hoisted_13, [
        _createElementVNode("span", _hoisted_14, _toDisplayString(syncMissing.value), 1),
        _cache[20] || (_cache[20] = _createElementVNode("span", { class: "ms-stat__label" }, "上次同步缺失", -1))
      ])
    ]),
    (error.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 0,
          class: "mx-3 mb-2",
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
    (result.value)
      ? (_openBlock(), _createBlock(_component_v_alert, {
          key: 1,
          class: "mx-3 mb-2",
          density: "compact",
          type: resultLevel.value,
          variant: "tonal"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(result.value), 1)
          ]),
          _: 1
        }, 8, ["type"]))
      : _createCommentVNode("", true),
    _createElementVNode("div", _hoisted_15, [
      (view.value === 'pending')
        ? (_openBlock(), _createElementBlock("div", _hoisted_16, [
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "tonal",
              onClick: _cache[6] || (_cache[6] = $event => (selectAll()))
            }, {
              default: _withCtx(() => [...(_cache[21] || (_cache[21] = [
                _createTextVNode("全选", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "tonal",
              onClick: invert
            }, {
              default: _withCtx(() => [
                _cache[22] || (_cache[22] = _createTextVNode(" 反选 ", -1)),
                _createVNode(_component_v_tooltip, {
                  activator: "parent",
                  location: "bottom",
                  text: "未勾选 → 歌曲；已选歌曲 → 专辑；已选专辑 → 取消"
                })
              ]),
              _: 1
            }),
            _createVNode(_component_v_btn, {
              size: "small",
              variant: "text",
              disabled: !pickedCount.value,
              onClick: clearPick
            }, {
              default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                _createTextVNode("清空选择", -1)
              ]))]),
              _: 1
            }, 8, ["disabled"])
          ]))
        : _createCommentVNode("", true),
      _createVNode(_component_v_text_field, {
        modelValue: keyword.value,
        "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((keyword).value = $event)),
        class: "ms-toolbar__search",
        density: "compact",
        variant: "outlined",
        placeholder: view.value === 'history' ? '搜索订阅历史：歌名 / 歌手 / 专辑' : '搜索歌名 / 歌手 / 专辑',
        "prepend-inner-icon": "mdi-magnify",
        "hide-details": "",
        "single-line": ""
      }, null, 8, ["modelValue", "placeholder"]),
      (view.value === 'pending')
        ? (_openBlock(), _createBlock(_component_v_select, {
            key: 1,
            modelValue: sourceFilter.value,
            "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((sourceFilter).value = $event)),
            items: sourceOptions.value,
            class: "ms-toolbar__source",
            density: "compact",
            variant: "outlined",
            label: "数据源",
            "hide-details": "",
            "single-line": "",
            clearable: ""
          }, null, 8, ["modelValue", "items"]))
        : (_openBlock(), _createBlock(_component_v_select, {
            key: 2,
            modelValue: targetFilter.value,
            "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((targetFilter).value = $event)),
            items: targetOptions,
            class: "ms-toolbar__source",
            density: "compact",
            variant: "outlined",
            label: "订阅粒度",
            "hide-details": "",
            "single-line": "",
            clearable: ""
          }, null, 8, ["modelValue"]))
    ]),
    _createElementVNode("div", _hoisted_17, [
      (loading.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_18, "加载中…"))
        : (_openBlock(), _createElementBlock(_Fragment, { key: 1 }, [
            (view.value === 'pending' && pagedRows.value.length)
              ? (_openBlock(), _createElementBlock("table", _hoisted_19, [
                  _cache[24] || (_cache[24] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", { class: "col-seq" }, "序号"),
                      _createElementVNode("th", { class: "col-pick" }, "选择歌曲"),
                      _createElementVNode("th", { class: "col-pick" }, "选择专辑"),
                      _createElementVNode("th", null, "歌曲名称"),
                      _createElementVNode("th", { class: "col-dur" }, "时长"),
                      _createElementVNode("th", null, "歌手"),
                      _createElementVNode("th", null, "专辑名称"),
                      _createElementVNode("th", { class: "col-link" }, "官方链接")
                    ])
                  ], -1)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(pagedRows.value, (row) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: row.seq,
                        class: _normalizeClass({ 'ms-row--fail': row.subscribe_message })
                      }, [
                        _createElementVNode("td", _hoisted_20, _toDisplayString(row.seq), 1),
                        _createElementVNode("td", _hoisted_21, [
                          _createElementVNode("input", {
                            type: "radio",
                            name: `pick-${row.seq}`,
                            checked: picks[row.seq] === 'song',
                            onChange: $event => (pick(row, 'song'))
                          }, null, 40, _hoisted_22)
                        ]),
                        _createElementVNode("td", _hoisted_23, [
                          _createElementVNode("input", {
                            type: "radio",
                            name: `pick-${row.seq}`,
                            checked: picks[row.seq] === 'album',
                            onChange: $event => (pick(row, 'album'))
                          }, null, 40, _hoisted_24)
                        ]),
                        _createElementVNode("td", null, [
                          _createElementVNode("div", _hoisted_25, _toDisplayString(row.title), 1),
                          _createElementVNode("div", _hoisted_26, [
                            _createElementVNode("span", _hoisted_27, _toDisplayString(row.source), 1),
                            (row.hits > 1)
                              ? (_openBlock(), _createElementBlock("span", _hoisted_28, " · 命中 " + _toDisplayString(row.hits) + " 次", 1))
                              : _createCommentVNode("", true),
                            (row.subscribe_message)
                              ? (_openBlock(), _createElementBlock("span", _hoisted_29, " · 上次订阅失败：" + _toDisplayString(row.subscribe_message), 1))
                              : _createCommentVNode("", true)
                          ])
                        ]),
                        _createElementVNode("td", _hoisted_30, _toDisplayString(row.duration_text || '-'), 1),
                        _createElementVNode("td", null, _toDisplayString(row.artist || '-'), 1),
                        _createElementVNode("td", null, _toDisplayString(row.album || '-'), 1),
                        _createElementVNode("td", _hoisted_31, [
                          (!linkCache[row.seq])
                            ? (_openBlock(), _createElementBlock("button", {
                                key: 0,
                                type: "button",
                                class: "ms-linkbtn",
                                disabled: linking.value === row.seq,
                                onClick: $event => (loadLink(row))
                              }, _toDisplayString(linking.value === row.seq ? '查询中…' : '查询链接'), 9, _hoisted_32))
                            : (_openBlock(true), _createElementBlock(_Fragment, { key: 1 }, _renderList(linkEntries(linkCache[row.seq]), (l) => {
                                return (_openBlock(), _createElementBlock("span", {
                                  key: `${row.seq}-${l.key}`
                                }, [
                                  (l.url)
                                    ? (_openBlock(), _createElementBlock("a", {
                                        key: 0,
                                        href: l.url,
                                        target: "_blank",
                                        rel: "noopener"
                                      }, _toDisplayString(l.label), 9, _hoisted_33))
                                    : (_openBlock(), _createElementBlock("span", _hoisted_34, _toDisplayString(l.label), 1))
                                ]))
                              }), 128))
                        ])
                      ], 2))
                    }), 128))
                  ])
                ]))
              : (view.value === 'history' && pagedRows.value.length)
                ? (_openBlock(), _createElementBlock("table", _hoisted_35, [
                    _cache[25] || (_cache[25] = _createElementVNode("thead", null, [
                      _createElementVNode("tr", null, [
                        _createElementVNode("th", { class: "col-seq" }, "序号"),
                        _createElementVNode("th", null, "歌曲名称"),
                        _createElementVNode("th", null, "歌手"),
                        _createElementVNode("th", null, "专辑名称"),
                        _createElementVNode("th", { class: "col-dur" }, "时长"),
                        _createElementVNode("th", { class: "col-pick" }, "粒度"),
                        _createElementVNode("th", null, "订阅人"),
                        _createElementVNode("th", { class: "col-time" }, "订阅时间"),
                        _createElementVNode("th", { class: "col-link" }, "官方链接")
                      ])
                    ], -1)),
                    _createElementVNode("tbody", null, [
                      (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(pagedRows.value, (row) => {
                        return (_openBlock(), _createElementBlock("tr", {
                          key: `h-${row.seq}`
                        }, [
                          _createElementVNode("td", _hoisted_36, _toDisplayString(row.seq), 1),
                          _createElementVNode("td", null, [
                            _createElementVNode("div", _hoisted_37, _toDisplayString(row.title), 1),
                            _createElementVNode("div", _hoisted_38, [
                              _createElementVNode("span", _hoisted_39, _toDisplayString(row.playlist || row.origin || '歌单'), 1),
                              (row.subscribe_id)
                                ? (_openBlock(), _createElementBlock("span", _hoisted_40, " · 订阅 #" + _toDisplayString(row.subscribe_id), 1))
                                : (row.message)
                                  ? (_openBlock(), _createElementBlock("span", _hoisted_41, " · " + _toDisplayString(row.message), 1))
                                  : _createCommentVNode("", true)
                            ])
                          ]),
                          _createElementVNode("td", null, _toDisplayString(row.artist || '-'), 1),
                          _createElementVNode("td", null, _toDisplayString(row.album || '-'), 1),
                          _createElementVNode("td", _hoisted_42, _toDisplayString(row.duration_text || '-'), 1),
                          _createElementVNode("td", _hoisted_43, _toDisplayString(row.target === 'album' ? '专辑' : '歌曲'), 1),
                          _createElementVNode("td", null, _toDisplayString(row.user || '-'), 1),
                          _createElementVNode("td", _hoisted_44, _toDisplayString(row.time || '-'), 1),
                          _createElementVNode("td", _hoisted_45, [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(linkEntries(row.links), (l) => {
                              return (_openBlock(), _createElementBlock("span", {
                                key: `h-${row.seq}-${l.key}`
                              }, [
                                (l.url)
                                  ? (_openBlock(), _createElementBlock("a", {
                                      key: 0,
                                      href: l.url,
                                      target: "_blank",
                                      rel: "noopener"
                                    }, _toDisplayString(l.label), 9, _hoisted_46))
                                  : (_openBlock(), _createElementBlock("span", _hoisted_47, _toDisplayString(l.label), 1))
                              ]))
                            }), 128))
                          ])
                        ]))
                      }), 128))
                    ])
                  ]))
                : (keyword.value || sourceFilter.value)
                  ? (_openBlock(), _createBlock(_component_v_alert, {
                      key: 2,
                      density: "compact",
                      type: "info",
                      variant: "tonal"
                    }, {
                      default: _withCtx(() => [...(_cache[26] || (_cache[26] = [
                        _createTextVNode(" 没有匹配的记录，换个关键词试试。 ", -1)
                      ]))]),
                      _: 1
                    }))
                  : (view.value === 'history')
                    ? (_openBlock(), _createElementBlock("div", _hoisted_48, " 还没有订阅历史 —— 在「待订阅清单」里勾选曲目点「订阅」，成功的条目会留档在这里。 "))
                    : (_openBlock(), _createElementBlock("div", _hoisted_49, " 清单是空的 —— 先跑一次歌单同步，媒体库里搜不到的曲目会出现在这里。 "))
          ], 64))
    ]),
    (rows.value.length)
      ? (_openBlock(), _createElementBlock("div", _hoisted_50, [
          _createVNode(_component_v_select, {
            modelValue: pageSize.value,
            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((pageSize).value = $event)),
            items: [20, 50, 100],
            density: "compact",
            variant: "outlined",
            "hide-details": "",
            label: "每页",
            class: "ms-pager__size"
          }, null, 8, ["modelValue"]),
          _createElementVNode("span", _hoisted_51, "第 " + _toDisplayString(page.value) + " / " + _toDisplayString(Math.max(1, pageCount.value)) + " 页 · 共 " + _toDisplayString(rows.value.length) + " 条", 1),
          _createVNode(_component_v_btn, {
            size: "small",
            variant: "text",
            disabled: page.value <= 1,
            onClick: _cache[11] || (_cache[11] = $event => (page.value = page.value - 1))
          }, {
            default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
              _createTextVNode("上一页", -1)
            ]))]),
            _: 1
          }, 8, ["disabled"]),
          _createVNode(_component_v_btn, {
            size: "small",
            variant: "text",
            disabled: page.value >= pageCount.value,
            onClick: _cache[12] || (_cache[12] = $event => (page.value = page.value + 1))
          }, {
            default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
              _createTextVNode("下一页", -1)
            ]))]),
            _: 1
          }, 8, ["disabled"])
        ]))
      : _createCommentVNode("", true),
    (view.value === 'pending')
      ? (_openBlock(), _createElementBlock("footer", _hoisted_52, [
          _createElementVNode("span", _hoisted_53, "已勾选 " + _toDisplayString(pickedCount.value) + " 条（歌曲 " + _toDisplayString(countByTarget.value.song) + " / 专辑 " + _toDisplayString(countByTarget.value.album) + "）", 1),
          _createVNode(_component_v_spacer),
          _createVNode(_component_v_menu, { location: "top" }, {
            activator: _withCtx(({ props: menuProps }) => [
              _createVNode(_component_v_btn, _mergeProps({
                variant: "text",
                "prepend-icon": "mdi-broom"
              }, menuProps), {
                default: _withCtx(() => [...(_cache[29] || (_cache[29] = [
                  _createTextVNode("清理", -1)
                ]))]),
                _: 1
              }, 16)
            ]),
            default: _withCtx(() => [
              _createVNode(_component_v_list, { density: "compact" }, {
                default: _withCtx(() => [
                  _createVNode(_component_v_list_item, {
                    title: "清理订阅失败记录",
                    onClick: _cache[13] || (_cache[13] = $event => (clearPending('failed')))
                  }),
                  _createVNode(_component_v_list_item, {
                    title: "清空整个清单",
                    onClick: _cache[14] || (_cache[14] = $event => (clearPending('all')))
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_v_btn, {
            variant: "tonal",
            color: "warning",
            "prepend-icon": "mdi-delete-outline",
            disabled: !pickedCount.value,
            loading: removing.value,
            onClick: removePicked
          }, {
            default: _withCtx(() => [...(_cache[30] || (_cache[30] = [
              _createTextVNode("移除", -1)
            ]))]),
            _: 1
          }, 8, ["disabled", "loading"]),
          _createVNode(_component_v_btn, {
            color: "primary",
            variant: "flat",
            "prepend-icon": "mdi-bell-plus-outline",
            disabled: !pickedCount.value,
            loading: subscribing.value,
            onClick: subscribePicked
          }, {
            default: _withCtx(() => [...(_cache[31] || (_cache[31] = [
              _createTextVNode("订阅", -1)
            ]))]),
            _: 1
          }, 8, ["disabled", "loading"])
        ]))
      : (_openBlock(), _createElementBlock("footer", _hoisted_54, [
          _createElementVNode("span", _hoisted_55, "共 " + _toDisplayString(historySummary.total) + " 条订阅历史（歌曲 " + _toDisplayString(historySummary.song) + " / 专辑 " + _toDisplayString(historySummary.album) + "），清理历史不会影响宿主的订阅列表", 1),
          _createVNode(_component_v_spacer),
          _createVNode(_component_v_btn, {
            variant: "tonal",
            color: "warning",
            "prepend-icon": "mdi-broom",
            disabled: !historySummary.total,
            loading: clearingHistory.value,
            onClick: clearHistory
          }, {
            default: _withCtx(() => [...(_cache[32] || (_cache[32] = [
              _createTextVNode("清空历史", -1)
            ]))]),
            _: 1
          }, 8, ["disabled", "loading"])
        ]))
  ]))
}
}

};
const PageComponent = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-f39a421b"]]);

export { PageComponent as default };
