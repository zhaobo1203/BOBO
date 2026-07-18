"""TN-01: 微信进程管理模块

功能：
- 检测微信进程是否运行
- 终止所有微信进程
- 从注册表检测微信安装路径
- 启动微信客户端
"""

import os
import psutil
import winreg
import subprocess
import time
from typing import List, Dict, Optional


def detect_wechat_process() -> List[Dict]:
    """检测微信进程
    
    Returns:
        list: 进程列表，每个元素包含 pid, name, exe
    """
    processes = []
    for p in psutil.process_iter(['name', 'pid', 'exe']):
        try:
            name = p.info['name'].lower() if p.info['name'] else ''
            if name in ['weixin.exe', 'wechat.exe']:
                processes.append({
                    'pid': p.info['pid'],
                    'name': p.info['name'],
                    'exe': p.info['exe']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return processes


def kill_wechat_processes() -> int:
    """终止所有微信进程
    
    Returns:
        int: 终止的进程数量
    """
    killed_count = 0
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name'].lower() if proc.info['name'] else ''
            if name in ['weixin.exe', 'wechat.exe']:
                proc.terminate()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    # 等待进程终止
    time.sleep(2)
    
    # 检查是否还有残留进程
    remaining = detect_wechat_process()
    if remaining:
        # 强制终止
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = proc.info['name'].lower() if proc.info['name'] else ''
                if name in ['weixin.exe', 'wechat.exe']:
                    proc.kill()
            except:
                pass
    
    return killed_count


def detect_wechat_installation() -> Dict:
    """从注册表检测微信安装路径
    
    Returns:
        dict: 包含 wechat_exe_path 的字典，失败返回空字典
    """
    registry_paths = [
        (winreg.HKEY_CURRENT_USER, r"Software\Tencent\WeChat"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\WeChat"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\WeChat"),
    ]
    
    for hkey, key_path in registry_paths:
        try:
            key = winreg.OpenKey(hkey, key_path)
            for value_name in ["FilePath", "InstallPath", ""]:
                try:
                    file_path, _ = winreg.QueryValueEx(key, value_name)
                    if file_path:
                        wechat_exe = os.path.join(file_path, "WeChat.exe")
                        if os.path.exists(wechat_exe):
                            return {'wechat_exe_path': wechat_exe}
                        
                        # 尝试 Weixin.exe (新版微信)
                        weixin_exe = os.path.join(file_path, "Weixin.exe")
                        if os.path.exists(weixin_exe):
                            return {'wechat_exe_path': weixin_exe}
                except Exception:
                    continue
            winreg.CloseKey(key)
        except Exception:
            continue
    
    return {}


def launch_wechat(wechat_exe_path: str) -> Optional[int]:
    """启动微信客户端
    
    Args:
        wechat_exe_path: 微信可执行文件路径
        
    Returns:
        int: 进程PID，失败返回 None
    """
    if not os.path.exists(wechat_exe_path):
        return None
    
    try:
        process = subprocess.Popen(wechat_exe_path)
        return process.pid
    except Exception:
        return None


def ensure_wechat_running(wechat_exe_path: str = None) -> Dict:
    """确保微信正在运行
    
    Args:
        wechat_exe_path: 微信可执行文件路径（可选）
        
    Returns:
        dict: 包含进程信息和状态
    """
    # 检测现有进程
    processes = detect_wechat_process()
    if processes:
        return {
            'status': 'running',
            'processes': processes,
            'pid': processes[0]['pid']
        }
    
    # 需要启动微信
    if not wechat_exe_path:
        install_info = detect_wechat_installation()
        wechat_exe_path = install_info.get('wechat_exe_path')
    
    if not wechat_exe_path:
        return {
            'status': 'not_found',
            'error': '未找到微信安装路径'
        }
    
    # 启动微信
    pid = launch_wechat(wechat_exe_path)
    if pid:
        # 等待进程启动
        time.sleep(3)
        processes = detect_wechat_process()
        return {
            'status': 'started',
            'pid': pid,
            'processes': processes
        }
    else:
        return {
            'status': 'failed',
            'error': '启动微信失败'
        }