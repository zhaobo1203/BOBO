import ctypes
import struct
import hmac
import os
from ctypes import wintypes
import sys

# 使用 ThreadPoolExecutor 替代 multiprocessing.Pool
# 原因: PyInstaller onefile 模式下 multiprocessing 子进程会重新解压并执行整个 exe，
# 导致模块级代码（如日志初始化）在子进程中重复执行，造成死锁
from concurrent.futures import ThreadPoolExecutor, as_completed

import pymem
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA512
import yara

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

# Windows API Constants
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

finish_flag = False


def xor_raw_key(raw_key: bytes, internal_db_key: bytes | None) -> bytes:
    """在派生前对原始 32 字节候选 key 执行 XOR 变换。"""
    if internal_db_key is None:
        return raw_key
    if len(raw_key) != KEY_SIZE:
        raise ValueError(f"raw key length must be {KEY_SIZE}, got {len(raw_key)}")
    if len(internal_db_key) != KEY_SIZE:
        raise ValueError(f"internal_db_key length must be {KEY_SIZE}, got {len(internal_db_key)}")
    return bytes(a ^ b for a, b in zip(raw_key, internal_db_key))


def verify_worker(task):
    """Pool worker wrapper for imap_unordered."""
    return check_chunk(*task)


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


# 定义 MEMORY_BASIC_INFORMATION 结构
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


# 打开目标进程
def open_process(pid):
    return ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)


# 读取目标进程内存
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


# 获取所有内存区域
def get_memory_regions(process_handle):
    regions = []
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    while ctypes.windll.kernel32.VirtualQueryEx(
            process_handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
    ):
        if mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE:
            regions.append((mbi.BaseAddress, mbi.RegionSize))
        address += mbi.RegionSize
    return regions


def read_num(data: bytes, offset, size):
    """从二进制数据中读取指定大小的数字"""
    if size == 1:
        fmt = '<B'
    elif size == 2:
        fmt = '<H'
    elif size == 4:
        fmt = '<I'
    elif size == 8:
        fmt = '<Q'
    else:
        raise ValueError("Unsupported size")
    return struct.unpack_from(fmt, data, offset)[0]


def read_bytes_from_pid(pid: int, addr: int, size: int):
    """从进程内存中读取指定大小的字节"""
    hprocess = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not hprocess:
        raise Exception(f"Failed to open process with PID {pid}")
    buffer = b''
    try:
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        success = ReadProcessMemory(hprocess, addr, buffer, size, ctypes.byref(bytes_read))
        if not success:
            CloseHandle(hprocess)
            return b''
        CloseHandle(hprocess)
    except:
        pass
    return bytes(buffer)


def is_ok(passphrase, buf, internal_db_key=None):
    """验证密钥是否正确"""
    global finish_flag
    if finish_flag:
        return False
    # 获取文件开头的 salt
    salt = buf[:SALT_SIZE]
    # salt 异或 0x3a 得到 mac_salt，用于计算 HMAC
    mac_salt = bytes(x ^ 0x3a for x in salt)
    # 使用 PBKDF2 生成新的密钥
    passphrase = xor_raw_key(passphrase, internal_db_key)
    new_key = PBKDF2(passphrase, salt, dkLen=KEY_SIZE, count=ROUND_COUNT, hmac_hash_module=SHA512)
    # 使用新的密钥和 mac_salt 计算 mac_key
    mac_key = PBKDF2(new_key, mac_salt, dkLen=KEY_SIZE, count=2, hmac_hash_module=SHA512)
    # 计算 hash 校验码的保留空间
    reserve = IV_SIZE + HMAC_SHA512_SIZE
    reserve = ((reserve + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE
    # 校验 HMAC
    start = SALT_SIZE
    end = PAGE_SIZE
    mac = hmac.new(mac_key, buf[start:end - reserve + IV_SIZE], SHA512)
    mac.update(struct.pack('<I', 1))  # page number as 1
    hash_mac = mac.digest()
    # 校验 HMAC 是否一致
    hash_mac_start_offset = end - reserve + IV_SIZE
    hash_mac_end_offset = hash_mac_start_offset + len(hash_mac)
    if hash_mac == buf[hash_mac_start_offset:hash_mac_end_offset]:
        print(f"[+] Found valid key!")
        finish_flag = True
        return True
    return False


def check_chunk(chunk, buf, internal_db_key=None):
    """检查单个密钥候选"""
    global finish_flag
    if finish_flag:
        return False
    if is_ok(chunk, buf, internal_db_key):
        return chunk
    return False


def is_potential_key(key: bytes, strict: bool = True) -> bool:
    """
    通过熵分析与字符分布快速过滤非密钥的普通文本。

    Args:
        key: 32字节的候选密钥
        strict: 是否使用严格模式（默认True）
                - 严格模式: 要求 >= 15 种不同字节，可打印字符 <= 24
                - 宽松模式: 只过滤全0和全重复字节
    """
    if len(key) != 32:
        return False

    # 检查是否全0
    if key == b'\x00' * 32:
        return False

    if strict:
        # 严格模式：原来的过滤条件
        # 1. 过滤字节太单一的数据（如全0，或大量重复字节）
        # 随机密钥包含的相异字节种类极大概率 >= 15
        if len(set(key)) < 15:
            return False
        # 2. 过滤可打印字符(ASCII 32-126)过多的普通文本
        # 密码学随机密钥匙中可打印字符数量很难超过 24 个
        printable_count = sum(32 <= b <= 126 for b in key)
        if printable_count > 24:
            return False
    else:
        # 宽松模式：只过滤明显的无效数据
        # 至少要有 8 种不同的字节（非常宽松的条件）
        if len(set(key)) < 8:
            return False

    return True


def get_key_inner(pid, process_infos):
    """扫描可能为key的内存，返回密钥候选列表"""
    process_handle = open_process(pid)
    
    # 多个备用 YARA 规则，针对不同微信版本
    # 规则1: 原始规则（适用于较旧版本）
    # 规则2: 新版本模式（更宽松的匹配）
    # 规则3: V4 特征模式
    rules_v4_key = r'''
        rule GetKeyAddrStub_V1
        {
            strings:
                $a = { ?? ?? ?? ?? ?? ?? 00 00 00 00 00 00 00 00 00 00 20 00 00 00 00 00 00 00 2f 00 00 00 00 00 00 00 }
            condition:
                all of them
        }
        
        rule GetKeyAddrStub_V2
        {
            strings:
                // 新版本模式：查找 32字节密钥指针区域
                $a = { 00 00 00 00 00 00 00 00 20 00 00 00 00 00 00 00 }
            condition:
                all of them
        }
        
        rule GetKeyAddrStub_V3
        {
            strings:
                // 另一种常见模式
                $a = { 20 00 00 00 00 00 00 00 [0-16] 00 00 00 00 00 00 00 }
            condition:
                all of them
        }
        
        rule GetKeyAddrStub_V4
        {
            strings:
                // 寻找可能的密钥存储结构
                $a = { 20 00 00 00 00 00 00 00 2f }
            condition:
                all of them
        }
        
        rule GetKeyAddrStub_V5
        {
            strings:
                // 更宽松的模式
                $a = { 00 00 00 00 20 00 00 00 00 00 00 00 [0-8] 00 00 00 00 }
            condition:
                all of them
        }
        '''
    
    rules = yara.compile(source=rules_v4_key)
    pre_addresses = []
    rule_matches = {}  # 统计每个规则匹配次数

    for base_address, region_size in process_infos:
        memory = read_process_memory(process_handle, base_address, region_size)
        if not memory:
            continue

        matches = rules.match(data=memory)
        if matches:
            for match in matches:
                rule_name = match.rule
                if rule_name.startswith('GetKeyAddrStub'):
                    # 统计匹配
                    rule_matches[rule_name] = rule_matches.get(rule_name, 0) + 1
                    
                    for string in match.strings:
                        for instance in string.instances:
                            offset, content = instance.offset, instance.matched_data
                            # 根据不同规则调整地址计算
                            if 'V1' in rule_name or 'V2' in rule_name:
                                addr = read_num(memory, offset, 8)
                            elif 'V3' in rule_name:
                                addr = read_num(memory, offset + 8, 8)
                            elif 'V4' in rule_name:
                                addr = read_num(memory, offset - 8, 8)
                            elif 'V5' in rule_name:
                                addr = read_num(memory, offset + 4, 8)
                            else:
                                addr = read_num(memory, offset, 8)
                            
                            if addr > 0x10000:  # 过滤无效地址
                                pre_addresses.append(addr)

    # 打印匹配统计
    if rule_matches:
        print(f"[*] YARA rule matches: {rule_matches}")
    else:
        print(f"[!] No YARA matches found")

    keys = []
    key_set = set()
    for pre_address in pre_addresses:
        key = read_bytes_from_pid(pid, pre_address, 32)
        if key and key not in key_set:
            keys.append(key)
            key_set.add(key)

    return keys


def get_key(pid, process_handle, buf, internal_db_key=None):
    """获取密钥：扫描进程内存，寻找有效的密钥"""
    global finish_flag
    finish_flag = False  # 重置标志

    process_infos = get_memory_regions(process_handle)

    def split_list(lst, n):
        k, m = divmod(len(lst), n)
        return (lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n))

    keys = []
    # 使用 ThreadPoolExecutor 替代 multiprocessing.Pool
    # 避免PyInstaller onefile模式下子进程死锁问题
    worker_count = max(1, os.cpu_count() // 2)
    task_list = list(split_list(process_infos, min(len(process_infos), 40)))

    raw_keys = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(get_key_inner, pid, process_info_) for process_info_ in task_list]
        for future in as_completed(futures):
            r = future.result()
            if r:
                raw_keys += r

    # 合并去重
    unique_keys = list(set(raw_keys))

    print(f"[*] Total raw candidates extracted: {len(unique_keys)}")

    # 策略1: 严格模式过滤
    filtered_keys_strict = [k for k in unique_keys if is_potential_key(k, strict=True)]
    print(f"[*] Strict filtering: {len(filtered_keys_strict)} candidates")

    if filtered_keys_strict:
        print(f"[*] Testing with strict filtering...")
        key = verify_keys(filtered_keys_strict, buf, internal_db_key)
        if key:
            return key

    # 策略2: 宽松模式过滤（如果严格模式失败）
    finish_flag = False  # 重置标志
    filtered_keys_relaxed = [k for k in unique_keys if is_potential_key(k, strict=False)]
    print(f"[*] Relaxed filtering: {len(filtered_keys_relaxed)} candidates")

    # 排除已经验证过的严格模式候选
    remaining_keys = [k for k in filtered_keys_relaxed if k not in filtered_keys_strict]
    print(f"[*] Additional candidates to test: {len(remaining_keys)}")

    if remaining_keys:
        print(f"[*] Testing with relaxed filtering...")
        key = verify_keys(remaining_keys, buf, internal_db_key)
        if key:
            return key

    return None


def verify_keys(keys, buf, internal_db_key=None):
    """验证密钥候选列表，返回有效的密钥"""
    total = len(keys)
    if total == 0:
        print("[-] No key candidates found")
        return None

    # 使用 ThreadPoolExecutor 替代 multiprocessing.Pool
    # 避免PyInstaller onefile模式下子进程死锁问题
    worker_count = max(1, os.cpu_count() // 2)
    print(f"[*] Testing {total} filtered key candidates with {worker_count} workers...")

    completed = 0
    last_percent = -1
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(verify_worker, (key, buf, internal_db_key)): key for key in keys}
        for future in as_completed(futures):
            completed += 1
            percent = int((completed / total) * 100)
            if percent != last_percent:
                print(f"[*] Verify progress: {completed}/{total} ({percent}%)")
                last_percent = percent

            r = future.result()
            if r:
                print(f"[+] Key found: {bytes.hex(r)}")
                # 取消剩余任务
                for f in futures:
                    f.cancel()
                return bytes.hex(r)

    print("[-] Verification completed, no valid key")
    return None


def recover_key(pid, db_file_path=None, internal_db_key=None):
    """
    主函数：从 WeChat 进程恢复密钥
    """
    process_handle = open_process(pid)
    if not process_handle:
        print(f"[-] Failed to open process {pid}")
        return None

    if not db_file_path:
        print("[-] No database file specified")
        CloseHandle(process_handle)
        return None

    if not os.path.exists(db_file_path):
        print(f"[-] Database file not found: {db_file_path}")
        CloseHandle(process_handle)
        return None

    try:
        with open(db_file_path, 'rb') as f:
            buf = f.read()

        if len(buf) < PAGE_SIZE:
            print(f"[-] Database file too small: {len(buf)} bytes")
            CloseHandle(process_handle)
            return None

        print(f"[*] Scanning process memory for key candidates...")
        key = get_key(pid, process_handle, buf, internal_db_key)

        CloseHandle(process_handle)
        return key

    except Exception as e:
        print(f"[-] Error during key recovery: {e}")
        CloseHandle(process_handle)
        return None


def main():
    """命令行入口函数"""

    try:
        pm = pymem.Pymem("Weixin.exe")
        pid = pm.process_id
        print(f"[*] Connected to Weixin.exe (PID: {pid})")
    except Exception as e:
        print(f"[-] Failed to connect to Weixin.exe: {e}")
        return 1

    try:
        db_path = input("[*] Enter database file path (e.g., favorite_fts.db): ").strip()
    except EOFError:
        print("[-] No input available (running in non-interactive mode)")
        return 1

    if not db_path:
        print("[-] No path provided")
        return 1

    try:
        raw_internal_db_key = input("[*] Enter internal database key hex (optional, 64 hex chars): ").strip()
    except EOFError:
        print("[*] No internal_db_key provided, using None")
        raw_internal_db_key = ""

    internal_db_key = None
    if raw_internal_db_key:
        try:
            internal_db_key = bytes.fromhex(raw_internal_db_key)
        except ValueError:
            print("[-] Invalid internal_db_key hex")
            return 1
        if len(internal_db_key) != KEY_SIZE:
            print(f"[-] internal_db_key must be {KEY_SIZE} bytes, got {len(internal_db_key)}")
            return 1
        print("[+] internal_db_key length:", len(internal_db_key))

    key = recover_key(pid, db_path, internal_db_key)
    if key:
        key = xor_raw_key(bytes.fromhex(key), internal_db_key).hex()

    if key:
        print(f"[+] Successfully recovered key: {key}")
        return 0
    else:
        print("[-] Failed to recover key")
        return 1


if __name__ == '__main__':
    # 使用 multiprocessing.freeze_support() 确保 Windows 多进程正常工作
    # 将所有交互式代码放在 main() 函数中，避免模块导入时执行
    exit(main())
