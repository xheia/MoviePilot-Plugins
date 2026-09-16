# 歌单同步工具（MoviePilot V3）

把 QQ 音乐 / 网易云音乐的歌单同步到 Plex、Emby 的音乐库播放列表。

V3 版本与旧版最大的区别：**网易云的登录与取数不再由插件自己直连网易官方接口**，
而是统一交给本地部署的 [`moefurina/ncm-api`](https://hub.docker.com/r/moefurina/ncm-api) 容器。
插件因此去掉了内置的 1.3MB `NeteaseCloudMusicApi.js` 和 `py_mini_racer`（V8 引擎）两个依赖，
加密、风控、解灰适配由 ncm-api 维护。

## 1. 部署 ncm-api

插件本身不包含 ncm-api，需要单独起一个容器。三种常见部署方式，配置页里填对应地址即可。

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
      - "3000:3000"
    networks:
      - moviepilot

networks:
  moviepilot:
```

同一网络下用容器名互访，插件里填 `http://ncm-api:3000`。

### 方式二：ncm-api 跑在宿主机

```bash
docker run -d --name ncm-api -p 3000:3000 --restart unless-stopped moefurina/ncm-api:latest
```

MoviePilot 在容器里，访问宿主机端口用 `http://host.docker.internal:3000`
（Linux 下需要给 MoviePilot 容器加 `--add-host=host.docker.internal:host-gateway`）。

### 方式三：ncm-api 在局域网另一台机器

填 `http://192.168.x.x:3000`。

> 部署完可以先在浏览器打开 `http://<地址>/inner/version`，
> 能返回 JSON 就说明服务正常；插件的配置页也有「测试连接」按钮做同样的探测。

## 2. 配置项

### ncm-api 服务地址

插件默认值 `http://192.168.1.100:3000` **只是占位**，必须改成你实际的地址，否则网易云相关功能不可用。
地址可以省略 `http://` 前缀，插件会自动补，末尾多余的 `/` 也会去掉。

### 网易云登录方式

四种方式，配置页里选一种：

| 方式 | 说明 |
| --- | --- |
| **扫码登录（推荐）** | 点「获取二维码」→ 用网易云音乐 App 扫码 → 点「检查扫码结果」完成登录。最稳，不受密码风控影响 |
| 短信验证码 | 填手机号 → 点「发送验证码」→ 填验证码 → 点「登录」。注意验证码 5 分钟内有效 |
| 手机号 / 邮箱 + 密码 | 沿用旧版配置项，但网易对密码登录风控较严，容易返回 `502` |
| 手动粘贴 Cookie | 自己在浏览器登录网易云，复制包含 `MUSIC_U` 的完整 Cookie 填进来。最省事，但要手动续期 |

登录成功后 Cookie 会缓存在插件数据目录（`cookie_storage`），失效时按所选方式自动续登。

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
| 提示 `502` | 多出现在密码登录，换扫码或 Cookie 登录 |
| 歌单拉取返回 403 / 空 | 网易云 Cookie 失效，重新扫码；ncm-api 需要更新到最新镜像 |
| Plex 搜不到歌曲 | 确认媒体库类型是「音乐」；歌名或歌手在库里不一致时先关掉精准匹配试一次 |
| 播放列表没变化 | 查看插件日志中「已存在歌曲」数量，确认不是已经同步过 |
