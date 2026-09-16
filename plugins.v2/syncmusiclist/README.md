# 歌单同步工具（MoviePilot V2）

## 上游引用

| 项 | 内容 |
| --- | --- |
| 上游仓库 | https://github.com/baozaodetudou/MoviePilot-Plugins |
| 原作者 | 逗猫 |
| 基线版本 | v7.2（上游 `plugins.v2/syncmusiclist`） |
| 引入时间 | 2026-09 重建本仓库时确认 |

## 本地改动（相对上游 v7.2）

- `cloudmusic.py`：网易云登录链路增强
  - 新增验证码发送（`/captcha/sent`）与验证码校验（`/captcha/verify`）
  - 支持手机号验证码登录与密码/邮箱登录，登录成功/失败均输出明确日志
  - 登录相关接口统一异常捕获，避免异常直接冒泡中断同步流程
- 移除与猫眼相关插件（MaoyanRank）同仓库带来的无关文件；本目录仅保留歌单同步工具本体

## 使用说明

- 功能说明与食用指南见仓库根目录 `document/playlist.md`（同样源自上游文档）。
- V3 环境（MoviePilot >= 3.0.0）请安装 `plugins.v3/syncmusiclist`（v8.x，基于本地 ncm-api），本 V2 目录仅服务 V2 宿主。
