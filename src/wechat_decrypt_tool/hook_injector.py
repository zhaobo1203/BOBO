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

    # 密钥特征码 (V4版本) - 需要根据实际微信版本更新
    KEY_PATTERN_V4 = b''  # Placeholder, actual pattern TBD

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
            
            # 确保 running 标志为 True（监听线程需要）
            self._running = True
            
            # 保存进程对象
            self._pm = pm

            # 启动密钥监听线程
            self._start_key_listener(pm)

            return True

        except Exception as e:
            self._log(f"注入失败: {e}")
            return False
    
    def start_and_hook(self, wechat_exe: str) -> bool:
        """
        启动微信并注入 Hook（参考 simple_monitor.py 的流程）
        
        Args:
            wechat_exe: 微信可执行文件路径
            
        Returns:
            是否成功启动并注入
        """
        import subprocess
        import psutil
        
        try:
            self._log(f"启动微信: {wechat_exe}")
            
            # 启动微信进程
            process = subprocess.Popen([wechat_exe])
            time.sleep(2)  # 等待微信初始化
            
            # 查找微信主进程
            target_pid = None
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = proc.info.get('name', '')
                    if name.lower() in ['weixin.exe', 'wechat.exe']:
                        cmdline = proc.info.get('cmdline') or []
                        cmdline_str = ' '.join(cmdline).lower()
                        # 选择命令行最短的作为主进程
                        if target_pid is None:
                            target_pid = proc.info['pid']
                        self._log(f"找到微信进程: PID={proc.info['pid']} name={name}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if not target_pid:
                target_pid = process.pid
                self._log(f"使用启动进程 PID: {target_pid}")
            
            self._detected_pid = target_pid
            self._running = True
            
            # 连接到微信进程
            import pymem
            pm = pymem.Pymem()
            pm.open_process_from_id(target_pid)
            self._pm = pm
            
            self._log(f"已连接到微信进程 PID={target_pid}")
            
            # 启动密钥监听线程
            self._start_key_listener(pm)
            
            return True
            
        except Exception as e:
            self._log(f"启动并注入失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _start_key_listener(self, pm):
        """启动密钥监听线程 - 使用 wx_key Hook方式"""

        def listener():
            """密钥监听器"""
            self._log("密钥监听已启动 (wx_key Hook模式)")

            try:
                # 尝试导入 wx_key 模块
                try:
                    import wx_key
                except ImportError:
                    self._log("wx_key 模块未安装，无法使用Hook方式")
                    self._log("请安装 wx_key 模块或使用 simple_monitor.py")
                    return

                # 初始化 Hook
                pid = pm.process_id
                self._log(f"初始化 Hook (PID={pid})...")
                
                try:
                    if not wx_key.initialize_hook(pid):
                        err = wx_key.get_last_error_msg()
                        self._log(f"Hook 初始化失败: {err}")
                        return
                except Exception as hook_err:
                    self._log(f"Hook 初始化异常: {hook_err}")
                    return

                self._log("Hook 初始化成功，等待微信登录获取密钥...")

                start_time = time.time()
                timeout = 60.0  # 60秒超时

                try:
                    while self._running and (time.time() - start_time) < timeout:
                        # 轮询密钥数据
                        try:
                            key_data = wx_key.poll_key_data()
                        except Exception as poll_err:
                            self._log(f"poll_key_data 错误: {poll_err}")
                            time.sleep(0.1)
                            continue
                        
                        if key_data and 'key' in key_data:
                            key = key_data['key']
                            if key and len(str(key)) == 64:
                                self._captured_key = str(key).lower()
                                self._log(f"成功获取密钥: {self._captured_key[:16]}...")
                                
                                # 调用回调
                                if self._key_callback:
                                    self._key_callback(self._captured_key)
                                break
                        
                        # 检查状态消息
                        try:
                            while True:
                                msg, level = wx_key.get_status_message()
                                if msg is None:
                                    break
                                if level == 2:  # 错误级别
                                    self._log(f"[Hook Error] {msg}")
                                elif level == 1:  # 警告级别
                                    self._log(f"[Hook Warn] {msg}")
                        except Exception:
                            pass
                        
                        time.sleep(0.1)
                    
                    if not self._captured_key:
                        elapsed = time.time() - start_time
                        self._log(f"密钥获取超时 ({elapsed:.1f}秒)")
                        self._log("提示：请在微信中完成登录（扫码或点击登录）")

                finally:
                    self._log("清理 Hook...")
                    try:
                        wx_key.cleanup_hook()
                    except Exception:
                        pass

                self._log("密钥监听结束")

            except Exception as e:
                self._log(f"监听异常: {e}")
                import traceback
                traceback.print_exc()

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