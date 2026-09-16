# 歌单同步工具（MoviePilot V3）

## 上游引用

| 项 | 内容 |
| --- | --- |
| 原始上游 | https://github.com/baozaodetudou/MoviePilot-Plugins（作者：逗猫） |
| 上游基线 | v7.2（V2 实现，即本仓库 `plugins.v2/syncmusiclist` 的来源） |
| 本仓库演化 | 上游 v7.2 → 本地 V2 7.2（网易云登录增强）→ 本地 V3 8.0.0（改用本地 ncm-api） |
| 引入时间 | 2026-09 重建本仓库时确认 |

> V3 版本为本仓库自有适配实现：网易云登录与取数改走本地部署的 `moefurina/ncm-api`，
> 与上游 V2 实现的直连方式不同，详见下文。

---

把 QQ 音乐 / 网易云音乐的歌单同步到 Plex、Emby 的音乐库播放列表。

V3 版本与旧版最大的区别：**网易云的登录与取数不再由插件自己直连网易官方接口**，
而是统一交给本地部署的 [`moefurina/ncm-api`](https://hub.docker.com/r/moefurina/ncm-api) 容器。
插件因此去掉了内置的 1.3MB `NeteaseCloudMusicApi.js` 和 `py_mini_racer`（V8 引擎）两个依赖，
加密、风控、解灰适配由 ncm-api 维护。

## 1. 部署 ncm-api

插件本身不包含 ncm-api，需要单独起一个容器。
**ncm-api 的默认容器端口 3000 与 MoviePilot 冲突，宿主机端口统一映射为 1630**，
插件默认地址也按此填写。三种常见部署方式，配置页里填对应地址即可。

### 方式一：与 MoviePilot 同一个 docker-compose（推荐）

```yaml
services:
  moviepilot:
    image: jxxghp/moviepilot-v2:latest
    # ... 已有配置 ...
    networks:
      - moviepilot

  ncm-api:
    image: moefurina/ncm-api:latest
    container_name: ncm-api
    restart: unless-stopped
    ports:
      - "1630:3000"
    networks:
      - moviepilot

networks:
  moviepilot:
```

同一网络下用容器名互访，插件里填 `http://ncm-api:1630`（容器内仍是 3000，映射后宿主机是 1630，
插件与 ncm-api 同网络时填 `http://ncm-api:3000` 也可以，走的是容器内部端口）。

### 方式二：ncm-api 跑在宿主机

```bash
docker run -d --name ncm-api -p 1630:3000 --restart unless-stopped moefurina/ncm-api:latest
```

MoviePilot 在容器里，访问宿主机端口用 `http://host.docker.internal:1630`
（Linux 下需要给 MoviePilot 容器加 `--add-host=host.docker.internal:host-gateway`）。

### 方式三：ncm-api 在局域网另一台机器

填 `http://192.168.x.x:1630`。

> 部署完可以先在浏览器打开 `http://<地址>/inner/version`，
> 能返回 JSON 就说明服务正常；插件的配置页也有「测试连接」按钮做同样的探测。

## 2. 配置项

### ncm-api 服务地址

插件默认值 `http://192.168.1.100:1630` **只是占位**，必须改成你实际的地址，否则网易云相关功能不可用。
地址可以省略 `http://` 前缀，插件会自动补，末尾多余的 `/` 也会去掉。
填完可以点旁边的「测试连接」按钮，不用保存配置就能验证地址是否可用。

### 防风控（realIP / 随机中国 IP）

ncm-api 部署在国外服务器或部分国内云主机上时，网易会返回 `460 cheating` 异常。
两种解法（二选一）：

- **realIP**：填一个国内 IP（如 `116.25.146.177`），插件会把它作为 `realIP` 参数传给 ncm-api；
- **随机中国 IP**：打开开关，ncm-api 每次请求自动使用随机中国 IP（需要 ncm-api 镜像支持）。

另外插件内置了两项防风控措施：所有请求自动带时间戳参数避开 ncm-api 的 2 分钟缓存，
相邻请求之间强制 0.3~0.8 秒随机间隔，避免触发网易 IP 高频限制。

### 网易云登录方式

四种方式，**配置页里选哪种，就只显示哪种的栏位和按钮**：

| 方式 | 说明 |
| --- | --- |
| **扫码登录（推荐）** | 点「获取二维码」二维码直接显示在配置页 → 用网易云音乐 App 扫码 → 点「检查扫码结果」完成登录。最稳，不受密码风控影响 |
| 短信验证码 | 填手机号 → 点「发送验证码」→ 填验证码 → 点「验证码登录」 |
| 手机号 / 邮箱 + 密码 | 网易网易云盾对密码登录风控最严，容易返回 `502` 或触发验证，仅在扫码/验证码都不可用时使用 |
| 手动粘贴 Cookie | 自己在浏览器登录网易云，复制包含 `MUSIC_U` 的完整 Cookie 填进来 → 点「校验并保存 Cookie」 |

所有按钮都是即时生效（不用先保存配置），登录成功后 Cookie 立即落盘到插件数据目录（`cookie_storage`）。
**不要频繁调登录接口**——登录状态还在时插件不会重复登录。

### Cookie 保活

默认开启：每天 9 点自动检查一次登录状态并尝试刷新（调用 `/login/refresh` 续期 Cookie）。
注意 ncm-api 的刷新接口**不支持二维码登录得到的 Cookie**，扫码账号只做状态确认；
Cookie 失效时，密码登录方式会用保存的账号密码自动重登，其他方式会在日志里提示重新登录。

### 歌单同步配置

每行一条，格式为 `歌单id:播放列表名称`，冒号是英文冒号。

```text
# 网易云歌单
365436873:我的歌单
# 带 Emby 多用户（第三个字段）
365436873:我的歌单:emby用户名
365436873:我的歌单:emby1,emby2
```

QQ 音乐歌单同理，填在「QQ音乐歌单同步」里。

> QQ 音乐歌单 id 取自歌单链接 `https://y.qq.com/n/ryqq/playlist/歌单id`；
> 网易云歌单 id 取自 `https://music.163.com/#/playlist?id=歌单id`。

### 其他

- **精准匹配**：开启后要求歌手也匹配，避免翻唱误入库。歌单里有冷门版本时可以先关掉排查。
- **每日推荐**：勾选后会把网易云「每日推荐歌单 / 每日推荐歌曲」也同步过来。
- **立即运行一次**：保存配置后立刻跑一次同步，方便验证。

## 3. 使用前提

1. 本地已部署并可访问 ncm-api，且网易云已登录。
2. Plex / Emby 中已存在**音乐类型**的媒体库。
3. 目标播放列表建议提前手动创建并放入至少一首歌（Plex 会自动创建，Emby 需要已有）。
4. Plex 使用最高码率版本入库；同一首歌在库里有多个版本时会自动取码率最高的那条。

## 4. 升级说明（v2 → v3）

| 项目 | v2 | v3 |
| --- | --- | --- |
| 目录 | `plugins.v2/syncmusiclist/` | `plugins.v3/syncmusiclist/` |
| 索引 | `package.v2.json` | `package.v3.json` |
| 宿主接口 | `app.core` / `app.helper` | `app.sdk` |
| 网易云链路 | 内置 JS + py_mini_racer 直连网易 | 本地 ncm-api HTTP |
| 额外依赖 | `py_mini_racer`、`requests` | 无（全部走宿主已提供的依赖） |
| Plex 检索 | 手工拼 `/hubs/search` | 媒体库级 `searchTracks()`（与宿主 `Plex.get_music()` 同链路） |
| 版本 | 7.2 | 8.0.0 |

版本按代际跃迁规则从 `7.2` 跳到 `8.0.0`，配置项与 v2 保持兼容，
已配置的网易云账号密码、歌单同步列表升级后可直接沿用。

## 5. 故障排查

| 现象 | 排查方向 |
| --- | --- |
| 保存配置报「服务地址不可达」 | 核对地址与端口；MoviePilot 容器内 `curl http://<地址>/inner/version` 是否通 |
| 提示 `460 cheating` | ncm-api 出口 IP 被网易限制，填 realIP（国内 IP）或开启随机中国 IP |
| 提示 `502` | 多出现在密码登录，换扫码或 Cookie 登录 |
| 歌单拉取返回 403 / 空 | 网易云 Cookie 失效，重新扫码；ncm-api 需要更新到最新镜像 |
| Plex 搜不到歌曲 | 确认媒体库类型是「音乐」；歌名或歌手在库里不一致时先关掉精准匹配试一次 |
| 播放列表没变化 | 查看插件日志中「已存在歌曲」数量，确认不是已经同步过 |
