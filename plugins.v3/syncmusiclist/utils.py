"""歌单同步工具使用的文本处理与 Cookie 解析函数。"""

import re


def sub_str(text):
    """去掉歌曲名、歌手名中的括号注释。

    例如「雨蝶 (Live)」「雨蝶 (《还珠格格》片尾曲)」都会被还原为「雨蝶」。
    """
    if not text:
        return ""
    return re.sub(r'\s*[\(\（\[【<《][^\)\）\]】>》]*[\)\）\]】>》]\s*', '', text)


def contains_chinese(text):
    """判断字符串是否包含中文字符。"""
    pattern = re.compile(r'[\u4e00-\u9fa5]')
    return bool(pattern.search(text or ""))


def extract_chinese(text):
    """提取字符串中的第一段连续中文字符，没有则返回空串。"""
    pattern = re.compile(r'[\u4e00-\u9fa5]+')
    match = pattern.findall(text or "")
    return match[0] if match else ""


def change_str(text):
    """规范化歌手名：先去括号注释，含中文时只保留中文部分。

    媒体服务器里「刘君 (Luna)」这类写法匹配不上，这里统一收紧成中文名。
    """
    text = sub_str(text)
    if contains_chinese(text):
        text = extract_chinese(text)
    return text


def parse_cookie_str(cookie_str):
    """把 Cookie 字符串解析成字典。

    只保留 ``name=value`` 形式，忽略 Path、Domain 等属性；取值不做 URL 解码，
    交给 ncm-api 侧按网易云的规则处理。
    """
    cookies = {}
    for item in (cookie_str or "").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def is_valid_cookie(cookie_str):
    """判断用户提供的 Cookie 是否像一份有效的网易云登录凭证。

    新版接口以 ``MUSIC_U`` 为准，老客户端 Cookie 则带 ``MUSIC_A_T`` /
    ``MUSIC_R_T``，三者命中其一即可继续交给 ncm-api 校验。
    """
    cookies = parse_cookie_str(cookie_str)
    return any(key in cookies for key in ("MUSIC_U", "MUSIC_A_T", "MUSIC_R_T"))
