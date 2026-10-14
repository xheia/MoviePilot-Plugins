import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper-pcqpp-6-.js';

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,normalizeClass:_normalizeClass,toDisplayString:_toDisplayString,withKeys:_withKeys,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment} = await importShared('vue');


const _hoisted_1 = { class: "ms-page" };
const _hoisted_2 = { class: "ms-head" };
const _hoisted_3 = { class: "ms-head__brand" };
const _hoisted_4 = { class: "ms-head__logo" };
const _hoisted_5 = { class: "ms-head__crumbs" };
const _hoisted_6 = { class: "ms-head__actions" };
const _hoisted_7 = { class: "ms-tabs" };
const _hoisted_8 = {
  key: 2,
  class: "ms-body"
};
const _hoisted_9 = { class: "ms-search" };
const _hoisted_10 = {
  key: 0,
  class: "ms-hint-inline"
};
const _hoisted_11 = {
  key: 1,
  class: "ms-table-wrap"
};
const _hoisted_12 = { class: "ms-table" };
const _hoisted_13 = { class: "ms-src" };
const _hoisted_14 = { class: "ms-title" };
const _hoisted_15 = { class: "col-dur" };
const _hoisted_16 = { class: "col-link" };
const _hoisted_17 = ["href"];
const _hoisted_18 = {
  key: 1,
  class: "ms-link-off"
};
const _hoisted_19 = { class: "col-act" };
const _hoisted_20 = {
  key: 2,
  class: "ms-empty"
};
const _hoisted_21 = {
  key: 3,
  class: "ms-empty"
};
const _hoisted_22 = {
  key: 3,
  class: "ms-body"
};
const _hoisted_23 = { class: "ms-smart" };
const _hoisted_24 = {
  key: 0,
  class: "ms-table-wrap"
};
const _hoisted_25 = { class: "ms-table" };
const _hoisted_26 = { class: "col-score" };
const _hoisted_27 = { class: "ms-score-num" };
const _hoisted_28 = { class: "ms-src" };
const _hoisted_29 = { class: "ms-title" };
const _hoisted_30 = { class: "col-link" };
const _hoisted_31 = ["href"];
const _hoisted_32 = {
  key: 1,
  class: "ms-link-off"
};
const _hoisted_33 = { class: "col-act" };
const _hoisted_34 = {
  key: 1,
  class: "ms-empty"
};
const _hoisted_35 = {
  key: 2,
  class: "ms-empty"
};

const {computed,onMounted,reactive,ref} = await importShared('vue');


const PLUGIN = 'plugin/MusicSubscribe';

const _sfc_main = {
  __name: 'Search',
  props: {
  api: { type: Object, default: () => ({}) },
  show_switch: { type: Boolean, default: true },
},
  emits: ['switch', 'close', 'action'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;

const PLATFORM_LABELS = {
  netease: '网易云', qq: 'QQ音乐', spotify: 'Spotify',
  kugou: '酷狗', kuwo: '酷我', migu: '咪咕',
};

const view = ref('search');
const keyword = ref('');
const selPlatforms = ref([]);
const searchResults = ref([]);
const searching = ref(false);
const searched = ref(false);
const searchEnabled = ref(false);
const downloading = ref(null);
const platforms = ref([]);

const seedTitle = ref('');
const seedArtist = ref('');
const seedKeyword = ref('');
const seedSize = ref(20);
const smartRows = ref([]);
const generating = ref(false);
const generated = ref(false);

const error = ref('');
const result = ref('');
const resultLevel = ref('success');

const availablePlatforms = computed(() =>
  platforms.value.filter(p => p.available).map(p => ({ title: p.label, value: p.name })));

function platformLabel(name) {
  return PLATFORM_LABELS[name] || name || '未知'
}

function linkEntries(links) {
  const got = links || {};
  return [
    { key: 'song', label: '歌曲', url: got.song || '' },
    { key: 'album', label: '专辑', url: got.album || '' },
    { key: 'artist', label: '歌手', url: got.artist || '' },
  ]
}

function call(method, path, data) {
  const fn = props?.api?.[method];
  if (typeof fn !== 'function') throw new Error('API 不可用')
  return data === undefined ? fn(path) : fn(path, data)
}

async function loadPlatforms() {
  try {
    const res = await call('get', `${PLUGIN}/platforms`);
    platforms.value = Array.isArray(res?.platforms) ? res.platforms : [];
    searchEnabled.value = !!res?.search_enabled;
    if (selPlatforms.value.length === 0) {
      selPlatforms.value = platforms.value.filter(p => p.available).map(p => p.name);
    }
  } catch (e) {
    error.value = '加载平台列表失败：' + (e?.message || e);
  }
}

async function doSearch() {
  if (!keyword.value.trim()) {
    result.value = '请先输入搜索关键词';
    resultLevel.value = 'warning';
    return
  }
  searching.value = true;
  error.value = '';
  result.value = '';
  try {
    const params = `keyword=${encodeURIComponent(keyword.value.trim())}`
      + `&limit=20`
      + (selPlatforms.value.length ? `&platforms=${encodeURIComponent(selPlatforms.value.join(','))}` : '');
    const res = await call('get', `${PLUGIN}/search?${params}`);
    if (res?.code === 0) {
      searchResults.value = Array.isArray(res.results) ? res.results : [];
      searched.value = true;
      const errCount = Object.keys(res.errors || {}).length;
      resultLevel.value = searchResults.value.length ? 'success' : 'info';
      result.value = `搜索到 ${searchResults.value.length} 条${errCount ? `（${errCount} 个平台出错）` : ''}`;
    } else {
      resultLevel.value = 'error';
      result.value = res?.message || '搜索失败';
    }
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '搜索失败：' + (e?.message || e);
  } finally {
    searching.value = false;
    emit('action');
  }
}

async function doDownload(row, idx) {
  downloading.value = idx;
  result.value = '';
  try {
    const res = await call('post', `${PLUGIN}/download`, {
      platform: row.platform, source_id: row.source_id, album_id: row.album_id,
      title: row.title, artist: row.artist, album: row.album,
    });
    resultLevel.value = res?.code === 0 ? 'success' : 'error';
    result.value = res?.message || (res?.code === 0 ? '已处理' : '下载失败');
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '下载失败：' + (e?.message || e);
  } finally {
    downloading.value = null;
  }
}

async function doSmartlist() {
  if (!seedTitle.value.trim()) {
    result.value = '请先填写种子歌名';
    resultLevel.value = 'warning';
    return
  }
  generating.value = true;
  error.value = '';
  result.value = '';
  try {
    const params = `title=${encodeURIComponent(seedTitle.value.trim())}`
      + `&artist=${encodeURIComponent(seedArtist.value.trim())}`
      + `&size=${Number(seedSize.value) || 20}`
      + (seedKeyword.value.trim() ? `&keyword=${encodeURIComponent(seedKeyword.value.trim())}` : '');
    const res = await call('get', `${PLUGIN}/smartlist?${params}`);
    if (res?.code === 0) {
      smartRows.value = Array.isArray(res.playlist) ? res.playlist : [];
      generated.value = true;
      resultLevel.value = smartRows.value.length ? 'success' : 'info';
      result.value = `生成 ${smartRows.value.length} 首（候选池 ${res.pool_size || 0} 首）`;
    } else {
      resultLevel.value = 'error';
      result.value = res?.message || '生成失败';
    }
  } catch (e) {
    resultLevel.value = 'error';
    result.value = '生成失败：' + (e?.message || e);
  } finally {
    generating.value = false;
    emit('action');
  }
}

onMounted(loadPlatforms);

return (_ctx, _cache) => {
  const _component_v_icon = _resolveComponent("v-icon");
  const _component_v_btn = _resolveComponent("v-btn");
  const _component_v_alert = _resolveComponent("v-alert");
  const _component_v_text_field = _resolveComponent("v-text-field");
  const _component_v_select = _resolveComponent("v-select");
  const _component_v_progress_linear = _resolveComponent("v-progress-linear");

  return (_openBlock(), _createElementBlock("section", _hoisted_1, [
    _createElementVNode("header", _hoisted_2, [
      _createElementVNode("div", _hoisted_3, [
        _createElementVNode("div", _hoisted_4, [
          _createVNode(_component_v_icon, {
            icon: "mdi-magnify",
            size: "20"
          })
        ]),
        _createElementVNode("div", null, [
          _createElementVNode("div", _hoisted_5, [
            _cache[11] || (_cache[11] = _createElementVNode("span", null, "MoviePilot", -1)),
            _createVNode(_component_v_icon, {
              icon: "mdi-chevron-right",
              size: "13"
            }),
            _cache[12] || (_cache[12] = _createElementVNode("span", null, "插件", -1))
          ]),
          _cache[13] || (_cache[13] = _createElementVNode("h1", { class: "ms-head__title" }, "搜索 / 下载 / 智能歌单", -1))
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
              default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                _createTextVNode("同步配置", -1)
              ]))]),
              _: 1
            }))
          : _createCommentVNode("", true),
        _createVNode(_component_v_btn, {
          icon: "mdi-refresh",
          size: "small",
          variant: "text",
          loading: searching.value,
          "aria-label": "刷新",
          onClick: _cache[1] || (_cache[1] = $event => (loadPlatforms()))
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
        class: _normalizeClass(['ms-tab', { 'ms-tab--active': view.value === 'search' }]),
        onClick: _cache[3] || (_cache[3] = $event => (view.value = 'search'))
      }, "跨平台搜索", 2),
      _createElementVNode("button", {
        type: "button",
        class: _normalizeClass(['ms-tab', { 'ms-tab--active': view.value === 'smartlist' }]),
        onClick: _cache[4] || (_cache[4] = $event => {loadPlatforms(); view.value = 'smartlist';})
      }, "智能歌单", 2)
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
    (view.value === 'search')
      ? (_openBlock(), _createElementBlock("div", _hoisted_8, [
          _createElementVNode("div", _hoisted_9, [
            _createVNode(_component_v_text_field, {
              modelValue: keyword.value,
              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((keyword).value = $event)),
              class: "ms-search__kw",
              density: "compact",
              variant: "outlined",
              label: "关键词（歌名 / 歌手 / 专辑）",
              "prepend-inner-icon": "mdi-magnify",
              "hide-details": "",
              "single-line": "",
              onKeyup: _withKeys(doSearch, ["enter"])
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_select, {
              modelValue: selPlatforms.value,
              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((selPlatforms).value = $event)),
              items: availablePlatforms.value,
              class: "ms-search__pf",
              density: "compact",
              variant: "outlined",
              label: "平台",
              "hide-details": "",
              multiple: "",
              chips: "",
              "closable-chips": ""
            }, null, 8, ["modelValue", "items"]),
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "flat",
              "prepend-icon": "mdi-magnify",
              loading: searching.value,
              onClick: doSearch
            }, {
              default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                _createTextVNode("搜索", -1)
              ]))]),
              _: 1
            }, 8, ["loading"])
          ]),
          (!searchEnabled.value)
            ? (_openBlock(), _createElementBlock("p", _hoisted_10, "搜索功能未开启（请在「搜索与下载」配置页打开开关）。"))
            : _createCommentVNode("", true),
          (searchResults.value.length)
            ? (_openBlock(), _createElementBlock("div", _hoisted_11, [
                _createElementVNode("table", _hoisted_12, [
                  _cache[17] || (_cache[17] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", null, "平台"),
                      _createElementVNode("th", null, "歌曲名称"),
                      _createElementVNode("th", null, "歌手"),
                      _createElementVNode("th", null, "专辑"),
                      _createElementVNode("th", { class: "col-dur" }, "时长"),
                      _createElementVNode("th", { class: "col-link" }, "来源链接"),
                      _createElementVNode("th", { class: "col-act" }, "下载")
                    ])
                  ], -1)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(searchResults.value, (row, i) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: `${row.platform}-${row.source_id}-${i}`
                      }, [
                        _createElementVNode("td", null, [
                          _createElementVNode("span", _hoisted_13, _toDisplayString(platformLabel(row.platform)), 1)
                        ]),
                        _createElementVNode("td", null, [
                          _createElementVNode("div", _hoisted_14, _toDisplayString(row.title), 1)
                        ]),
                        _createElementVNode("td", null, _toDisplayString(row.artist || '-'), 1),
                        _createElementVNode("td", null, _toDisplayString(row.album || '-'), 1),
                        _createElementVNode("td", _hoisted_15, _toDisplayString(row.duration_text || '-'), 1),
                        _createElementVNode("td", _hoisted_16, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(linkEntries(row.links), (l) => {
                            return (_openBlock(), _createElementBlock("span", {
                              key: l.key
                            }, [
                              (l.url)
                                ? (_openBlock(), _createElementBlock("a", {
                                    key: 0,
                                    href: l.url,
                                    target: "_blank",
                                    rel: "noopener"
                                  }, _toDisplayString(l.label), 9, _hoisted_17))
                                : (_openBlock(), _createElementBlock("span", _hoisted_18, _toDisplayString(l.label), 1))
                            ]))
                          }), 128))
                        ]),
                        _createElementVNode("td", _hoisted_19, [
                          _createVNode(_component_v_btn, {
                            size: "x-small",
                            variant: "tonal",
                            loading: downloading.value === i,
                            onClick: $event => (doDownload(row, i))
                          }, {
                            default: _withCtx(() => [...(_cache[16] || (_cache[16] = [
                              _createTextVNode("下载", -1)
                            ]))]),
                            _: 1
                          }, 8, ["loading", "onClick"])
                        ])
                      ]))
                    }), 128))
                  ])
                ])
              ]))
            : (searched.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_20, "没有搜到结果，换个关键词或平台试试。"))
              : (_openBlock(), _createElementBlock("div", _hoisted_21, "输入关键词开始跨平台搜索。"))
        ]))
      : (_openBlock(), _createElementBlock("div", _hoisted_22, [
          _createElementVNode("div", _hoisted_23, [
            _createVNode(_component_v_text_field, {
              modelValue: seedTitle.value,
              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((seedTitle).value = $event)),
              class: "ms-smart__title",
              density: "compact",
              variant: "outlined",
              label: "种子：歌名（必填）",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_text_field, {
              modelValue: seedArtist.value,
              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((seedArtist).value = $event)),
              class: "ms-smart__artist",
              density: "compact",
              variant: "outlined",
              label: "种子：歌手（可选）",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_text_field, {
              modelValue: seedKeyword.value,
              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((seedKeyword).value = $event)),
              class: "ms-smart__kw",
              density: "compact",
              variant: "outlined",
              label: "候选池关键词（可选，默认按种子歌手）",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_text_field, {
              modelValue: seedSize.value,
              "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((seedSize).value = $event)),
              modelModifiers: { number: true },
              type: "number",
              class: "ms-smart__size",
              density: "compact",
              variant: "outlined",
              label: "歌单长度",
              "hide-details": ""
            }, null, 8, ["modelValue"]),
            _createVNode(_component_v_btn, {
              color: "primary",
              variant: "flat",
              "prepend-icon": "mdi-auto-fix",
              loading: generating.value,
              onClick: doSmartlist
            }, {
              default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
                _createTextVNode("生成歌单", -1)
              ]))]),
              _: 1
            }, 8, ["loading"])
          ]),
          _cache[21] || (_cache[21] = _createElementVNode("p", { class: "ms-hint-inline" }, "算法：以种子曲目为基调，按「同歌手 / 同专辑 / 标题 · 专辑 token 重合」打相似度， 并限制同一歌手最多保留 3 首以保证多样性。候选来自本地已采集曲目 + 跨平台搜索。", -1)),
          (smartRows.value.length)
            ? (_openBlock(), _createElementBlock("div", _hoisted_24, [
                _createElementVNode("table", _hoisted_25, [
                  _cache[20] || (_cache[20] = _createElementVNode("thead", null, [
                    _createElementVNode("tr", null, [
                      _createElementVNode("th", { class: "col-score" }, "相似度"),
                      _createElementVNode("th", null, "平台"),
                      _createElementVNode("th", null, "歌曲名称"),
                      _createElementVNode("th", null, "歌手"),
                      _createElementVNode("th", null, "专辑"),
                      _createElementVNode("th", { class: "col-link" }, "来源链接"),
                      _createElementVNode("th", { class: "col-act" }, "下载")
                    ])
                  ], -1)),
                  _createElementVNode("tbody", null, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(smartRows.value, (row, i) => {
                      return (_openBlock(), _createElementBlock("tr", {
                        key: `smart-${row.platform}-${row.source_id}-${i}`
                      }, [
                        _createElementVNode("td", _hoisted_26, [
                          _createVNode(_component_v_progress_linear, {
                            "model-value": row.score * 100,
                            color: "primary",
                            height: "6",
                            rounded: ""
                          }, null, 8, ["model-value"]),
                          _createElementVNode("span", _hoisted_27, _toDisplayString(row.score.toFixed(2)), 1)
                        ]),
                        _createElementVNode("td", null, [
                          _createElementVNode("span", _hoisted_28, _toDisplayString(row.platform_label), 1)
                        ]),
                        _createElementVNode("td", null, [
                          _createElementVNode("div", _hoisted_29, _toDisplayString(row.title), 1)
                        ]),
                        _createElementVNode("td", null, _toDisplayString(row.artist || '-'), 1),
                        _createElementVNode("td", null, _toDisplayString(row.album || '-'), 1),
                        _createElementVNode("td", _hoisted_30, [
                          (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(linkEntries(row.links), (l) => {
                            return (_openBlock(), _createElementBlock("span", {
                              key: l.key
                            }, [
                              (l.url)
                                ? (_openBlock(), _createElementBlock("a", {
                                    key: 0,
                                    href: l.url,
                                    target: "_blank",
                                    rel: "noopener"
                                  }, _toDisplayString(l.label), 9, _hoisted_31))
                                : (_openBlock(), _createElementBlock("span", _hoisted_32, _toDisplayString(l.label), 1))
                            ]))
                          }), 128))
                        ]),
                        _createElementVNode("td", _hoisted_33, [
                          _createVNode(_component_v_btn, {
                            size: "x-small",
                            variant: "tonal",
                            loading: downloading.value === `s${i}`,
                            onClick: $event => (doDownload(row, `s${i}`))
                          }, {
                            default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                              _createTextVNode("下载", -1)
                            ]))]),
                            _: 1
                          }, 8, ["loading", "onClick"])
                        ])
                      ]))
                    }), 128))
                  ])
                ])
              ]))
            : (generated.value)
              ? (_openBlock(), _createElementBlock("div", _hoisted_34, "没有生成候选，换个种子或关键词试试。"))
              : (_openBlock(), _createElementBlock("div", _hoisted_35, "填写种子歌名后点「生成歌单」。"))
        ]))
  ]))
}
}

};
const SearchComponent = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-efb4c1d3"]]);

export { SearchComponent as default };
