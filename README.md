# MoviePilot-Plugins（个人聚合插件库）

参考 [MoviePilot 官方插件市场](https://github.com/jxxghp/MoviePilot-Plugins) 的目录结构维护的个人插件仓库，
聚合多个上游插件，做 V3 适配与本地增强。插件开发与目录约定见 [食用说明](MP-README.md)。

## 插件市场添加

在 MoviePilot「插件 → 插件市场」中填入本仓库地址即可安装：

```
https://github.com/xheia/MoviePilot-Plugins
```

## 插件列表与上游引用

| 插件 | 目录 | 版本 | 上游来源 | 说明 |
| --- | --- | --- | --- | --- |
| 歌单同步工具 SyncMusicList | `plugins.v2/syncmusiclist` | 7.2 | [baozaodetudou/MoviePilot-Plugins](https://github.com/baozaodetudou/MoviePilot-Plugins)（逗猫）v7.2 | 同步 QQ/网易云歌单到 Plex/Emby；本地增强网易云登录，见 [插件 README](plugins.v2/syncmusiclist/README.md) |
| 歌单同步工具 SyncMusicList | `plugins.v3/syncmusiclist` | 8.1.1 | 同上（上游 v7.2 → 本地 V2 → 本地 V3） | V3 专用：网易云改走本地 [ncm-api](https://hub.docker.com/r/moefurina/ncm-api)，见 [插件 README](plugins.v3/syncmusiclist/README.md) |
| 自动订阅助手 AutomaticSubscriptionAssistant | `plugins.v3/automaticsubscriptionassistant` | 1.0.0 | [Aqr-K/MoviePilot-Plugins](https://github.com/Aqr-K/MoviePilot-Plugins) v0.2.13 | V3 专用重实现（SDK + 统一媒体身份），见 [插件 README](plugins.v3/automaticsubscriptionassistant/README.md) |

> 各插件目录内的 `README.md` 与 `package.v2.json` / `package.v3.json` 中的 `upstream` 字段
> 记录了上游仓库、基线版本与本地改动，供后续与上游同步时比对。

## 目录结构

- `plugins.v3/`：MoviePilot V3 专用插件（要求 MoviePilot >= 3.0.0）
- `package.v3.json`：插件市场的概要信息
- `icons/`：插件图标
