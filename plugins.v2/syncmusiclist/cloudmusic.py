
import re
import time


from app.log import logger
from app.plugins.syncmusiclist.netcloudmusic import NeteaseCloudMusicApi
from app.plugins.syncmusiclist.utils import change_str, sub_str


class CloudMusic(object):
    def __init__(self, path=None):
        self.music_api = NeteaseCloudMusicApi(path=path)  # 初始化API
        version_result = self.music_api.request("inner_version")
        logger.info(f'当前使用NeteaseCloudMusicApi版本号：{version_result["NeteaseCloudMusicApi"]}\n'
                    f'当前使用NeteaseCloudMusicApi_V8版本号：{version_result["NeteaseCloudMusicApi_V8"]}')

    def login_status(self):
        """账户登录状态"""
        try:
            if not self.music_api.cookie:
                return None
            response = self.music_api.request("/login/status")
            if response['data']['data']["code"] == 200:
                try:
                    nickname = response["data"]["data"]["profile"]["nickname"]
                    logger.info(f'当前登录账号：{nickname}')
                except:
                    nickname = None
                return nickname
            else:
                return None
        except:
            return None

    def captcha_sent(self, _phone):
        """发送手机验证码"""
        try:
            response = self.music_api.request("/captcha/sent", {"phone": f"{_phone}"})
            if response.get("code") == 200:
                logger.info(f'验证码已发送至手机号：{_phone}')
            else:
                logger.error(f'验证码发送失败：{response.get("message", "未知错误")}')
            return response
        except Exception as e:
            logger.error(f'发送验证码异常：{str(e)}')
            return {"code": -1, "message": f"发送验证码异常：{str(e)}"}

    def captcha_verify(self, _phone, _captcha):
        """验证验证码是否正确"""
        try:
            response = self.music_api.request("/captcha/verify", {"phone": f"{_phone}", "captcha": f"{_captcha}"})
            if response.get("code") == 200:
                logger.info('验证码验证成功')
            else:
                logger.error(f'验证码验证失败：{response.get("message", "未知错误")}')
            return response
        except Exception as e:
            logger.error(f'验证码验证异常：{str(e)}')
            return {"code": -1, "message": f"验证码验证异常：{str(e)}"}

    def login_cellphone(self, _phone, _captcha):
        """手机号验证码登录"""
        try:
            response = self.music_api.request("/login/cellphone", {"phone": f"{_phone}", "captcha": f"{_captcha}"})
            if response.get("code") == 200:
                try:
                    nickname = response.get("data", {}).get("profile", {}).get("nickname")
                    logger.info(f'验证码登录成功，用户：{nickname}')
                except:
                    logger.info('验证码登录成功')
            else:
                logger.error(f'验证码登录失败：{response.get("message", "未知错误")}')
            return response
        except Exception as e:
            logger.error(f'验证码登录异常：{str(e)}')
            return {"code": -1, "message": f"验证码登录异常：{str(e)}"}


    def login(self, username, password):
        """
        使用账号密码登录到网易云音乐
        支持手机号登录和邮箱登录

        调用登录接口后，会自动设置cookie，如果cookie失效，需要重新登录
        登录过后api会在当前工作目录下创建cookie_storage文件保存你的cookie
        在下次调用运行程序时，它会判断cookie是否过期，没有过期就自动读取cookie_storage文件中的cookie

        总的来说你不需要手动管理cookie，只需要调用登录接口，然后调用其他接口即可
        cookie会自动设置，如果cookie过期，再次调用登录接口就好
        更好的办法是，在cookie还没有失效之前使用refresh_login接口刷新cookie

        Args:
            username: 用户名（手机号或邮箱）
            password: 密码

        Returns:
            dict: 登录结果
        """
        try:
            # 检查是否已登录
            if self.music_api.cookie:
                nickname = self.login_status()
                if nickname:
                    logger.info(f'当前已登录，用户：{nickname}')
                    return {"code": 200, "message": "已登录"}

            # 执行登录
            if username.isdigit():
                logger.info(f'使用手机号登录：{username}')
                response = self.music_api.request("/login/cellphone",
                                                  {"phone": f"{username}", "password": f"{password}"})
            else:
                logger.info(f'使用邮箱登录：{username}')
                response = self.music_api.request("/login",
                                                  {"email": f"{username}", "password": f"{password}"})

            if response.get("code") == 200:
                try:
                    nickname = response.get("data", {}).get("profile", {}).get("nickname", "未知用户")
                    logger.info(f'登录成功，欢迎用户：{nickname}')
                except:
                    logger.info('登录成功')

                if self.music_api.cookie:
                    logger.info('cookie已缓存')
            else:
                logger.error(f'登录失败：{response.get("message", "未知错误")}')

            return response

        except Exception as e:
            logger.error(f'登录异常：{str(e)}')
            return {"code": -1, "message": f"登录异常：{str(e)}"}

    def login_with_captcha(self, phone, captcha):
        """
        使用手机号和验证码登录
        这是login_cellphone的包装方法，提供更清晰的接口

        Args:
            phone: 手机号
            captcha: 验证码

        Returns:
            dict: 登录结果
        """
        return self.login_cellphone(phone, captcha)

    def logout(self):
        """
        退出登录
        清除本地缓存的cookie
        """
        try:
            # 调用退出登录接口
            response = self.music_api.request("/logout")

            # 清除本地cookie
            if hasattr(self.music_api, '_NeteaseCloudMusicApi__cookie'):
                self.music_api._NeteaseCloudMusicApi__cookie = ""

            # 尝试删除cookie存储文件
            import os
            cookie_path = str(self.music_api.path / "cookie_storage") if self.music_api.path else "cookie_storage"
            if os.path.exists(cookie_path):
                os.remove(cookie_path)
                logger.info('已清除本地cookie文件')

            logger.info('退出登录成功')
            return response

        except Exception as e:
            logger.error(f'退出登录异常：{str(e)}')
            return {"code": -1, "message": f"退出登录异常：{str(e)}"}

    def refresh_login(self):
        """
        刷新登录状态
        使用cookie刷新登录状态，延长cookie有效期
        建议在每次启动程序时调用此方法

        Returns:
            dict: 刷新结果
        """
        try:
            if not self.music_api.cookie:
                logger.warning('未找到cookie，无法刷新登录状态')
                return {"code": -1, "message": "未找到cookie"}

            response = self.music_api.request("/login/refresh")

            if response.get("code") == 200:
                logger.info('刷新登录状态成功')
            else:
                logger.error(f'刷新登录状态失败：{response.get("message", "未知错误")}')

            return response

        except Exception as e:
            logger.error(f'刷新登录状态异常：{str(e)}')
            return {"code": -1, "message": f"刷新登录状态异常：{str(e)}"}

    def re_login(self, username, password):
        """
        重新登录
        先退出登录，再重新登录
        用于解决cookie失效或其他登录问题

        Args:
            username: 用户名
            password: 密码

        Returns:
            dict: 登录结果
        """
        logger.info('开始重新登录...')
        self.logout()
        return self.login(username, password)

    def signin(self):
        """网易云签到"""
        res = self.music_api.request("/daily_signin")
        return res

    def get_list_days(self, nums=5):
        """每日推荐歌单"""
        res = self.music_api.request("/recommend/resource")
        recommend = res.get('data', {}).get('recommend', [])
        res = [[i.get("id"), i.get("name")] for i in recommend[:nums] if i.get("id")]
        return res

    def get_song_daily(self):
        """每日推荐歌曲"""
        res = self.music_api.request("/recommend/songs")
        dailySongs = res['data']['data']['dailySongs']
        track_names = []
        for i in dailySongs:
            # 正则处理
            name = sub_str(i.get('name'))
            # 多歌手处理
            ars = [change_str(ar.get('name')) for ar in i.get('ar')]
            track_names.append([name, ars])
        return track_names


    def playlist(self, uid):
        """
        歌单
        Full request URI: http://music.163.com/api/playlist/detail?id=37880978&updateTime=-1
        GET http://music.163.com/api/playlist/detail
        必要参数：
            id：歌单ID
        """
        res = self.music_api.request(f"/playlist/track/all", {"id": f"{uid}"})
        return res.get('data', {}).get('songs')

    def playlist_anonymous(self, uid):
        """
        免登录模式获取歌单信息
        直接调用网易云公开API，无需登录即可获取歌单歌曲列表
        :param uid: 歌单ID
        :return: 歌单信息字典，包含歌单名称、描述、歌曲列表等
        """
        try:
            import requests
            import json

            # 使用公开API获取歌单详情
            url = f'https://music.163.com/api/v1/playlist/detail?id={uid}'
            headers = {
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'referer': 'https://music.163.com/'
            }

            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                result = r.json()
                if result.get("code") == 200:
                    playlist_data = result.get("playlist", {})
                    playlist_name = playlist_data.get("name", "未知歌单")
                    playlist_desc = playlist_data.get("description", "")

                    logger.info(f'成功获取歌单：{playlist_name}')

                    # 获取歌曲ID列表
                    track_ids = [track.get("id") for track in playlist_data.get("trackIds", [])]

                    # 分批获取歌曲详情（每次最多50首）
                    songs = []
                    for i in range(0, len(track_ids), 50):
                        batch_ids = track_ids[i:i+50]
                        songs_url = f'https://music.163.com/api/song/detail/?id=&ids={json.dumps(batch_ids)}'
                        songs_r = requests.get(songs_url, headers=headers, timeout=10)
                        if songs_r.status_code == 200:
                            songs_result = songs_r.json()
                            if songs_result.get("code") == 200:
                                songs.extend(songs_result.get("songs", []))

                    return {
                        "name": playlist_name,
                        "description": playlist_desc,
                        "songs": songs,
                        "track_count": len(songs)
                    }
                else:
                    logger.error(f'获取歌单失败：{result.get("message", "未知错误")}')
            else:
                logger.error(f'HTTP请求失败，状态码：{r.status_code}')

        except Exception as e:
            logger.error(f'免登录获取歌单异常：{str(e)}')

        return None

    def songofplaylist_anonymous(self, uid):
        """
        免登录模式获取歌单中的歌曲列表（返回格式与songofplaylist一致）
        :param uid: 歌单ID
        :return: [[歌曲名, [歌手列表]], ...] 格式的歌曲列表
        """
        playlist_info = self.playlist_anonymous(uid)

        if not playlist_info:
            return []

        tracks = playlist_info.get("songs", [])
        track_names = []

        for song in tracks:
            # 正则处理歌曲名
            name = sub_str(song.get('name'))

            # 多歌手处理
            ars = [change_str(ar.get('name')) for ar in song.get('ar', [])]
            track_names.append([name, ars])

        logger.info(f'免登录模式获取到 {len(track_names)} 首歌曲')
        return track_names
    
    def songofplaylist(self, uid):
        """
        获取歌单中歌曲
        """
        tracks = []
        # 循环进行重试
        # 设置最大重试次数
        max_retry_times = 5
        # 当前重试次数
        retry_times = 0
        while retry_times < max_retry_times:
            try:
                tracks = self.playlist(uid)
                break  # 如果成功执行，跳出循环
            except Exception as e:
                logger.warn(f"第 {retry_times + 1} 次重试失败：获取歌单错误")
                retry_times += 1
                time.sleep(2)  # 添加延时
        track_names = []
        for i in tracks:
            # 正则处理
            name = sub_str(i.get('name'))
            # 多歌手处理
            ars = [change_str(ar.get('name')) for ar in i.get('ar')]
            track_names.append([name, ars])
        return track_names


if __name__ == '__main__':
    cm = CloudMusic()

    # ===== 登录功能演示 =====
    print("=" * 60)
    print("网易云音乐登录功能演示")
    print("=" * 60)

    # 检查登录状态
    print("\n【1. 检查登录状态】")
    status = cm.login_status()
    if status:
        print(f"当前已登录：{status}")
    else:
        print("当前未登录")

    # 方式1：使用账号密码登录（需要配置真实账号）
    print("\n【2. 账号密码登录（可选）】")
    # response = cm.login("your_email@example.com", "your_password")
    # print(f"登录结果：{response.get('code')} - {response.get('message')}")

    # 方式2：使用手机号+验证码登录
    print("\n【3. 手机号验证码登录流程】")
    print("步骤1：发送验证码")
    # phone = "13800138000"
    # response = cm.captcha_sent(phone)
    # print(f"发送验证码结果：{response.get('message')}")

    print("\n步骤2：输入验证码登录")
    # captcha = "1234"
    # response = cm.login_with_captcha(phone, captcha)
    # print(f"登录结果：{response.get('message')}")

    # 方式3：刷新登录状态（如果已登录）
    print("\n【4. 刷新登录状态（延长cookie有效期）】")
    # response = cm.refresh_login()
    # print(f"刷新结果：{response.get('message')}")

    # 方式4：重新登录
    print("\n【5. 重新登录】")
    # response = cm.re_login("your_email@example.com", "your_password")
    # print(f"重新登录结果：{response.get('message')}")

    # 方式5：退出登录
    print("\n【6. 退出登录】")
    # response = cm.logout()
    # print(f"退出登录结果：{response.get('message')}")

    # ===== 需要登录的功能演示 =====
    print("\n" + "=" * 60)
    print("需要登录的功能演示")
    print("=" * 60)

    # 签到
    print("\n【1. 网易云签到】")
    # signin_result = cm.signin()
    # print(f"签到结果：{signin_result}")

    # 每日推荐歌曲
    print("\n【2. 获取每日推荐歌曲】")
    # res_s = cm.get_song_daily()
    # print(f"每日推荐歌曲数量：{len(res_s)}")
    # for i, (name, artists) in enumerate(res_s[:5], 1):
    #     print(f"  {i}. {name} - {', '.join(artists)}")

    # 获取歌单（登录模式）
    print("\n【3. 获取歌单（登录模式）】")
    # res = cm.songofplaylist("365436873")
    # print(f"歌曲数量：{len(res)}")

    # ===== 免登录模式演示 =====
    print("\n" + "=" * 60)
    print("免登录模式演示（无需登录即可使用）")
    print("=" * 60)

    playlist_id = "365436873"  # 测试歌单ID
    print(f"\n【免登录获取歌单：{playlist_id}】")

    playlist_info = cm.playlist_anonymous(playlist_id)

    if playlist_info:
        print(f"歌单名称：{playlist_info['name']}")
        print(f"歌曲数量：{playlist_info['track_count']}")
        print(f"歌单描述：{playlist_info.get('description', '无')[:80]}...")

        songs = cm.songofplaylist_anonymous(playlist_id)
        print(f"\n前5首歌曲：")
        for i, (name, artists) in enumerate(songs[:5], 1):
            print(f"  {i}. {name} - {', '.join(artists)}")
    else:
        print("获取歌单失败")

    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)
    print("\n使用说明：")
    print("1. 免登录模式：可直接获取公开歌单，无需登录")
    print("2. 登录模式：需要登录后才能使用的功能（签到、每日推荐等）")
    print("3. 登录方式：支持账号密码登录和手机号验证码登录")
    print("4. Cookie管理：自动缓存cookie，支持刷新登录状态")
    print("=" * 60)


