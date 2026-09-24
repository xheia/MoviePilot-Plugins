"""外部歌单接口的请求节流。

公开歌单接口（QQ音乐 ``musicu.fcg``、PlaylistOut 解析服务等）都有调用频率限制，
超了会被直接拒或返回异常结构。这里提供一个最小的节流器：同一个节流器内，相邻
两次请求至少间隔 ``interval`` 秒，多等的那点时间远比被限流后整轮失败划算。
"""

from __future__ import annotations

import time
from threading import Lock


class Throttle:
    """相邻请求的最小间隔控制。

    加锁是必要的：插件的定时同步与手动「立即运行一次」可能在同一个进程里并发触发，
    而限速是**接口维度**的，不是单次同步维度。
    """

    def __init__(self, interval: float) -> None:
        """
        :param interval: 两次请求之间的最小间隔（秒）；<= 0 表示不限速。
        """
        self.interval = max(0.0, float(interval or 0.0))
        self._lock = Lock()
        self._last = 0.0

    def wait(self) -> float:
        """阻塞到可以发起下一次请求。

        :return: 实际等待的秒数（未等待则为 0），便于调用方记录日志。
        """
        if self.interval <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()
            return max(0.0, delay)
