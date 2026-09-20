"""歌单同步工具（MoviePilot V3）。

把 QQ 音乐 / 网易云歌单同步到 Plex 与 Emby 的音乐库播放列表。

V3 版本的两处关键变化：

1. 网易云的登录与取数不再由插件内置的 ``NeteaseCloudMusicApi.js``
   （1.3MB 浏览器打包产物 + ``py_mini_racer`` V8 引擎）直连官方接口，
   而是统一调用本地部署的 ``moefurina/ncm-api:latest`` 容器。
   加密、风控与解灰适配交给 ncm-api 维护，插件同时去掉了两个第三方依赖。
2. 登录方式支持扫码、短信验证码、手机号/邮箱密码、手动粘贴 Cookie 四种。
"""

import re
import time
from datetime import datetime, timedelta
from threading import Event
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.services import ServiceConfigHelper

from .QQmusic import QQMusicApi
from .cloudmusic import QR_STATUS, QR_STATUS_SUCCESS, CloudMusic
from .emby_music import EmbyMusic
from .ncm_api import NcmApiClient, NcmApiError
from .plex_music import PlexMusic
from .qishui import QishuiClient, QishuiError, looks_like_qishui_link

# --------------------------------------------------------------------------
# 配置页按钮交互脚本。
# Vuetify JSON 模式下 `on*` 事件的值是函数代码字符串，前端 FormRender 会在
# 表单模型上下文里执行（等价 with(model){...}），因此脚本里可直接读写
# 表单字段（ncm_api_url、wylogin_user 等）实现「点按钮即时出结果」。
# --------------------------------------------------------------------------

JS_PROBE = """
async function (event) {
  probe_loading = true;
  try {
    const resp = await window.MoviePilotAPI.get(
      'plugin/MusicSubscribe/probe?api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    if (resp && resp.success) {
      probe_msg = '连接成功，ncm-api 版本：' + ((resp.data && resp.data.version) || '未知');
    } else {
      probe_msg = (resp && resp.message) || '连接失败，请检查地址与容器状态';
    }
  } catch (err) {
    probe_msg = '连接失败：' + ((err && err.message) || err);
  } finally {
    probe_loading = false;
  }
}
"""

JS_QR_FETCH = """
async function (event) {
  qr_loading = true;
  try {
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/qrcode?api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    const data = (resp && resp.data) || {};
    if (resp && resp.success && data.qrimg) {
      qr_img = data.qrimg;
      qr_msg = '二维码已生成，请用网易云音乐 App 扫码，并在手机上确认登录';
    } else {
      qr_img = '';
      qr_msg = (resp && resp.message) || '获取二维码失败，请先测试 ncm-api 连接';
    }
  } catch (err) {
    qr_img = '';
    qr_msg = '获取二维码失败：' + ((err && err.message) || err);
  } finally {
    qr_loading = false;
  }
}
"""

JS_QR_CHECK = """
async function (event) {
  qr_loading = true;
  try {
    const resp = await window.MoviePilotAPI.get('plugin/MusicSubscribe/qrcode/status');
    const data = (resp && resp.data) || {};
    if (resp && resp.success) {
      if (data.logged_in) {
        qr_img = '';
        qr_msg = '扫码登录成功：' + (data.nickname || '未知账号')
          + '。Cookie 已保存，请点击右下角「保存」使配置生效';
      } else {
        qr_msg = data.message || data.status || '等待扫码…';
      }
    } else {
      qr_msg = (resp && resp.message) || '检查扫码结果失败';
    }
  } catch (err) {
    qr_msg = '检查扫码结果失败：' + ((err && err.message) || err);
  } finally {
    qr_loading = false;
  }
}
"""

JS_CAPTCHA_SEND = """
async function (event) {
  if (!(wylogin_user || '').trim()) {
    login_msg = '请先填写手机号';
    return;
  }
  try {
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/captcha/send?phone=' + encodeURIComponent(wylogin_user || '')
      + '&api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    login_msg = (resp && resp.message) || '验证码发送失败';
  } catch (err) {
    login_msg = '验证码发送失败：' + ((err && err.message) || err);
  }
}
"""

JS_LOGIN_TEMPLATE = """
async function (event) {
  login_loading = true;
  try {
    const params = new URLSearchParams();
    params.set('api_url', ncm_api_url || '');
    params.set('login_type', '%(login_type)s');
    params.set('user', wylogin_user || '');
    params.set('password', wylogin_password || '');
    params.set('cookie', wylogin_cookie || '');
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/login?' + params.toString()
    );
    if (resp && resp.success) {
      login_msg = resp.message || '登录成功';
      wylogin_password = '';
    } else {
      login_msg = (resp && resp.message) || '登录失败';
    }
  } catch (err) {
    login_msg = '登录失败：' + ((err && err.message) || err);
  } finally {
    login_loading = false;
  }
}
"""

JS_LOGIN_CAPTCHA = JS_LOGIN_TEMPLATE % {'login_type': 'captcha'}
JS_LOGIN_PASSWORD = JS_LOGIN_TEMPLATE % {'login_type': 'password'}
JS_LOGIN_COOKIE = JS_LOGIN_TEMPLATE % {'login_type': 'cookie'}


class MusicSubscribe(_PluginBase):
    # 插件名称
    plugin_name = "歌单订阅"
    # 插件描述
    plugin_desc = "歌单订阅：同步QQ&网易云&汽水音乐歌单到plex&emby，库内没有的歌曲可转为音乐订阅。"
    # 插件图标
    plugin_icon = "music.png"
    # 插件版本
    plugin_version = "8.2.0"
    # 插件作者
    plugin_author = "逗猫"
    # 作者主页
    author_url = "https://github.com/baozaodetudou"
    # 插件配置项ID前缀
    plugin_config_prefix = "music_"
    # 加载顺序
    plugin_order = 17
    # 可使用的用户级别
    auth_level = 1

    #: ncm-api 默认地址。ncm-api 默认容器端口 3000 与 MoviePilot 冲突，
    #: 宿主机映射端口统一用 1630（如 -p 1630:3000），配置页可随时修改。
    DEFAULT_NCM_API_URL = "http://192.168.1.100:1630"
    #: 二维码在配置页保留的有效时长（秒），过期后需要重新获取
    QRCODE_TTL = 300
    #: 插件数据中保存二维码的键名
    QRCODE_DATA_KEY = "netease_qrcode"
    #: 配置页交互用的临时字段，不落盘（保存配置时剔除）
    TRANSIENT_KEYS = (
        "qr_img", "qr_msg", "qr_loading",
        "login_msg", "login_loading",
        "probe_msg", "probe_loading",
    )

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    # 启动
    _enabled = False
    # 运行一次
    _onlyonce = False
    # 定时
    _cron = None
    # 媒体服务器
    _media_server: List[str] = []
    # 精准匹配开关
    _exact_match = True
    # ncm-api 服务地址
    _ncm_api_url = DEFAULT_NCM_API_URL
    # 网易云登录方式：qrcode / captcha / password / cookie
    _login_type = "qrcode"
    # 网易云登录信息（按登录方式复用：用户名 + 密码/验证码 + Cookie）
    _wylogin_user = ""
    _wylogin_password = ""
    _wylogin_cookie = ""
    # Cookie 保活：每天检查登录状态并尝试刷新
    _wy_keepalive = True
    # 每日推荐
    _wy_daily_list = False
    _wy_daily_song = False
    # 同步列表
    _wymusic_paths = ""
    _qqmusic_paths = ""
    # 退出事件
    _event = Event()

    # 运行时对象
    cm: Optional[CloudMusic] = None
    pm: Optional[PlexMusic] = None
    em: Optional[EmbyMusic] = None
    # 媒体服务器（init_plugin 时按宿主配置刷新；这里给出默认值，
    # 保证 init_plugin 尚未执行时 get_form() 也能安全渲染）
    media_config: Dict[str, Any] = {}
    media_list: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def init_plugin(self, config: dict = None):
        """读取配置、执行待办登录动作，并按需注册定时同步。"""
        # 停止现有任务
        self.stop_service()
        self._scheduler = None

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._cron = config.get("cron")
        self._media_server = config.get("media_server") or []
        # 注意：不能用 `or True`，否则用户关掉精准匹配也会被强制打开
        self._exact_match = (
            True if config.get("exact_match") is None else bool(config.get("exact_match"))
        )
        self._ncm_api_url = (
            config.get("ncm_api_url") or self.DEFAULT_NCM_API_URL
        ).strip()
        self._login_type = config.get("login_type") or "qrcode"
        self._wylogin_user = config.get("wylogin_user") or ""
        self._wylogin_password = config.get("wylogin_password") or ""
        self._wylogin_cookie = config.get("wylogin_cookie") or ""
        # Cookie 保活默认开启，旧配置没有该字段时视为开启
        self._wy_keepalive = (
            True if config.get("wy_keepalive") is None else bool(config.get("wy_keepalive"))
        )
        self._wymusic_paths = config.get("wymusic_paths") or ""
        self._qqmusic_paths = config.get("qqmusic_paths") or ""
        self._wy_daily_list = bool(config.get("wy_daily_list"))
        self._wy_daily_song = bool(config.get("wy_daily_song"))
        # 库内没有的歌曲是否转为 MoviePilot 音乐订阅
        self._wy_subscribe = bool(config.get("wy_subscribe"))

        # 配置页交互字段（二维码图片、提示消息等）只存在于表单模型，
        # 保存时会被前端原样带回，这里剔除后写回，避免污染持久化配置
        self._strip_transient_config(config)

        # 网易云客户端（所有请求经本地 ncm-api 转发）
        self.cm = CloudMusic(
            base_url=self._ncm_api_url,
            data_path=self.get_data_path(),
        )

        # 媒体服务器列表
        mediaserver_configs = ServiceConfigHelper.get_mediaserver_configs()
        self.media_config = {conf.name: conf for conf in mediaserver_configs if conf.enabled}
        self.media_list = [
            {'title': conf.name, 'value': conf.name}
            for conf in mediaserver_configs
            if conf.enabled
        ]

        # 账号状态
        self._username = None
        self._load_login_state()

        # 执行配置页上的一次性登录动作（开关已复位时会重新保存配置）
        self._handle_pending_actions(config)

        # 密码登录方式下 Cookie 失效时自动续登，行为和 V2 版本保持一致
        if (
            not self._username
            and self._login_type == "password"
            and self._wylogin_user
            and self._wylogin_password
        ):
            if self.cm.login_by_password(self._wylogin_user, self._wylogin_password):
                self._load_login_state()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:
            if self._onlyonce:
                logger.info("歌单同步服务，立即运行一次")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(
                    func=self.__run_sync_paylist,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="歌单同步",
                )
                # 关闭一次性开关
                self._onlyonce = False
                self._save_config()
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def _strip_transient_config(self, config: dict) -> None:
        """把配置页回传的临时字段从持久化配置里清掉。"""
        dirty = [
            key
            for key in self.TRANSIENT_KEYS
            if config.get(key) not in (None, "", False)
        ]
        if not dirty:
            return
        cleaned = {key: "" for key in dirty}
        cleaned.update({k: v for k, v in config.items() if k not in self.TRANSIENT_KEYS})
        try:
            self.update_config(cleaned)
        except Exception as error:  # noqa: BLE001 - 清理失败不影响正常流程
            logger.warning(f"清理配置页临时字段失败（已忽略）：{error}")

    def get_state(self) -> bool:
        """返回插件是否启用（含「立即运行一次」）。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册登录与状态查询接口，方便脚本或前端直接驱动。

        完整路径为 ``/api/v1/plugin/MusicSubscribe/<path>``，
        返回 ``{success, message, data}`` 信封。
        """
        return [
            {
                "path": "/probe",
                "endpoint": self.api_probe,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "探测 ncm-api 连通性",
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询网易云登录状态",
            },
            {
                "path": "/qrcode",
                "endpoint": self.api_qrcode,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "获取网易云扫码登录二维码",
            },
            {
                "path": "/qrcode/status",
                "endpoint": self.api_qrcode_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询扫码状态，成功后自动保存 Cookie",
            },
            {
                "path": "/captcha/send",
                "endpoint": self.api_captcha_send,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "发送网易云登录短信验证码",
            },
            {
                "path": "/login",
                "endpoint": self.api_login,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "验证码/密码/Cookie 登录",
            },
            {
                "path": "/cookie",
                "endpoint": self.api_cookie,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "使用 Cookie 登录",
            },
            {
                "path": "/logout",
                "endpoint": self.api_logout,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "退出网易云账号",
            },
        ]

    # ------------------------------------------------------------------
    # 插件 API
    # ------------------------------------------------------------------

    def _make_client(self, api_url: Optional[str]) -> CloudMusic:
        """按指定服务地址构建临时客户端，复用 Cookie 缓存目录。

        配置页按钮允许在保存之前就用「表单里正在编辑的地址」发起请求。
        """
        url = NcmApiClient.normalize_base_url(api_url) if api_url else ""
        if not url or url == self._ncm_api_url:
            return self.cm
        return CloudMusic(
            base_url=url,
            data_path=self.get_data_path(),
        )

    def api_probe(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """探测 ncm-api 服务连通性。"""
        cm = self._make_client(api_url)
        try:
            version = cm.ping()
        except Exception as error:  # noqa: BLE001 - 接口不做异常透出
            return {"success": False, "message": str(error), "data": {}}
        return {
            "success": True,
            "message": "",
            "data": {"url": cm.api.base_url, "version": version},
        }

    def api_status(self) -> Dict[str, Any]:
        """查询网易云登录状态。"""
        try:
            nickname = self.cm.login_status()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        return {
            "success": True,
            "message": "",
            "data": {"logged_in": bool(nickname), "nickname": nickname or ""},
        }

    def api_qrcode(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """获取扫码登录二维码并暂存 unikey。"""
        cm = self._make_client(api_url)
        try:
            key, image = cm.login_qrcode()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        self.save_data(
            self.QRCODE_DATA_KEY,
            {"unikey": key, "qrimg": image, "create_time_stamp": time.time()},
        )
        return {"success": True, "message": "", "data": {"unikey": key, "qrimg": image}}

    def api_qrcode_status(self) -> Dict[str, Any]:
        """查询扫码状态，扫码成功后保存 Cookie。"""
        qrcode = self.get_data(self.QRCODE_DATA_KEY) or {}
        key = qrcode.get("unikey")
        if not key:
            return {"success": False, "message": "没有可用的二维码，请先获取二维码", "data": {}}
        try:
            result = self.cm.check_qrcode(key)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        data = {
            "code": result.get("code"),
            "message": result.get("message") or "",
            "status": QR_STATUS.get(result.get("code"), "未知状态"),
            "logged_in": False,
            "nickname": "",
        }
        if result.get("code") == QR_STATUS_SUCCESS:
            if self.cm.save_cookie(result.get("cookie") or ""):
                data["logged_in"] = True
                data["nickname"] = self.cm.login_status() or ""
            self.del_data(self.QRCODE_DATA_KEY)
        return {"success": True, "message": "", "data": data}

    def api_captcha_send(
        self, phone: str = "", api_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送网易云登录短信验证码。"""
        phone = (phone or "").strip()
        if not phone:
            return {"success": False, "message": "请先填写手机号", "data": {}}
        cm = self._make_client(api_url)
        try:
            result = cm.send_captcha(phone)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        code = result.get("code")
        if code == 200:
            return {"success": True, "message": "验证码已发送，请查收短信", "data": {}}
        reason = result.get("message") or result.get("msg") or f"code={code}"
        return {"success": False, "message": f"验证码发送失败：{reason}", "data": {}}

    def api_login(
        self,
        api_url: Optional[str] = None,
        login_type: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        cookie: Optional[str] = None,
    ) -> Dict[str, Any]:
        """验证码/密码/Cookie 登录，登录成功后 Cookie 直接落盘。"""
        login_type = login_type or self._login_type or "qrcode"
        cm = self._make_client(api_url)
        try:
            if login_type == "captcha":
                ok = cm.login_by_captcha(user or "", password or "")
            elif login_type == "password":
                ok = cm.login_by_password(user or "", password or "")
            elif login_type == "cookie":
                ok = cm.login_by_cookie(cookie or "")
            else:
                return {
                    "success": False,
                    "message": f"不支持的登录方式：{login_type}，扫码请用二维码按钮",
                    "data": {},
                }
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        if not ok:
            return {
                "success": False,
                "message": "登录失败，请检查账号信息；频繁失败可能触发网易风控，请稍后再试",
                "data": {},
            }
        nickname = cm.login_status() or ""
        return {
            "success": True,
            "message": f"登录成功，当前账号：{nickname}" if nickname else "登录成功",
            "data": {"nickname": nickname},
        }

    def api_cookie(self, cookie: Optional[str] = None) -> Dict[str, Any]:
        """使用 Cookie 登录。"""
        cookie = cookie or self._wylogin_cookie
        try:
            ok = self.cm.login_by_cookie(cookie)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        return {
            "success": ok,
            "message": "" if ok else "Cookie 校验未通过，请检查是否完整或已失效",
            "data": {"nickname": self.cm.login_status() or ""},
        }

    def api_logout(self) -> Dict[str, Any]:
        """退出网易云账号。"""
        try:
            self.cm.logout()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        self.del_data(self.QRCODE_DATA_KEY)
        return {"success": True, "message": "", "data": {}}

    # ------------------------------------------------------------------
    # 配置页
    # ------------------------------------------------------------------

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面：页面 JSON + 默认配置模型。"""
        self._load_login_state()

        content: List[dict] = [
            {
                'component': 'VRow',
                'content': [
                    self._col(6, self._switch('enabled', '启用插件')),
                    self._col(6, self._switch('onlyonce', '立即运行一次')),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VSelect',
                        'props': {
                            'chips': True,
                            'multiple': True,
                            'model': 'media_server',
                            'label': '媒体服务器',
                            'items': self.media_list,
                        },
                    }),
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {
                            'model': 'cron',
                            'label': '执行周期',
                            'placeholder': '5位cron表达式，留空自动, 建议每天一次',
                        },
                    }),
                    self._col(6, self._switch('exact_match', '精准匹配(同时匹配歌曲名称和歌手)')),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {
                            'model': 'ncm_api_url',
                            'label': 'ncm-api 服务地址',
                            'placeholder': 'http://192.168.1.100:1630',
                        },
                    }),
                    self._col(6, self._button(
                        '测试连接', JS_PROBE, color='info', loading_model='probe_loading',
                    )),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'title': 'ncm-api 与账号状态',
                                    'text': self._ncm_status_text,
                                },
                            }
                        ],
                    }
                ],
            },
        ]

        # 登录区：按登录方式联动显示，操作按钮直接调插件 API 并即时回显
        content.extend(self._login_blocks())

        content.extend([
            {
                'component': 'VRow',
                'content': [
                    self._col(4, self._switch('wy_daily_song', '同步每日推荐歌曲')),
                    self._col(4, self._switch('wy_daily_list', '同步每日推荐歌单')),
                    self._col(4, self._switch('wy_subscribe', '库内没有的歌曲转为音乐订阅')),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'qqmusic_paths',
                                    'label': 'QQ音乐歌单同步设置',
                                    'rows': 4,
                                    'placeholder':
                                        '一行一个歌单配置留空不启用 \n'
                                        '默认格式：QQ音乐歌单id:plex/emby播放列表名称\n'
                                        'eg: 2362260213:经典歌曲\n'
                                        'emby多用户格式：QQ音乐歌单id:plex/emby播放列表名称:emby用户名 \n'
                                        'eg: 2362260213:经典歌曲:doumao\n'
                                        'emby多用户格式：QQ音乐歌单id:plex/emby播放列表名称:emby1,emby2 \n'
                                        'eg: 2362260213:经典歌曲:doumao,tudou\n',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'wymusic_paths',
                                    'label': '网易云歌单同步设置',
                                    'rows': 4,
                                    'placeholder':
                                        '一行一个歌单配置留空不启用 \n'
                                        '网易云格式：歌单id:播放列表名称[:emby用户名] \n'
                                        'eg: 2362260213:经典歌曲 \n'
                                        '汽水音乐：粘贴App里的歌单分享链接:播放列表名称 \n'
                                        'eg: https://qishui.douyin.com/xxxx:华语精选 \n',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'title': '使用说明:',
                                    'text':
                                        '1. 部署 ncm-api：docker run -d --name ncm-api '
                                        '-p 1630:3000 moefurina/ncm-api:latest，'
                                        '地址填 http://192.168.X.X:1630; \n'
                                        '2. 登录后选择歌单同步（一行一个，支持汽水音乐分享链接）; \n'
                                        '3. 开启「库内没有的歌曲转为音乐订阅」后，'
                                        '同步时没搜到的歌曲会自动加入 MoviePilot 音乐订阅; \n'
                                        '4. 同步只添加媒体库已有歌曲，不会自动下载; \n',
                                },
                            }
                        ],
                    }
                ],
            },
        ])

        return [{'component': 'VForm', 'content': content}], {
            "enabled": False,
            "onlyonce": False,
            "cron": "0 7 * * *",
            "media_server": [],
            "exact_match": True,
            "ncm_api_url": self.DEFAULT_NCM_API_URL,
            "login_type": "qrcode",
            "wylogin_user": "",
            "wylogin_password": "",
            "wylogin_cookie": "",
            "wy_keepalive": True,
            "wy_subscribe": False,
            "wy_daily_song": False,
            "wy_daily_list": False,
            "wymusic_paths": "",
            "qqmusic_paths": "",
            "wy_logout": False,
            # 配置页交互临时字段（不落盘）
            "qr_img": "",
            "qr_msg": "",
            "qr_loading": False,
            "login_msg": "",
            "login_loading": False,
            "probe_msg": "",
            "probe_loading": False,
        }

    def get_page(self) -> Optional[List[dict]]:
        """当前插件无独立详情页。"""
        return None

    @staticmethod
    def _col(md: int, component: dict) -> dict:
        """包一层 VCol，减少配置页 JSON 的重复写法。"""
        return {
            'component': 'VCol',
            'props': {'cols': 12, 'md': md},
            'content': [component],
        }

    @staticmethod
    def _switch(model: str, label: str) -> dict:
        """生成一个绑定到配置模型的开关。"""
        return {
            'component': 'VSwitch',
            'props': {
                'model': model,
                'label': label,
            },
        }

    @staticmethod
    def _button(
        text: str,
        handler: str,
        color: str = 'primary',
        loading_model: Optional[str] = None,
    ) -> dict:
        """生成一个点击时执行 ``handler`` 脚本的按钮。

        ``handler`` 在前端表单模型上下文里执行，可直接读写表单字段，
        也可以通过 ``window.MoviePilotAPI`` 调用插件 API。
        """
        props = {
            'color': color,
            'variant': 'tonal',
            'block': True,
            'onClick': handler,
        }
        if loading_model:
            props['loading'] = f'{{{{{loading_model}}}}}'
        return {'component': 'VBtn', 'props': props, 'text': text}

    def _login_blocks(self) -> List[dict]:
        """网易云登录区：登录方式联动显示，操作按钮即时回显结果。"""
        show = {
            'qrcode': "{{login_type === 'qrcode'}}",
            'captcha': "{{login_type === 'captcha'}}",
            'password': "{{login_type === 'password'}}",
            'cookie': "{{login_type === 'cookie'}}",
        }
        return [
            # 登录方式选择 + 保活/退出开关
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VSelect',
                        'props': {
                            'model': 'login_type',
                            'label': '网易云登录方式',
                            'items': [
                                {'title': '扫码登录(推荐)', 'value': 'qrcode'},
                                {'title': '手机号+短信验证码', 'value': 'captcha'},
                                {'title': '手机号/邮箱+密码（风控最严）', 'value': 'password'},
                                {'title': '手动粘贴 Cookie', 'value': 'cookie'},
                            ],
                        },
                    }),
                    self._col(3, self._switch('wy_keepalive', 'Cookie保活(每天)')),
                    self._col(3, self._switch('wy_logout', '退出网易云登录')),
                ],
            },
            # ---- 扫码登录 ----
            {
                'component': 'VRow',
                'props': {'show': show['qrcode']},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'warning',
                                    'variant': 'tonal',
                                    'title': '扫码登录',
                                    'text': '点「获取二维码」直接出码，用网易云音乐 App 扫码'
                                            '并在手机上确认后，点「检查扫码结果」完成登录。'
                                            f'二维码 {self.QRCODE_TTL // 60} 分钟内有效。',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['qrcode']},
                'content': [
                    self._col(6, self._button(
                        '获取二维码', JS_QR_FETCH, loading_model='qr_loading',
                    )),
                    self._col(6, self._button(
                        '检查扫码结果', JS_QR_CHECK, color='success',
                        loading_model='qr_loading',
                    )),
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': "{{login_type === 'qrcode' && qr_img}}"},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VImg',
                                'props': {'src': '{{qr_img}}', 'width': 200, 'height': 200},
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': "{{login_type === 'qrcode' && qr_msg}}"},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '{{qr_msg}}',
                                },
                            }
                        ],
                    }
                ],
            },
            # ---- 短信验证码登录 ----
            {
                'component': 'VRow',
                'props': {'show': show['captcha']},
                'content': [
                    self._col(4, {
                        'component': 'VTextField',
                        'props': {'model': 'wylogin_user', 'label': '手机号'},
                    }),
                    self._col(4, self._button(
                        '发送验证码', JS_CAPTCHA_SEND, color='info',
                    )),
                    self._col(4, {
                        'component': 'VTextField',
                        'props': {'model': 'wylogin_password', 'label': '短信验证码'},
                    }),
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['captcha']},
                'content': [
                    self._col(4, self._button('验证码登录', JS_LOGIN_CAPTCHA)),
                ],
            },
            # ---- 密码登录 ----
            {
                'component': 'VRow',
                'props': {'show': show['password']},
                'content': [
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {'model': 'wylogin_user', 'label': '手机号/邮箱'},
                    }),
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {
                            'model': 'wylogin_password',
                            'label': '密码',
                            'type': 'password',
                        },
                    }),
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['password']},
                'content': [
                    self._col(4, self._button(
                        '密码登录', JS_LOGIN_PASSWORD, color='warning',
                    )),
                ],
            },
            # ---- 手动 Cookie ----
            {
                'component': 'VRow',
                'props': {'show': show['cookie']},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'wylogin_cookie',
                                    'label': '网易云 Cookie',
                                    'rows': 3,
                                    'placeholder': '从浏览器开发者工具复制 music.163.com 的'
                                                   '完整 Cookie，至少包含 MUSIC_U',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['cookie']},
                'content': [
                    self._col(4, self._button('校验并保存 Cookie', JS_LOGIN_COOKIE)),
                ],
            },
            # ---- 操作结果提示（登录/连接测试共用） ----
            {
                'component': 'VRow',
                'props': {'show': '{{login_msg || probe_msg}}'},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '{{login_msg || probe_msg}}',
                                },
                            }
                        ],
                    }
                ],
            },
        ]

    # ------------------------------------------------------------------
    # 登录状态与登录动作
    # ------------------------------------------------------------------

    def _load_login_state(self) -> None:
        """刷新账号状态文案，供配置页展示。"""
        self._username: Optional[str] = None
        try:
            self._username = self.cm.login_status() if self.cm else None
        except Exception as error:  # noqa: BLE001 - 配置页不能因为服务异常打不开
            logger.error(f"获取网易云登录状态失败：{error}")

        if self._username:
            self._wyy_text = f"当前网易云账号「{self._username}」登录成功，可以使用用户相关功能"
        else:
            self._wyy_text = "当前未登录网易云账号，部分功能受限，请按下方登录方式完成登录"

        # ncm-api 连通性只在未配置地址时提示，避免每次打开配置页都发请求
        if not self._ncm_api_url:
            self._ncm_status_text = f"{self._wyy_text}\n尚未填写 ncm-api 服务地址"
        else:
            self._ncm_status_text = f"{self._wyy_text}\nncm-api 地址：{self._ncm_api_url}"

    def _handle_pending_actions(self, config: dict) -> None:
        """执行配置页上的一次性登录动作，并把开关复位。

        沿用 MoviePilot 插件通用的「保存即执行」约定：打开开关并保存配置后
        在这里执行动作，再把开关写回 false 并保存配置。
        """
        actions = {
            "qr_get": self._action_qrcode,
            "qr_check": self._action_qrcode_check,
            "captcha_sent": self._action_captcha_sent,
            "wy_login": self._action_login,
            "wy_logout": self._action_logout,
        }
        triggered = [name for name in actions if config.get(name)]
        if not triggered:
            return

        for name in triggered:
            try:
                actions[name]()
            except Exception as error:  # noqa: BLE001 - 单个动作失败不影响后续
                logger.error(f"执行登录动作 {name} 失败：{error}")

        # 复位开关（同时把当前配置完整写回）
        self._save_config(**{name: False for name in triggered})
        self._load_login_state()

    def _save_config(self, **overrides) -> None:
        """保存插件配置，未显式覆盖的字段保持当前值。"""
        config = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "media_server": self._media_server,
            "exact_match": self._exact_match,
            "ncm_api_url": self._ncm_api_url,
            "login_type": self._login_type,
            "wylogin_user": self._wylogin_user,
            "wylogin_password": self._wylogin_password,
            "wylogin_cookie": self._wylogin_cookie,
            "wymusic_paths": self._wymusic_paths,
            "qqmusic_paths": self._qqmusic_paths,
            "wy_keepalive": self._wy_keepalive,
            "wy_subscribe": self._wy_subscribe,
            "wy_daily_list": self._wy_daily_list,
            "wy_daily_song": self._wy_daily_song,
            "qr_get": False,
            "qr_check": False,
            "captcha_sent": False,
            "wy_login": False,
            "wy_logout": False,
        }
        config.update(overrides)
        self.update_config(config)

    def _qrcode_image(self) -> str:
        """读取未过期的二维码图片（data URL），没有则返回空串。"""
        qrcode = self.get_data(self.QRCODE_DATA_KEY) or {}
        if not qrcode.get("unikey"):
            return ""
        created = qrcode.get("create_time_stamp") or 0
        if time.time() - created > self.QRCODE_TTL:
            return ""
        return qrcode.get("qrimg") or ""

    def _action_qrcode(self) -> None:
        """生成扫码登录二维码并暂存，供配置页展示。"""
        key, image = self.cm.login_qrcode()
        self.save_data(
            self.QRCODE_DATA_KEY,
            {"unikey": key, "qrimg": image, "create_time_stamp": time.time()},
        )
        logger.info("已生成网易云登录二维码，请用网易云音乐 App 扫码，然后打开「检查扫码结果」并保存")

    def _action_qrcode_check(self) -> None:
        """检查扫码结果，授权成功后保存 Cookie。"""
        qrcode = self.get_data(self.QRCODE_DATA_KEY) or {}
        key = qrcode.get("unikey")
        if not key:
            logger.error("没有可用的二维码，请先执行「获取二维码」")
            return
        if time.time() - (qrcode.get("create_time_stamp") or 0) > self.QRCODE_TTL:
            logger.error("二维码已过期，请重新执行「获取二维码」")
            self.del_data(self.QRCODE_DATA_KEY)
            return

        result = self.cm.check_qrcode(key)
        code = result.get("code")
        if code == QR_STATUS_SUCCESS:
            if self.cm.save_cookie(result.get("cookie") or ""):
                logger.info(f"网易云扫码登录成功：{self.cm.login_status() or ''}")
                self.del_data(self.QRCODE_DATA_KEY)
            return
        logger.info(f"网易云扫码状态：{QR_STATUS.get(code, f'未知状态 {code}')}")

    def _action_captcha_sent(self) -> None:
        """发送登录短信验证码。"""
        phone = (self._wylogin_user or "").strip()
        if not phone:
            logger.error("请先填写手机号，再获取短信验证码")
            return
        result = self.cm.send_captcha(phone)
        if result.get("code") == 200:
            logger.info("验证码已发送，请把收到的验证码填入「密码/短信验证码」，再执行「执行登录」")
        else:
            logger.error(
                f"验证码发送失败：{result.get('message') or result.get('msg') or result}"
            )

    def _action_login(self) -> None:
        """按所选登录方式执行登录。"""
        login_type = self._login_type
        if login_type == "qrcode":
            logger.info("扫码登录请使用「获取二维码」与「检查扫码结果」两个开关")
        elif login_type == "captcha":
            if self.cm.login_by_captcha(self._wylogin_user, self._wylogin_password):
                # 验证码是一次性的，用完立即清掉
                self._wylogin_password = ""
        elif login_type == "password":
            self.cm.login_by_password(self._wylogin_user, self._wylogin_password)
        elif login_type == "cookie":
            self.cm.login_by_cookie(self._wylogin_cookie)
        else:
            logger.error(f"未知的登录方式：{login_type}")

    def _action_logout(self) -> None:
        """退出网易云登录。"""
        self.cm.logout()
        self.del_data(self.QRCODE_DATA_KEY)

    # ------------------------------------------------------------------
    # 定时同步
    # ------------------------------------------------------------------

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件公共服务：歌单同步定时任务 + Cookie 保活。"""
        services: List[Dict[str, Any]] = []
        if self._enabled:
            services.append({
                "id": "MusicSubscribe",
                "name": "歌单同步",
                "trigger": CronTrigger.from_crontab(self._cron or "0 7 * * *"),
                "func": self.__run_sync_paylist,
                "kwargs": {},
            })
        # Cookie 保活独立于同步开关：只要求插件启用且登录过
        if self._wy_keepalive and self.cm and self.cm.cookie:
            services.append({
                "id": "MusicSubscribeKeepalive",
                "name": "网易云Cookie保活",
                "trigger": CronTrigger.from_crontab("0 9 * * *"),
                "func": self._keepalive_login,
                "kwargs": {},
            })
        return services

    def _keepalive_login(self) -> None:
        """每天检查一次网易云登录状态，尽量续期 Cookie，失效时给出明确提示。"""
        if not self.cm:
            return
        nickname = self.cm.login_status()
        if nickname:
            # /login/refresh 不支持二维码登录得到的 Cookie，扫码账号只做状态确认
            if self._login_type != "qrcode":
                self.cm.refresh_login()
            logger.info(f"网易云 Cookie 保活完成，当前账号：{nickname}")
            return
        logger.warning("网易云登录态已失效，尝试自动恢复")
        if (
            self._login_type == "password"
            and self._wylogin_user
            and self._wylogin_password
        ):
            if self.cm.login_by_password(self._wylogin_user, self._wylogin_password):
                logger.info(f"网易云已用保存的密码自动重新登录：{self.cm.login_status() or ''}")
                return
        logger.warning(
            "网易云 Cookie 已失效且无法自动恢复，请到插件配置页重新扫码/验证码登录"
            "（验证码登录因验证码一次性无法自动重登）"
        )

    def __run_sync_paylist(self):
        """
        开始同步歌单
        """
        emby_users = []
        if not self._wymusic_paths and not self._qqmusic_paths and not self._username:
            logger.info("同步配置为空,不进行处理。告退......")
            return
        if not self._media_server:
            logger.info("没有可用的媒体服务器,不进行处理。告退......")
            return
        if not self.cm or not self.cm.api.available:
            logger.error("未配置 ncm-api 服务地址，无法同步网易云歌单")
            return

        qq = QQMusicApi()

        # 获取同步列表信息
        qqmusic_paths = self._qqmusic_paths.split("\n") if self._qqmusic_paths else []
        wymusic_paths = self._wymusic_paths.split("\n") if self._wymusic_paths else []

        for name in self._media_server:
            server = self.media_config.get(name)
            if not server:
                continue
            config = server.config
            if server.type == 'plex':
                self.pm = PlexMusic(host=config['host'], token=config['token'])
                self.pm.get_music_library()
                self.pm.get_playlists()
            elif server.type == 'emby':
                self.em = EmbyMusic(host=config['host'], apikey=config['apikey'])
                emby_users = [self.em.default_user]
                logger.info('媒体服务器设置包含Emby服务器')
            else:
                continue

            for path in qqmusic_paths:
                data_list = path.strip().split(':')
                if len(data_list) == 2:
                    qq_play_id, media_playlist = data_list[0], data_list[1]
                elif len(data_list) == 3:
                    qq_play_id, media_playlist, emby_users = data_list[0], data_list[1], data_list[2]
                    emby_users = emby_users.split(',')
                else:
                    logger.warning("QQ音乐歌单同步设置配置不规范,请认真检查修改")
                    return
                if not qq_play_id or not media_playlist:
                    logger.warning("QQ音乐歌单同步设置配置不规范,请认真检查修改")
                    continue
                logger.info(f"QQ歌单id: {qq_play_id}, 媒体库播放列表名称: {media_playlist}")
                qq_tracks = qq.get_playlist_by_id(qq_play_id)
                logger.info(f"QQ歌单 {qq_play_id} 获取歌曲[{len(qq_tracks)}]首,列表为: {qq_tracks}")
                if server.type == 'plex':
                    self.__t_plex(qq_tracks, media_playlist)
                elif server.type == 'emby':
                    logger.info(
                        f"QQ歌单id: {qq_play_id}, 为Emby用户[{emby_users}]更新媒体库播放列表名称: {media_playlist}")
                    self.__t_emby(qq_tracks, media_playlist, emby_users)

            for path in wymusic_paths:
                path = path.strip()
                if not path:
                    continue
                # 汽水音乐分享链接：链接:播放列表名称[:emby用户名]，链接经公共解析服务取歌
                if looks_like_qishui_link(path):
                    self._sync_qishui(path, server, emby_users)
                    continue
                data_list = path.split(':')
                if len(data_list) == 2:
                    wy_play_id, media_playlist = data_list[0], data_list[1]
                elif len(data_list) == 3:
                    wy_play_id, media_playlist, emby_users = data_list[0], data_list[1], data_list[2]
                    emby_users = emby_users.split(',')
                else:
                    logger.warning("网易云歌单同步设置配置不规范,请认真检查修改")
                    return
                logger.info(f"网易云歌单id: {wy_play_id}, 媒体库播放列表名称: {media_playlist}")
                self.cm_emby_plex(wy_play_id, media_playlist, emby_users, server.type)

            if self._username:
                # 每日推荐歌单
                if self._wy_daily_list:
                    try:
                        datas = self.cm.get_list_days()
                        for data in datas:
                            wy_play_id, media_playlist = data[0], data[1]
                            self.cm_emby_plex(wy_play_id, media_playlist, emby_users, server.type)
                    except Exception as e:
                        logger.error(e)
                        logger.error("每日推荐歌单获取失败")
                # 每日歌曲推荐
                if self._wy_daily_song:
                    try:
                        wy_tracks = self.cm.get_song_daily()
                        playlist = "每日歌曲推荐"
                        logger.info(f"网易云歌单 {playlist} 获取歌曲[{len(wy_tracks)}]首,列表为: {wy_tracks}")
                        if server.type == 'plex':
                            self.__t_plex(wy_tracks, playlist)
                        elif server.type == 'emby':
                            logger.info(
                                f"网易云歌单: {wy_tracks}, 为Emby用户{emby_users}更新媒体库播放列表名称: {playlist}")
                            self.__t_emby(wy_tracks, playlist, emby_users)
                    except Exception as e:
                        logger.error(e)
                        logger.error("每日推荐更新失败")
        return

    _QISHUI_LINK_RE = re.compile(r"https?://[^\s:：]+")

    def _add_music_subscribes(self, t_tracks, missing_titles) -> None:
        """把同步时在媒体库里没搜到的歌曲转为 MoviePilot 音乐订阅。

        宿主 V3 提供完整的音乐订阅链路（MusicBrainz 等识别源），这里只负责
        把缺歌信息递给 SubscribeChain；识别失败的音乐记日志跳过，不影响同步。
        """
        if not missing_titles or not self._wy_subscribe:
            return
        try:
            from app.chain.subscribe import SubscribeChain
            from app.schemas.types import MediaType
        except Exception as error:  # noqa: BLE001 - 宿主过旧或音乐链未启用
            logger.warning(f"宿主不支持音乐订阅，跳过转订阅（{error}）")
            return
        # 给识别链多一个线索：标题带上第一位歌手
        artist_map: Dict[str, str] = {}
        for track in t_tracks:
            if track and track[0] in missing_titles and track[0] not in artist_map:
                artists = track[1] if len(track) > 1 and track[1] else []
                artist_map[track[0]] = artists[0] if artists else ""
        chain = SubscribeChain()
        added = exists = failed = 0
        for title in missing_titles:
            keyword = f"{artist_map.get(title, '')} {title}".strip()
            try:
                subscribe_id, message = chain.add(
                    title=keyword,
                    year="",
                    mtype=MediaType.MUSIC,
                    music_type="recording",
                    exist_ok=True,
                    message=False,
                )
            except Exception as error:  # noqa: BLE001 - 单首失败不中断整批
                failed += 1
                logger.warning(f"音乐订阅失败[{keyword}]：{error}")
                continue
            if subscribe_id:
                added += 1
                logger.info(f"音乐订阅成功：{keyword}")
            else:
                exists += 1
                logger.info(f"音乐订阅未新增：{keyword}（{message}）")
        logger.info(
            f"音乐订阅处理完成：新增 {added}，已存在/未识别 {exists}，失败 {failed}")

    def _sync_qishui(self, path, server, emby_users):
        """同步一行汽水音乐歌单配置（链接:播放列表名称[:emby用户名]）。"""
        match = self._QISHUI_LINK_RE.search(path)
        if not match:
            logger.warning(f"汽水音乐配置缺少分享链接：{path}")
            return
        link = match.group(0)
        remainder = path[match.end():].strip()
        media_playlist, _, user_part = remainder.lstrip(':：').partition(':')
        media_playlist = media_playlist.strip()
        users = [u.strip() for u in user_part.split(',') if u.strip()] if user_part else emby_users
        try:
            playlist_name, tracks = QishuiClient().parse_playlist(link)
        except QishuiError as error:
            logger.error(f"汽水音乐歌单解析失败：{error}")
            return
        media_playlist = media_playlist or playlist_name
        logger.info(
            f"汽水音乐歌单[{playlist_name}]解析到歌曲[{len(tracks)}]首，"
            f"目标播放列表: {media_playlist}")
        if server.type == 'plex':
            self.__t_plex(tracks, media_playlist)
        elif server.type == 'emby':
            self.__t_emby(tracks, media_playlist, users)

    def cm_emby_plex(self, wy_play_id, media_playlist, emby_users, media_type):
        """把单份网易云歌单同步到当前媒体服务器。"""
        if not (wy_play_id and media_playlist):
            logger.warning("网易云音乐歌单同步设置配置不规范,请认真检查修改")
            return
        wy_tracks = self.cm.songofplaylist(wy_play_id)
        if not wy_tracks:
            logger.error("网易云歌单获取失败，请检查 ncm-api 与登录状态")
            return
        logger.info(f"网易云歌单 {wy_play_id} 获取歌曲[{len(wy_tracks)}]首,列表为: {wy_tracks}")
        if media_type == 'plex':
            self.__t_plex(wy_tracks, media_playlist)
        elif media_type == 'emby':
            logger.info(
                f"网易云歌单: {wy_tracks}, 为Emby用户{emby_users}更新媒体库播放列表名称: {media_playlist}")
            self.__t_emby(wy_tracks, media_playlist, emby_users)

    def __t_emby(self, t_tracks, media_playlist, emby_users=None):
        """同步歌曲到 Emby 播放列表，并处理多用户共享。"""
        em = self.em
        if emby_users is None:
            emby_users = [em.default_user]
        one_user = emby_users[0]
        other_users = emby_users[1:]
        em.user = em.get_user(one_user)
        em.get_music_library()
        logger.info("Emby开始同步歌单,涉及搜索时间较长请耐心等待.......")
        playlist_id, music_ids, music_names = em.get_tracks_by_playlist(media_playlist)
        logger.info(f"Emby歌单[{media_playlist}]现有歌曲[{len(music_names)}]首,列表为: {music_names}")
        if music_names:
            new_tracks = [i for i in t_tracks if i[0] not in music_names]
        else:
            new_tracks = t_tracks
        tracks = em.mul_search_music(new_tracks, self._exact_match)
        if playlist_id:
            ids = [i for i in tracks if i not in music_ids]
            em.set_tracks_to_playlist(playlist_id, ','.join(ids))
        else:
            em.create_playlist(media_playlist, ','.join(tracks))
        _, final_ids, final_names = em.get_tracks_by_playlist(media_playlist)
        missing = [i[0] for i in t_tracks if i[0] not in set(final_names or [])]
        self._add_music_subscribes(t_tracks, missing)
        for user in other_users:
            em.user = em.get_user(user)
            em.get_music_library()
            user_playlist_id, user_music_ids, _ = em.get_tracks_by_playlist(media_playlist)
            if user_playlist_id:
                new_ids = [i for i in final_ids if i not in user_music_ids]
                em.set_tracks_to_playlist(user_playlist_id, ','.join(new_ids), user)
            else:
                em.create_playlist(media_playlist, ','.join(final_ids), user)

        logger.info("Emby同步歌单完成,感谢耐心等待.......")
        logger.info("歌单同步完成，END")
        return

    def __t_plex(self, t_tracks, media_playlist):
        """同步歌曲到 Plex 播放列表。"""
        pm = self.pm
        logger.info("Plex开始同步歌单,涉及搜索时间较长请耐心等待.......")
        add_tracks = []
        old_tracks = []
        plex_tracks = pm.get_tracks_by_playlist(media_playlist)
        logger.debug(f"plex播放列表 [{media_playlist}] 已存在歌曲[{len(plex_tracks)}]首,列表为: {plex_tracks}")
        # 查找获取tracks
        for t_track in t_tracks:
            if t_track[0] in plex_tracks:
                old_tracks.append(t_track)
                continue
            try:
                tracks = pm.search_music(t_track, self._exact_match)
            except Exception as e:
                logger.error(f"搜索歌曲失败,err:{e}")
                tracks = []
            add_tracks += tracks
        # 按 ratingKey 去重，避免同一首歌被重复添加
        add_tracks = list({
            getattr(item, "ratingKey", id(item)): item for item in add_tracks
        }.values())
        no_list = list(set(i[0] for i in t_tracks) - set([i.title for i in add_tracks]) - set(i[0] for i in old_tracks))
        logger.info(f"Plex库中未搜到歌曲[{len(no_list)}]首,列表为: {no_list}")
        self._add_music_subscribes(t_tracks, no_list)
        # 有歌曲写入没有就跳过
        if len(add_tracks) > 0:
            if len(plex_tracks) < 1:
                try:
                    # 创建如果存在创建失败就进行添加
                    pm.create_playlist(media_playlist, add_tracks)
                    logger.info(f"Plex创建播放列表[{media_playlist}]成功，并添加歌曲[{len(add_tracks)}]首,列表为: {[i.title for i in add_tracks]}")
                except Exception as err:
                    logger.error(f"{err}")
            else:
                try:
                    pm.set_tracks_to_playlist(media_playlist, add_tracks)
                    logger.info(f"Plex向播放列表[{media_playlist}]添加歌曲[{len(add_tracks)}]首,列表为: {[i.title for i in add_tracks]}成功")
                except Exception as e:
                    logger.error(f"{e}")
        else:
            if len(old_tracks) == len(t_tracks):
                logger.info("Plex歌单全部同步，无需再次同步")
            else:
                logger.info("Plex歌单同步完成，有部分歌曲没有查询到，请查看日志")
        logger.info("Plex同步歌单完成,感谢耐心等待.......")
        return

    def stop_service(self):
        """退出插件：释放自建的调度器和运行时对象。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出歌单同步服务失败：{e}")
        finally:
            self.pm = None
            self.em = None
