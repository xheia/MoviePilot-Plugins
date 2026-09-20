"""网易云音乐业务封装。

登录、歌单、每日推荐的原始请求全部经本地部署的 ncm-api 转发，
本模块只负责 Cookie 生命周期和返回值的业务化处理。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger

from .ncm_api import NcmApiClient, NcmApiError
from .utils import change_str, is_valid_cookie, sub_str

#: 扫码状态码含义，取自 ncm-api 的 /login/qr/check。
QR_STATUS = {
    800: "二维码已过期，请重新获取",
    801: "等待扫码",
    802: "已扫码，请在手机上确认登录",
    803: "授权登录成功",
}

#: 状态码 803 表示扫码授权完成。
QR_STATUS_SUCCESS = 803

#: ncm-api / 网易云常见返回码的中文解释。
#: 每日推荐这类接口失败时网易只回一个 code，不解释原因，这里统一翻译成可读文案，
#: 避免插件把「未登录 / 风控 / 空数据」都当成「没问题，只是没歌」。
NCM_CODE_HINT = {
    301: "需要登录（Cookie 已失效或未登录），请重新登录网易云",
    302: "需要登录",
    400: "请求参数错误",
    401: "登录状态异常，请重新登录",
    460: "触发网易风控（cheating），请降低请求频率后重试",
    462: "网易要求二次验证，请到网易云 App 完成验证",
    502: "网易侧返回错误（多出现在密码登录）",
    503: "网易侧限流，请稍后再试",
}


class CloudMusic:
    """网易云歌单与登录业务层。"""

    #: Cookie 缓存文件名，沿用旧版本命名，老用户升级后无需重新登录。
    COOKIE_FILE = "cookie_storage"
    #: 旧版本按约 15 天判断 Cookie 过期，这里保持一致。
    COOKIE_MAX_AGE = 1296010

    def __init__(
        self,
        base_url: Optional[str] = None,
        data_path: Optional[Path] = None,
        timeout: int = 15,
    ) -> None:
        """
        :param base_url: ncm-api 服务地址，例如 ``http://192.168.1.10:1630``
        :param data_path: 插件数据目录，Cookie 缓存写入这里
        :param timeout: 单次请求超时（秒）
        """
        self.data_path = Path(data_path) if data_path else None
        self.api = NcmApiClient(base_url, timeout=timeout)
        self._cookie_loaded = False

    # ------------------------------------------------------------------
    # Cookie 生命周期
    # ------------------------------------------------------------------

    @property
    def cookie(self) -> str:
        """当前使用的 Cookie，首次访问时从磁盘缓存载入。"""
        if not self._cookie_loaded:
            self._cookie_loaded = True
            self.api.set_cookie(self._read_cookie())
        return self.api.cookie

    def _cookie_path(self) -> Optional[Path]:
        """Cookie 缓存文件路径。"""
        if not self.data_path:
            return None
        return self.data_path / self.COOKIE_FILE

    def _read_cookie(self) -> str:
        """从磁盘读取缓存的 Cookie，过期或损坏时返回空串。"""
        path = self._cookie_path()
        if not path or not path.is_file():
            return ""
        try:
            storage = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.error(f"读取网易云 Cookie 缓存失败：{error}")
            return ""
        created = storage.get("create_time_stamp") or 0
        if time.time() - created > self.COOKIE_MAX_AGE:
            logger.info("网易云 Cookie 已超过 15 天，按过期处理，请重新登录")
            return ""
        return storage.get("cookie") or ""

    def save_cookie(self, cookie: str) -> bool:
        """校验并持久化 Cookie，返回是否保存成功。"""
        cookie = (cookie or "").strip()
        if not is_valid_cookie(cookie):
            logger.error(
                "Cookie 不合法：缺少 MUSIC_U 等登录标识，"
                "请重新扫码登录或复制完整 Cookie"
            )
            return False
        self.api.set_cookie(cookie)
        self._cookie_loaded = True
        path = self._cookie_path()
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {"cookie": cookie, "create_time_stamp": time.time()},
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError as error:
                logger.error(f"写入网易云 Cookie 缓存失败：{error}")
        return True

    def clear_cookie(self) -> None:
        """清除内存与磁盘上的 Cookie。"""
        self.api.set_cookie("")
        self._cookie_loaded = True
        path = self._cookie_path()
        if path and path.is_file():
            try:
                path.unlink()
            except OSError as error:
                logger.error(f"删除网易云 Cookie 缓存失败：{error}")

    # ------------------------------------------------------------------
    # 服务探测
    # ------------------------------------------------------------------

    def ping(self) -> str:
        """探测 ncm-api 连通性，返回版本号。"""
        return self.api.ping()

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------

    def login_status(self) -> Optional[str]:
        """返回当前登录账号昵称；未登录或服务异常时返回 None。"""
        if not self.cookie:
            return None
        try:
            profile = self.api.login_status()
        except NcmApiError as error:
            logger.error(f"查询网易云登录状态失败：{error}")
            return None
        if not profile:
            return None
        return (profile.get("profile") or {}).get("nickname") or None

    def login_qrcode(self) -> Tuple[str, str]:
        """生成扫码登录二维码。

        :return: ``(unikey, qrimg)``，``qrimg`` 是可直接渲染的 data URL
        """
        key = self.api.qrcode_key()
        if not key:
            raise NcmApiError("ncm-api 未返回二维码 key")
        image = self.api.qrcode_image(key)
        return key, image.get("qrimg") or ""

    def check_qrcode(self, key: str) -> Dict[str, Any]:
        """查询扫码状态。

        :return: ``{"code": int, "message": str, "cookie": str}``，
            含义见 :data:`QR_STATUS`
        """
        result = self.api.qrcode_check(key)
        return {
            "code": result.get("code"),
            "message": result.get("message") or "",
            "cookie": result.get("cookie") or "",
        }

    def send_captcha(self, phone: str) -> Dict[str, Any]:
        """发送短信验证码。"""
        return self.api.send_captcha((phone or "").strip())

    def login_by_captcha(self, phone: str, captcha: str) -> bool:
        """手机号 + 短信验证码登录。"""
        phone = (phone or "").strip()
        captcha = (captcha or "").strip()
        if not phone or not captcha:
            logger.error("手机号或验证码为空，无法登录")
            return False
        return self._handle_login_result(self.api.login_by_captcha(phone, captcha))

    def login_by_password(self, account: str, password: str) -> bool:
        """手机号或邮箱 + 密码登录。"""
        account = (account or "").strip()
        password = (password or "").strip()
        if not account or not password:
            logger.error("账号或密码为空，无法登录")
            return False
        return self._handle_login_result(self.api.login_by_password(account, password))

    def login_by_cookie(self, cookie: str) -> bool:
        """直接使用用户粘贴的 Cookie 登录（先落盘再校验状态）。"""
        if not self.save_cookie(cookie):
            return False
        nickname = self.login_status()
        if nickname:
            logger.info(f"网易云 Cookie 校验通过，当前账号：{nickname}")
            return True
        logger.error("Cookie 已保存，但 ncm-api 返回未登录状态，请检查 Cookie 是否完整或已失效")
        return False

    def refresh_login(self) -> bool:
        """刷新登录状态，延长 Cookie 有效期。

        注意：ncm-api 文档明确 ``/login/refresh`` 不支持刷新二维码登录
        得到的 Cookie，扫码登录的账号请以检查登录状态为主。
        """
        try:
            result = self.api.login_refresh()
        except NcmApiError as error:
            logger.warning(f"刷新网易云登录状态失败（已忽略）：{error}")
            return False
        code = result.get("code")
        cookie = result.get("cookie") or (result.get("data") or {}).get("cookie") or ""
        if code == 200 and cookie:
            self.save_cookie(cookie)
            logger.info("网易云登录状态已刷新，Cookie 已更新")
            return True
        reason = result.get("message") or result.get("msg") or f"code={code}"
        logger.info(f"网易云暂不支持刷新当前 Cookie（{reason}），将以状态检查为准")
        return False

    def logout(self) -> None:
        """退出登录并清理本地 Cookie。"""
        try:
            if self.cookie:
                self.api.logout()
        except NcmApiError as error:
            logger.warning(f"调用退出登录接口失败（已忽略）：{error}")
        self.clear_cookie()
        logger.info("已退出网易云账号并清除本地 Cookie")

    def _handle_login_result(self, result: Dict[str, Any]) -> bool:
        """处理 ncm-api 登录接口的统一返回。"""
        code = result.get("code")
        cookie = result.get("cookie") or (result.get("data") or {}).get("cookie") or ""
        if code != 200 or not cookie:
            reason = result.get("message") or result.get("msg") or result
            logger.error(f"网易云登录失败：code={code}, 原因：{reason}")
            return False
        if not self.save_cookie(cookie):
            return False
        nickname = (result.get("profile") or {}).get("nickname") or ""
        logger.info(f"网易云登录成功：{nickname}")
        return True

    # ------------------------------------------------------------------
    # 歌单与推荐
    # ------------------------------------------------------------------

    def signin(self) -> Dict[str, Any]:
        """网易云签到。"""
        return self.api.daily_signin()

    def get_list_days(self, nums: int = 5) -> List[List[Any]]:
        """每日推荐歌单，返回 ``[[歌单id, 歌单名], ...]``。

        接口失败或返回空列表时抛 :class:`NcmApiError`，把失败原因带到调用方，
        避免上游只看到一个空列表而误判成「没有歌可同步」。
        """
        result = self.api.recommend_playlists()
        self._check_result(result, "获取每日推荐歌单")
        recommend = result.get("recommend") or []
        if not recommend:
            raise NcmApiError(
                "获取每日推荐歌单失败：网易云返回的推荐列表为空"
                "（常见原因：账号未登录、Cookie 已失效，或当日推荐尚未生成）"
            )
        return [
            [item.get("id"), item.get("name")]
            for item in recommend[:nums]
            if item.get("id")
        ]

    def get_song_daily(self) -> List[List[Any]]:
        """每日推荐歌曲，返回 ``[[歌名, [歌手, ...]], ...]``。

        与 :meth:`get_list_days` 同样在失败时抛异常，不再静默返回空列表。
        """
        result = self.api.recommend_songs()
        self._check_result(result, "获取每日推荐歌曲")
        daily_songs = (result.get("data") or {}).get("dailySongs") or []
        if not daily_songs:
            raise NcmApiError(
                "获取每日推荐歌曲失败：网易云返回的 dailySongs 为空"
                "（常见原因：账号未登录、Cookie 已失效，或当日推荐尚未生成）"
            )
        return [self._to_track(song) for song in daily_songs]

    def get_category_playlists(self, cat: str, nums: int = 1, limit: int = 6) -> List[List[Any]]:
        """按网易云官方歌单分类取热门歌单，返回 ``[[歌单id, 歌单名], ...]``。

        「听歌模式」的数据源：清晨 / 轻音乐 / 学习 / 运动等场景分类由
        网易云官方与达人不定期更新，插件每天自动取榜首歌单同步，
        内容跟随官方刷新，无需人工维护。
        接口失败或返回空列表时抛 :class:`NcmApiError`。
        """
        cat = (cat or "").strip()
        if not cat:
            raise NcmApiError("获取场景歌单失败：分类名为空")
        result = self.api.top_playlists(cat, limit=limit)
        self._check_result(result, f"获取场景歌单[{cat}]")
        playlists = result.get("playlists") or []
        if not playlists:
            raise NcmApiError(
                f"获取场景歌单[{cat}]失败：网易云该分类下没有返回歌单"
                "（请确认分类名是否为网易云官方分类，或在「自定义场景」里改写）"
            )
        picked = [
            [item.get("id"), item.get("name")]
            for item in playlists[:max(1, int(nums or 1))]
            if item.get("id")
        ]
        if not picked:
            raise NcmApiError(f"获取场景歌单[{cat}]失败：返回结果里没有有效歌单 id")
        return picked

    def diagnose_recommend(self) -> Dict[str, Any]:
        """探测每日推荐的两个接口，返回可读结果，供配置页与日志排错。

        只做只读探测，不抛异常，任何错误都收敛进返回值。
        """
        report: Dict[str, Any] = {}
        for key, label, call in (
            ("daily_list", "每日推荐歌单", self.api.recommend_playlists),
            ("daily_song", "每日推荐歌曲", self.api.recommend_songs),
        ):
            try:
                result = call()
                code = self._result_code(result)
                if key == "daily_list":
                    count = len(result.get("recommend") or [])
                else:
                    count = len((result.get("data") or {}).get("dailySongs") or [])
                message = result.get("message") or result.get("msg") or ""
                if code == 200 and count == 0:
                    message = message or "接口正常但返回空数据（多半是未登录或当日推荐为空）"
                if code != 200 and not message:
                    message = NCM_CODE_HINT.get(code, "未知错误")
                report[key] = {
                    "label": label,
                    "ok": code == 200 and count > 0,
                    "code": code,
                    "count": count,
                    "message": message,
                }
            except Exception as error:  # noqa: BLE001 - 探针本身不能抛
                report[key] = {
                    "label": label,
                    "ok": False,
                    "code": None,
                    "count": 0,
                    "message": str(error),
                }
        return report

    @staticmethod
    def _result_code(result: Dict[str, Any]) -> int:
        """取出返回体里的业务码，字段缺失时视为成功（兼容老版本 ncm-api）。"""
        raw = result.get("code", result.get("status", 200))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 200

    def _check_result(self, result: Dict[str, Any], action: str) -> None:
        """校验返回码，失败时抛出带中文原因的 :class:`NcmApiError`。"""
        code = self._result_code(result)
        if code == 200:
            return
        reason = result.get("message") or result.get("msg") or ""
        hint = NCM_CODE_HINT.get(code)
        if hint and (not reason or str(reason) in hint):
            # 上游只回了「需要登录」这类短语，用带排查建议的文案替代，避免重复堆叠
            reason = hint
        elif hint:
            reason = f"{reason}（{hint}）"
        elif not reason:
            reason = "未知错误"
        raise NcmApiError(f"{action}失败：code={code}，{reason}")

    def playlist(self, playlist_id: str) -> List[Dict[str, Any]]:
        """获取歌单全部歌曲的原始列表。"""
        result = self.api.playlist_tracks(playlist_id)
        return result.get("songs") or []

    def songofplaylist(self, playlist_id: str) -> List[List[Any]]:
        """获取歌单歌曲，返回 ``[[歌名, [歌手, ...]], ...]``，失败时重试 5 次。"""
        tracks: List[Dict[str, Any]] = []
        max_retry_times = 5
        retry_times = 0
        while retry_times < max_retry_times:
            try:
                tracks = self.playlist(playlist_id)
                if tracks:
                    break
                logger.warning(
                    f"第 {retry_times + 1} 次获取歌单 {playlist_id} 为空，准备重试"
                )
            except Exception as error:  # noqa: BLE001 - 网络抖动统一重试
                logger.warning(f"第 {retry_times + 1} 次重试失败：获取歌单错误 {error}")
            retry_times += 1
            time.sleep(2)
        return [self._to_track(track) for track in tracks]

    @staticmethod
    def _to_track(raw: Dict[str, Any]) -> List[Any]:
        """把 ncm-api 的歌曲对象转换成 ``[歌名, [歌手, ...], 专辑名]``。

        专辑名可能为空串（老版本 ncm-api 不返回 al 字段时），下游所有
        消费方都按「第三个元素可选」处理，不影响旧逻辑。
        """
        name = sub_str(raw.get("name"))
        # 新版接口用 ar，老接口用 artists，两者都兼容
        artists = raw.get("ar") or raw.get("artists") or []
        singers = [change_str(artist.get("name")) for artist in artists]
        album_raw = raw.get("al") or raw.get("album") or {}
        album = sub_str(album_raw.get("name")) if isinstance(album_raw, dict) else ""
        return [name, [singer for singer in singers if singer], album or ""]

    # ------------------------------------------------------------------
    # 曲目校验（库内缺失的歌曲去 music.163.com 确认真身）
    # ------------------------------------------------------------------

    @staticmethod
    def norm_text(text: Any) -> str:
        """把歌名/歌手/专辑名归一化，用于比对。

        去掉括号补充说明、各类标点与空白并统一小写，这样
        「雨蝶 (Live)」「雨蝶【现场版】」「雨蝶」会被视为同一首。
        """
        value = sub_str(text) or ""
        value = re.sub(r"[（(\[【].*?[)）\]】]", "", value)
        value = re.sub(r"[\s\-_·,，.。!！?？:：;；'\"“”‘’/\\|]+", "", value)
        return value.lower()

    def search_track(
        self, title: str, artist: str = "", limit: int = 8,
    ) -> List[Dict[str, Any]]:
        """在网易云搜索曲目，返回候选列表（含打分）。

        候选结构：``{song_id, title, artist, album, score}``，
        按匹配度降序排列。
        """
        title = sub_str(title)
        artist = sub_str(artist)
        if not title:
            return []
        keyword = f"{artist} {title}".strip()
        result = self.api.search_songs(keyword, limit=limit)
        songs = (result.get("result") or {}).get("songs") or []
        candidates: List[Dict[str, Any]] = []
        norm_title = self.norm_text(title)
        norm_artist = self.norm_text(artist)
        for raw in songs:
            if not isinstance(raw, dict):
                continue
            track = self._to_track(raw)
            cand_title = track[0]
            cand_artists = track[1] or []
            cand_album = track[2] if len(track) > 2 else ""
            candidates.append({
                "song_id": raw.get("id") or 0,
                "title": cand_title,
                "artist": "、".join(cand_artists),
                "album": cand_album,
                "score": self.match_score(
                    norm_title, norm_artist, cand_title, cand_artists,
                ),
            })
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates

    @staticmethod
    def match_score(
        norm_title: str, norm_artist: str,
        cand_title: str, cand_artists: List[str],
    ) -> int:
        """给一个候选曲目打匹配分：标题权重最高，其次歌手。"""
        score = 0
        cand_norm_title = CloudMusic.norm_text(cand_title)
        if norm_title and cand_norm_title:
            if norm_title == cand_norm_title:
                score += 3
            elif norm_title in cand_norm_title or cand_norm_title in norm_title:
                score += 1
        if norm_artist:
            for name in cand_artists or []:
                cand_norm_artist = CloudMusic.norm_text(name)
                if not cand_norm_artist:
                    continue
                if norm_artist == cand_norm_artist:
                    score += 2
                    break
                if norm_artist in cand_norm_artist or cand_norm_artist in norm_artist:
                    score += 1
        return score

    #: 校验通过所需的最低匹配分：标题完全一致即视为命中。
    VERIFY_SCORE_THRESHOLD = 3

    def verify_track(
        self, title: str, artist: str = "", album: str = "",
    ) -> Dict[str, Any]:
        """到 music.163.com 校验一首歌是否存在，并回填权威元数据。

        :return: ``{status, song_id, title, artist, album, score,
                  candidates, message}``；``status`` 取 ``ok`` /
                  ``not_found`` / ``error``，本方法不抛异常。
        """
        result: Dict[str, Any] = {
            "status": "error",
            "song_id": 0,
            "title": "",
            "artist": "",
            "album": "",
            "score": 0,
            "candidates": 0,
            "message": "",
        }
        try:
            candidates = self.search_track(title, artist)
        except Exception as error:  # noqa: BLE001 - 校验失败不影响同步
            result["message"] = str(error)
            return result
        result["candidates"] = len(candidates)
        if not candidates:
            result["status"] = "not_found"
            result["message"] = "网易云搜索无结果"
            return result
        best = candidates[0]
        result.update({
            "song_id": best.get("song_id") or 0,
            "title": best.get("title") or "",
            "artist": best.get("artist") or "",
            "album": best.get("album") or "",
            "score": best.get("score") or 0,
        })
        if (best.get("score") or 0) >= self.VERIFY_SCORE_THRESHOLD:
            result["status"] = "ok"
            result["message"] = f"匹配度 {best['score']}（候选 {len(candidates)} 条）"
        else:
            result["status"] = "not_found"
            result["message"] = (
                f"匹配度不足（最高 {best.get('score') or 0}，"
                f"候选 {len(candidates)} 条）"
            )
        return result
