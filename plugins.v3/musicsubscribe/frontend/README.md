# 歌单订阅 · 前端（Vue 联邦组件）

`plugins.v3/musicsubscribe/frontend`，产出 `dist/assets/remoteEntry.js`，宿主以联邦方式加载
`./Config`（配置页）与 `./Page`（数据页）。

## 目录

```
frontend/
├── index.html          # 本地开发壳入口（不参与联邦产物）
├── vite.config.js      # federation 配置：name=MusicSubscribe，exposes Config/Page
├── src/
│   ├── main.js         # 本地开发壳（自带 Vuetify 实例），宿主运行时不走这里
│   ├── App.vue         # 本地预览：浅/深色切换 + 窄中宽预览
│   ├── dev/mockApi.js  # 本地预览用的假接口
│   └── components/
│       ├── Config.vue  # 配置页：运行设置 / 网易云登录 / 歌单来源 / 上次同步
│       └── Page.vue    # 数据页：库内缺失曲目清单（勾选歌曲或专辑后一键订阅）
```

## 构建

```bash
npm install
npm run build      # 产出 dist/assets/remoteEntry.js 等联邦产物
npm run dev        # 本地预览（http://localhost:5101）
```

## 宿主注入

| prop           | 说明 |
| -------------- | ---- |
| `api`          | 已经绑定到 `plugin/MusicSubscribe/<path>` 的请求实例，`get/post` 直接返回插件响应对象 |
| `initialConfig`| 宿主已保存的配置（仅 Config 使用） |
| `show_switch`  | 数据页是否显示「同步配置」按钮（仅 Page 使用） |

事件：`save`（配置保存）、`switch`（跨页切换）、`close`、`layout`（建议宽度）、`action`（数据刷新完成）。

## 注意

- Vuetify 由宿主提供，`shared` 一律 `generate: false`；构建时会把产物里的 `.v-*` / `.mdi-*` 规则剥掉，
  避免覆盖宿主样式（`vite.config.js` 的 `vuetifyFilter`，仅 `vite build` 生效）。
- `build.target` 必须是 `esnext`，否则顶层 await 会失败。
