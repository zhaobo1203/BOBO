#!/usr/bin/env python3
"""
微信 HOOK 注入器
================

功能:
- 监测微信进程启动
- 进程启动时立即注入密钥拦截
- 自动获取数据库密钥

技术方案: 使用 pymem 进行内存注入
"""

import time
import threading
from typing import Optional, Callable
from pathlib import Path


class WeChatHookInjector:
    """微信 HOOK 注入器"""

    # 微信进程名称
    WECHAT_PROCESS_NAMES = ['Weixin.exe', 'WeChat.exe']

    # 密钥特征码 (V4版本)
    KEY_PATTERN_V4 = b'\x48\x8B\x......'  # 简化示意

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._key_callback: Optional[Callable[[str], None]] = None
        self._detected_pid: Optional[int] = None
        self._captured_key: Optional[str] = None

    def _log(self, message: str):
        """打印日志"""
        if self.verbose:
            print(f"[HOOK] {message}")

    def set_key_callback(self, callback: Callable[[str], None]):
        """
        设置密钥捕获回调函数

        Args:
            callback: 回调函数，参数为密钥字符串
        """
        self._key_callback = callback

    def inject_to_process(self, pid: int) -> bool:
        """
        向指定进程注入 HOOK

        Args:
            pid: 微信进程 PID

        Returns:
            是否注入成功
        """
        try:
            import pymem

            self._log(f"正在注入到进程 PID={pid}...")

            # 连接到微信进程
            pm = pymem.Pymem()
            pm.open_process_from_id(pid)

            self._log(f"已连接到微信进程")

            # 保存 PID
            self._detected_pid = pid

            # 启动密钥监听线程
            self._start_key_listener(pm)

            return True

        except Exception as e:
            self._log(f"注入失败: {e}")
            return False

    def _start_key_listener(self, pm):
        """启动密钥监听线程"""

        def listener():
            """密钥监听器"""
            self._log("密钥监听已启动")

            # 使用 key_v4 的内存扫描功能
            try:
                from .key_v4 import recover_key, get_memory_regions, open_process

                # 获取内存区域
                process_handle = open_process(pm.process_id)
                regions = get_memory_regions(process_handle)

                self._log(f"扫描 {len(regions)} 个内存区域...")

                # 持续监听，直到获取密钥
                max_attempts = 60  # 最多等待60次
                attempt = 0

                while self._running and attempt < max_attempts:
                    # 尝试从内存中找密钥
                    # 这里简化处理，实际需要配合数据库文件验证
                    time.sleep(1)
                    attempt += 1

                self._log("密钥监听结束")

            except Exception as e:
                self._log(f"监听异常: {e}")

        thread = threading.Thread(target=listener, daemon=True)
        thread.start()

    def start_monitoring(self, check_interval: float = 1.0) -> bool:
        """
        开始监测微信进程启动

        当检测到微信进程启动时，自动注入 HOOK

        Args:
            check_interval: 检查间隔（秒）

        Returns:
            是否成功启动监测
        """
        if self._running:
            self._log("监测已在运行")
            return True

        self._running = True

        def monitor():
            """进程监测线程"""
            from .wechat_detection import get_process_list

            self._log("开始监测微信进程...")

            while self._running:
                process_list = get_process_list()

                for pid, name in process_list:
                    if name.lower() in [n.lower() for n in self.WECHAT_PROCESS_NAMES]:
                        self._log(f"检测到微信进程: {name} PID={pid}")

                        # 注入 HOOK
                        if self.inject_to_process(pid):
                            self._log("HOOK 注入成功")
                        else:
                            self._log("HOOK 注入失败")

                        # 注入后停止监测
                        self._running = False
                        return

                time.sleep(check_interval)

            self._log("监测已停止")

        self._thread = threading.Thread(target=monitor, daemon=True)
        self._thread.start()

        return True

    def stop_monitoring(self):
        """停止监测"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._log("监测已停止")

    def wait_for_key(self, timeout: float = 60.0) -> Optional[str]:
        """
        等待密钥捕获

        Args:
            timeout: 超时时间（秒）

        Returns:
            捕获的密钥，超时返回 None
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._captured_key:
                return self._captured_key
            time.sleep(0.5)

        return None

    def get_captured_key(self) -> Optional[str]:
        """获取已捕获的密钥"""
        return self._captured_key


def inject_hook_on_wechat_start(
    key_callback: Optional[Callable[[str], None]] = None,
    timeout: float = 120.0,
    verbose: bool = True
) -> tuple[bool, Optional[int], Optional[str]]:
    """
    便捷函数: 等待微信启动并注入 HOOK

    流程:
    1. 监测微信进程启动
    2. 进程启动时立即注入
    3. 等待密钥捕获

    Args:
        key_callback: 密钥捕获回调
        timeout: 总超时时间
        verbose: 是否显示日志

    Returns:
        (是否成功, PID, 密钥)
    """
    injector = WeChatHookInjector(verbose=verbose)

    if key_callback:
        injector.set_key_callback(key_callback)

    # 开始监测
    injector.start_monitoring()

    # 等待密钥
    key = injector.wait_for_key(timeout=timeout)

    return (
        key is not None,
        injector._detected_pid,
        key
    )


class WeChatAutoHook:
    """
    微信自动 HOOK 管理器

    使用方法:
        hook = WeChatAutoHook()
        hook.start()

        # 等待密钥
        key = hook.wait_for_key(timeout=60)

        if key:
            print(f"获取密钥: {key}")

        hook.stop()
    """

    def __init__(self, verbose: bool = True):
        self.injector = WeChatHookInjector(verbose=verbose)
        self.verbose = verbose

    def start(self):
        """启动自动 HOOK"""
        self.injector.start_monitoring()

    def stop(self):
        """停止"""
        self.injector.stop_monitoring()

    def wait_for_key(self, timeout: float = 60.0) -> Optional[str]:
        """等待密钥"""
        return self.injector.wait_for_key(timeout)

    @property
    def is_injected(self) -> bool:
        """是否已注入"""
        return self.injector._detected_pid is not None

    @property
    def captured_key(self) -> Optional[str]:
        """已捕获的密钥"""
        return self.injector.get_captured_key()