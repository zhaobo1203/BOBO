"""
内存暴力搜索密钥模块

不依赖 YARA 规则，直接扫描进程内存中的高熵数据块进行密钥验证。
"""

import ctypes
import multiprocessing
import struct
import hmac
import os
from ctypes import wintypes
from multiprocessing import freeze_support
import sys

from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512

# 定义必要的常量
PROCESS_ALL_ACCESS = 0x1F0FFF
PAGE_READWRITE = 0x04
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000

# Stream cipher constants
IV_SIZE = 16
HMAC_SHA256_SIZE = 64
HMAC_SHA512_SIZE = 64
KEY_SIZE = 32
AES_BLOCK_SIZE = 16
ROUND_COUNT = 256000
PAGE_SIZE = 4096
SALT_SIZE = 16

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

finish_flag = False

# Load Windows DLLs
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
                              ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


def open_process(pid):
    return ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)


def read_process_memory(process_handle, address, size):
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    success = ctypes.windll.kernel32.ReadProcessMemory(
        process_handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read)
    )
    if not success:
        return None
    return buffer.raw


def get_memory_regions(process_handle):
    """获取所有可读内存区域"""
    regions = []
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    
    while ctypes.windll.kernel32.VirtualQueryEx(
            process_handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
    ):
        # 只扫描已提交的私有内存，且具有读取权限
        if mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE:
            # 检查内存保护标志，跳过不可读的内存
            if mbi.Protect != 0 and not (mbi.Protect & 0x01):  # 不是 PAGE_NOACCESS
                regions.append((mbi.BaseAddress, mbi.RegionSize))
        address += mbi.RegionSize
    
    return regions


def xor_raw_key(raw_key: bytes, internal_db_key: bytes | None) -> bytes:
    """在派生前对原始 32 字节候选 key 执行 XOR 变换"""
    if internal_db_key is None:
        return raw_key
    if len(raw_key) != KEY_SIZE:
        raise ValueError(f"raw key length must be {KEY_SIZE}, got {len(raw_key)}")
    if len(internal_db_key) != KEY_SIZE:
        raise ValueError(f"internal_db_key length must be {KEY_SIZE}, got {len(internal_db_key)}")
    return bytes(a ^ b for a, b in zip(raw_key, internal_db_key))


def is_ok(passphrase, buf, internal_db_key=None):
    """验证密钥是否正确"""
    global finish_flag
    if finish_flag:
        return False
    
    salt = buf[:SALT_SIZE]
    mac_salt = bytes(x ^ 0x3a for x in salt)
    passphrase = xor_raw_key(passphrase, internal_db_key)
    new_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT, hmac_hash_module=SHA512)
    mac_key = PBKDF2(new_key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)
    
    reserve = IV_SIZE + HMAC_SHA512_SIZE
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE
    
    start = SALT_SIZE
    end = PAGE_SIZE
    mac = hmac.new(mac_key, buf[start:end - reserve + IV_SIZE], SHA512)
    mac.update(struct.pack('<I', 1))
    hash_mac = mac.digest()
    
    hash_mac_start_offset = end - reserve + IV_SIZE
    hash_mac_end_offset = hash_mac_start_offset + len(hash_mac)
    
    if hash_mac == buf[hash_mac_start_offset:hash_mac_end_offset]:
        print(f"[+] Found valid key!")
        finish_flag = True
        return True
    return False


def is_high_entropy(data: bytes, min_unique_bytes: int = 16) -> bool:
    """检查数据是否具有高熵（足够随机）"""
    if len(data) != KEY_SIZE:
        return False
    
    # 检查是否全 0
    if data == b'\x00' * KEY_SIZE:
        return False
    
    # 检查唯一字节数量
    unique_bytes = len(set(data))
    if unique_bytes < min_unique_bytes:
        return False
    
    return True


def scan_memory_region_for_keys(args):
    """扫描单个内存区域，提取高熵数据块"""
    pid, base_address, region_size, buf, internal_db_key = args
    
    process_handle = open_process(pid)
    if not process_handle:
        return []
    
    try:
        memory = read_process_memory(process_handle, base_address, region_size)
        if not memory:
            return []
        
        candidates = []
        
        # 步进为 8 字节（对齐），扫描每个 32 字节块
        step = 8
        for offset in range(0, len(memory) - KEY_SIZE, step):
            chunk = memory[offset:offset + KEY_SIZE]
            
            # 快速过滤：检查是否是高熵数据
            if not is_high_entropy(chunk):
                continue
            
            # 尝试验证
            if is_ok(chunk, buf, internal_db_key):
                candidates.append(chunk)
                break  # 找到就退出
        
        return candidates
    
    finally:
        CloseHandle(process_handle)


def brute_force_search_key(pid, db_path, internal_db_key=None, max_regions=None):
    """
    暴力搜索内存中的密钥
    
    Args:
        pid: 微信进程 PID
        db_path: 数据库文件路径（用于验证）
        internal_db_key: XOR 掩码密钥（可选）
        max_regions: 最大扫描区域数（可选，用于限制扫描范围）
    
    Returns:
        找到的密钥（64 位十六进制字符串）或 None
    """
    global finish_flag
    finish_flag = False
    
    # 读取数据库文件
    with open(db_path, 'rb') as f:
        buf = f.read()
    
    if len(buf) < PAGE_SIZE:
        print(f"[-] Database file too small: {len(buf)} bytes")
        return None
    
    # 打开进程
    process_handle = open_process(pid)
    if not process_handle:
        print(f"[-] Failed to open process {pid}")
        return None
    
    # 获取内存区域
    print("[*] Getting memory regions...")
    regions = get_memory_regions(process_handle)
    CloseHandle(process_handle)
    
    print(f"[*] Found {len(regions)} memory regions")
    
    if max_regions:
        regions = regions[:max_regions]
        print(f"[*] Limited to {len(regions)} regions")
    
    # 计算总扫描大小
    total_size = sum(size for _, size in regions)
    print(f"[*] Total memory to scan: {total_size / 1024 / 1024:.2f} MB")
    
    # 准备任务列表
    tasks = [(pid, addr, size, buf, internal_db_key) for addr, size in regions]
    
    # 使用多进程扫描
    worker_count = max(1, multiprocessing.cpu_count() // 2)
    print(f"[*] Starting brute force search with {worker_count} workers...")
    
    found_keys = []
    
    with multiprocessing.Pool(processes=worker_count) as pool:
        for i, result in enumerate(pool.imap_unordered(scan_memory_region_for_keys, tasks)):
            if result:
                found_keys.extend(result)
                if finish_flag:
                    pool.terminate()
                    break
            
            # 显示进度
            if (i + 1) % 100 == 0:
                print(f"[*] Scanned {i + 1}/{len(tasks)} regions...")
    
    if found_keys:
        key = found_keys[0]
        return key.hex()
    
    print("[-] Brute force search completed, no valid key found")
    return None


def main():
    """命令行入口"""
    freeze_support()
    
    import psutil
    
    # 查找微信进程
    print("[*] Looking for WeChat process...")
    pid = None
    for p in psutil.process_iter(['pid', 'name']):
        try:
            name = p.info['name'].lower() if p.info['name'] else ''
            if name in ['weixin.exe', 'wechat.exe']:
                pid = p.info['pid']
                print(f"[+] Found WeChat process: PID={pid}")
                break
        except:
            pass
    
    if not pid:
        print("[-] WeChat process not found")
        return 1
    
    # 获取数据库路径
    print("[*] Enter database file path for verification")
    db_path = input("    Path: ").strip()
    
    if not db_path or not os.path.exists(db_path):
        print("[-] Invalid database path")
        return 1
    
    # 获取 internal_db_key（可选）
    print("[*] Enter internal_db_key (64 hex chars, optional):")
    internal_key_hex = input("    Key: ").strip()
    
    internal_db_key = None
    if internal_key_hex:
        try:
            internal_db_key = bytes.fromhex(internal_key_hex)
            print(f"[+] Loaded internal_db_key: {internal_key_hex[:16]}...")
        except:
            print("[-] Invalid internal_db_key format")
            return 1
    
    # 执行暴力搜索
    print("\n[*] Starting brute force memory search...")
    key = brute_force_search_key(pid, db_path, internal_db_key)
    
    if key:
        print(f"\n[+] SUCCESS! Found key: {key}")
        return 0
    else:
        print("\n[-] Failed to find key")
        return 1


if __name__ == '__main__':
    exit(main())