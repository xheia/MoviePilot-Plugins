"""下载编排（搜索结果 → 落盘 / 推送到下载客户端）。

真实下载的两条路径
----------------

1. **直链（direct）** —— 适配器能给出**平台允许直接访问**的音频地址时（当前是网易云，
   经本地 ncm-api 的 ``/song/url``），插件把文件保存到 ``download_path``，
   文件名按 ``{歌手}/{专辑}/{歌名}.{download_format}`` 组织；
2. **种子 / 磁力（torrent）** —— 来源平台给不出直链时，若配置了 **bitmagnet**（自建
   BT 索引器），插件会用「歌手 + 歌名」去你自己的实例里检索种子，再把磁力链接通过
   宿主的 ``DownloadChain`` 推送到 **qBittorrent** 或 **transmission**
   （由 ``download_client`` 选择，``auto`` 交给宿主按已配置客户端挑）。

不做什么（重要边界）
--------------------

- **不解密音频、不绕过付费 / 会员限制、不规避 DRM**。平台不给地址就是给不了：
  适配器返回 ``{"kind": "none", "reason": ...}`` 时直接把原因透传给用户，
  而不是假装能下或去破解；
- 平台只返回**试听片段**时同样按 ``none`` 处理，不拿片段冒充完整音频。

所以 UI 上「下载」按钮永远可用，但点了之后会清楚告诉你：下成了（含落盘路径）、
还是为什么下不了。付费内容请通过平台官方渠道（购买 / 会员 / 官方客户端离线下载）获取。

bitmagnet 这条回退路径只做「换一个公开可得的渠道」这件事——插件依旧不碰任何平台的
付费墙与 DRM。检索到什么取决于你自己实例索引到的资源，**插件不对结果做任何保真
或版权判断**，请自行确保你对下载内容拥有合法权利。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.sdk.logging import logger

from .bitmagnet import BitmagnetClient, BitmagnetError
from .platform import PlatformError, get_platform
from .track import Track


class Downloader:
    """把一条曲目按配置解析成下载动作并执行。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("download_enabled"))

    @property
    def download_path(self) -> str:
        return (self._config.get("download_path") or "").strip()

    @property
    def download_format(self) -> str:
        fmt = (self._config.get("download_format") or "flac").strip().lower()
        return fmt or "flac"

    @property
    def download_client(self) -> str:
        return (self._config.get("download_client") or "auto").strip().lower()

    @property
    def bitmagnet_enabled(self) -> bool:
        return bool(self._config.get("bitmagnet_enabled"))

    @property
    def bitmagnet_limit(self) -> int:
        try:
            return int(self._config.get("bitmagnet_limit") or 20)
        except (TypeError, ValueError):
            return 20

    def bitmagnet_client(self) -> BitmagnetClient:
        """按当前配置构造 bitmagnet 客户端（未配置时返回一个空客户端）。"""
        return BitmagnetClient(
            base_url=(self._config.get("bitmagnet_url") or "").strip(),
            api_key=(self._config.get("bitmagnet_api_key") or "").strip(),
        )

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def resolve(self, track: Track) -> Dict[str, Any]:
        """解析一条曲目的下载方式（不真正下载）。

        顺序：来源平台直链 → bitmagnet 种子回退 → 给不出就返回 none + 原因。
        """
        try:
            adapter = get_platform(track.platform, self._config)
            descriptor = adapter.download_descriptor(track)
        except PlatformError as error:
            return {"kind": "none", "reason": str(error)}
        descriptor = descriptor or {}
        kind = descriptor.get("kind", "none")
        if kind != "none":
            return {"kind": kind, **{k: v for k, v in descriptor.items() if k != "kind"}}
        # 平台拿不到直链时，退到自建 bitmagnet 检索种子
        fallback = self._resolve_bitmagnet(track, descriptor.get("reason") or "")
        if fallback:
            return fallback
        return {"kind": "none", "reason": descriptor.get("reason") or "该平台暂不支持下载"}

    def _resolve_bitmagnet(self, track: Track, reason: str = "") -> Optional[Dict[str, Any]]:
        """用 bitmagnet 给曲目找种子；没开或没命中返回 ``None``。"""
        if not self.bitmagnet_enabled:
            return None
        client = self.bitmagnet_client()
        if not client.configured:
            return None
        try:
            hit = client.best_match(track, prefer_format=self.download_format)
        except BitmagnetError as error:
            logger.warning(f"bitmagnet 检索失败[{track.title}]：{error}")
            return {"kind": "none", "reason": f"bitmagnet 检索失败：{error}"}
        except Exception as error:  # noqa: BLE001 - 索引器返回结构异常不应中断
            logger.warning(f"bitmagnet 检索异常[{track.title}]：{error}")
            return None
        if hit is None:
            return None
        size = f"{hit.size / 1048576:.1f}MB" if hit.size else "未知大小"
        return {
            "kind": "torrent",
            "url": hit.magnet,
            "title": hit.title,
            "seeders": hit.seeders,
            "leechers": hit.leechers,
            "size": hit.size,
            "score": hit.score,
            "source": "bitmagnet",
            "note": (f"{reason}；已改用 bitmagnet 检索到种子「{hit.title}」"
                     f"（{size}，做种 {hit.seeders}）"),
        }

    def download(self, track: Track, content: Optional[str] = None) -> Dict[str, Any]:
        """执行下载。

        :param track: 要下载的曲目（含 platform / source_id）。
        :param content: 可选，直接给一个 magnet / 直链，覆盖适配器解析结果。
        :return: ``{ok, kind, message, path?}``。
        """
        if not self.enabled:
            return {"ok": False, "kind": "none",
                    "message": "下载功能未开启（请在「搜索与下载」配置页打开开关）"}
        descriptor = self.resolve(track)
        if content:
            # 显式给了资源（如搜索结果里带 magnet），以它为准
            if content.startswith(("magnet:", "http://", "https://")) and content.endswith((".torrent",)):
                descriptor = {"kind": "torrent", "url": content}
            elif content.startswith("magnet:"):
                descriptor = {"kind": "torrent", "url": content}
            else:
                descriptor = {"kind": "direct", "url": content}

        kind = descriptor.get("kind")
        if kind == "none":
            return {"ok": False, "kind": "none",
                    "message": descriptor.get("reason") or "该平台暂不支持下载"}
        result: Dict[str, Any]
        if kind == "torrent":
            result = self._push_torrent(descriptor.get("url") or "", track=track)
        elif kind == "direct":
            result = self._save_direct(descriptor.get("url") or "", track=track)
        else:
            result = {"ok": False, "kind": "none", "message": "未知的下载类型"}
        # 走了 bitmagnet 回退时，把「为什么不是平台直链」的原因带回给前端
        if descriptor.get("source") == "bitmagnet":
            result["source"] = "bitmagnet"
            result["title"] = descriptor.get("title") or ""
            result["seeders"] = descriptor.get("seeders") or 0
            if result.get("ok"):
                result["message"] = descriptor.get("note") or result.get("message", "")
        return result

    # ------------------------------------------------------------------
    # 两种下载实现
    # ------------------------------------------------------------------

    def _save_direct(self, url: str, track: Track) -> Dict[str, Any]:
        """直链下载：把音频保存到 download_path。"""
        if not url:
            return {"ok": False, "kind": "direct", "message": "没有可用的直链地址"}
        if not self.download_path:
            return {"ok": False, "kind": "direct",
                    "message": "未配置下载路径（请在「搜索与下载」填写 download_path）"}
        try:
            path = self._target_path(track)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._fetch(url, path)
        except Exception as error:  # noqa: BLE001
            logger.error(f"直链下载失败[{track.title}]：{error}")
            return {"ok": False, "kind": "direct", "message": f"下载失败：{error}"}
        return {"ok": True, "kind": "direct", "message": f"已保存到 {path}", "path": path}

    def _target_path(self, track: Track) -> str:
        """按 {歌手}/{专辑}/{歌名}.{格式} 组织落盘路径（非法字符替换）。"""
        safe = lambda s: "".join(c if c.isalnum() or c in " -_." else "_"
                                 for c in (s or "未知"))
        artist = safe(track.artist) or "未知歌手"
        album = safe(track.album) or "未知专辑"
        title = safe(track.title) or "未知歌曲"
        return os.path.join(self.download_path, artist, album, f"{title}.{self.download_format}")

    @staticmethod
    def _fetch(url: str, path: str) -> None:
        """把 URL 的响应体写入本地文件（懒加载宿主网络模块）。"""
        from app.sdk.network import RequestUtils
        resp = RequestUtils(timeout=120).get_res(url=url, stream=True)
        if resp is None or resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code if resp else '无响应'}")
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

    def _push_torrent(self, url: str, track: Track) -> Dict[str, Any]:
        """把磁力 / 种子推送给宿主的下载客户端（qBittorrent / transmission）。"""
        if not url:
            return {"ok": False, "kind": "torrent", "message": "没有可用的种子 / 磁力链接"}
        try:
            from app.chain.download import DownloadChain
        except Exception as error:  # noqa: BLE001 - 宿主过旧或缺少下载链
            logger.warning(f"宿主不支持下载链（{error}）")
            return {"ok": False, "kind": "torrent",
                    "message": "当前宿主不支持下载链，无法推送到 qBittorrent / transmission"}

        client = self.download_client if self.download_client != "auto" else None
        name = f"{track.artist} {track.title}".strip() or track.title or "音乐下载"
        chain = DownloadChain()
        # 宿主 DownloadChain.download 的签名在不同版本略有差异，依次尝试：
        #   download(content, downloader, ...)
        #   download(content, downloader=..., save_path=..., ...)
        attempts = []
        if client:
            attempts.append(lambda: chain.download(content=url, downloader=client,
                                                  save_path=self.download_path or None))
        attempts.append(lambda: chain.download(content=url, downloader=client,
                                              save_path=self.download_path or None))
        attempts.append(lambda: chain.download(url, client))
        last_err: Optional[Exception] = None
        for attempt in attempts:
            try:
                result = attempt()
                if result:
                    logger.info(f"已推送下载[{name}]到下载客户端（{client or 'auto'}）")
                    return {"ok": True, "kind": "torrent",
                            "message": f"已推送到下载客户端：{name}",
                            "client": client or "auto"}
                last_err = RuntimeError("下载链返回空结果")
            except TypeError:
                # 签名不匹配，试下一个
                continue
            except Exception as error:  # noqa: BLE001
                logger.warning(f"推送下载失败[{name}]：{error}")
                last_err = error
                break
        return {"ok": False, "kind": "torrent",
                "message": f"推送到下载客户端失败：{last_err or '未知错误'}"}
