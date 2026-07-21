# 微信群消息监听系统 - 技术节点测试报告

**测试日期：** 2026年7月16日  
**测试环境：** Windows 10, Python 3.x, 微信 4.x

---

## 一、测试概述

本文档记录了微信群消息监听系统 6 个关键技术节点（TN-01 至 TN-06）的测试过程和结果。所有测试均已通过验证。

| 节点 | 功能 | 复杂度 | 风险等级 | 测试结果 |
|------|------|--------|----------|----------|
| TN-01 | 微信进程管理与启动控制 | 中 | 低 | ✅ 通过 |
| TN-02 | 当前登录账号检测与识别 | 中 | 中 | ✅ 通过 |
| TN-03 | 数据库密钥获取（V4内存扫描） | 高 | 高 | ✅ 通过 |
| TN-04 | SQLCipher 数据库解密 | 中 | 中 | ✅ 通过 |
| TN-05 | WCDB 实时消息监听 | 高 | 高 | ✅ 通过 |
| TN-06 | 群消息提取与存储 | 中 | 低 | ✅ 通过 |

---

## 二、TN-01: 微信进程管理与启动控制

### 2.1 测试目标
- 检测微信进程是否运行（Weixin.exe / WeChat.exe）
- 终止所有微信进程
- 自动启动微信客户端

### 2.2 测试方法

```powershell
python test_tn01_process.py
```

### 2.3 测试代码要点

```python
import psutil

def detect_wechat_process():
    """检测微信进程"""
    processes = [p for p in psutil.process_iter(['name', 'pid']) 
                 if p.info['name'].lower() in ['weixin.exe', 'wechat.exe']]
    return processes

def kill_wechat_processes():
    """终止所有微信进程"""
    processes = detect_wechat_process()
    for p in processes:
        p.kill()
        
def launch_wechat(install_path: str):
    """启动微信"""
    import subprocess
    subprocess.Popen(install_path)
```

### 2.4 测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 进程检测 | ✅ 通过 | 能正确识别 Weixin.exe 进程 |
| 进程终止 | ✅ 通过 | 能终止所有微信进程（多实例场景） |
| 微信启动 | ✅ 通过 | 能自动启动微信（检测安装路径） |

### 2.5 关键发现
- 微信进程名为 `Weixin.exe`（小写）
- 微信安装路径存储在注册表：`HKCU\Software\Tencent\WeChat`
- 多开场景需要终止所有实例

---

## 三、TN-02: 当前登录账号检测与识别

### 3.1 测试目标
- 扫描微信数据目录，识别账号
- 检测当前登录的账号ID（支持 wxid_ 和自定义ID）
- 处理多账号场景

### 3.2 测试方法

```powershell
python test_tn02_account.py
```

### 3.3 测试代码要点

```python
from wechat_decrypt_tool.wechat_detection import (
    auto_detect_wechat_data_dirs,
    detect_current_logged_in_account
)

# 自动检测微信数据目录
data_dirs = auto_detect_wechat_data_dirs()

# 检测当前登录账号
account = detect_current_logged_in_account()
# 返回: {'current_account': 'wxid_xxx', 'data_path': 'E:\\xwechat_files\\wxid_xxx'}
```

### 3.4 测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 目录检测 | ✅ 通过 | 自动找到 xwechat_files 目录 |
| 账号识别 | ✅ 通过 | 正确识别当前登录账号 |
| 格式兼容 | ✅ 通过 | 支持 wxid_xxx 和自定义ID |

### 3.5 关键发现
- 微信 4.x 数据目录格式：`{用户ID}_{4位随机字符}`
- 账号ID可能为 `wxid_` 格式或自定义英文ID
- 通过 `global_config.db` 可获取账号信息

---

## 四、TN-03: 数据库密钥获取

### 4.1 测试目标
- 扫描微信进程内存，提取数据库密钥
- 支持 SQLCipher 密钥验证
- 密钥持久化存储

### 4.2 测试方法

```powershell
python test_tn03_dll_scan.py
```

### 4.3 测试代码要点

```python
from wechat_decrypt_tool.key_v4 import recover_key

# 从微信进程恢复密钥
key = recover_key(pid, db_path)
# 返回: 64位十六进制密钥字符串

# 保存密钥
from wechat_decrypt_tool.key_store import upsert_account_keys_in_store
upsert_account_keys_in_store(account_name, db_key=key)
```

### 4.4 测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| DLL 密钥扫描 | ✅ 通过 | 从 wcdb.dll 扫描密钥候选 |
| 密钥验证 | ✅ 通过 | 使用 session.db 验证密钥有效性 |
| 密钥存储 | ✅ 通过 | 保存到 key_store.json |

### 4.5 关键发现
- 密钥为 32 字节（64 位十六进制）
- 密钥存储在 `key_store.json` 文件
- 微信 4.x 使用 PBKDF2-SHA512 派生密钥

---

## 五、TN-04: SQLCipher 数据库解密

### 5.1 测试目标
- 使用密钥解密微信数据库文件
- 支持 AES-256-CBC 加密
- 输出明文 SQLite 数据库

### 5.2 测试方法

```powershell
python test_tn04_decrypt.py
```

### 5.3 测试代码要点

```python
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

decryptor = WeChatDatabaseDecryptor(key_hex)
success = decryptor.decrypt_database(
    input_path="session.db",
    output_path="session_decrypted.db"
)
```

### 5.4 测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 数据库解密 | ✅ 通过 | 成功解密 session.db |
| 完整性验证 | ✅ 通过 | 解密后数据库可正常读取 |
| contact.db 解密 | ✅ 通过 | 成功解密联系人数据库 |

### 5.5 关键发现
- 页面大小：4096 字节
- 加密算法：AES-256-CBC
- HMAC 校验：HMAC-SHA512
- 密钥派生：PBKDF2-SHA512, 256000轮迭代

---

## 六、TN-05: WCDB 实时消息监听

### 6.1 测试目标
- 通过 WCDB DLL 连接微信数据库
- 实时监听消息变更
- 支持群消息提取

### 6.2 测试方法

```powershell
python test_tn05_realtime.py
```

### 6.3 测试代码要点

```python
from wechat_decrypt_tool.wcdb_realtime import (
    open_account as wcdb_open_account,
    get_sessions as wcdb_get_sessions,
    get_messages as wcdb_get_messages,
    close_account as wcdb_close_account,
)

# 连接数据库
handle = wcdb_open_account(session_db_path, db_key)

# 获取会话列表
sessions = wcdb_get_sessions(handle)

# 获取消息
messages = wcdb_get_messages(handle, username, limit=20)

# 关闭连接
wcdb_close_account(handle)
```

### 6.4 测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| WCDB 连接 | ✅ 通过 | Sidecar 模式成功启动 |
| 会话获取 | ✅ 通过 | 获取到 201 个群聊 |
| 消息读取 | ✅ 通过 | 成功读取历史消息 |

### 6.5 关键发现
- WCDB 使用 Sidecar 进程（Electron）隔离
- 依赖 `wcdb_api.dll` 原生库
- 需要 Visual C++ Redistributable 运行时

---

## 七、TN-06: 群消息提取与存储

### 7.1 测试目标
- 从消息记录中提取群消息
- 解析 packed_info (protobuf) 获取发送者信息
- 解码 zstd 压缩的消息内容
- 存储到 SQLite 数据库

### 7.2 测试方法

```powershell
python test_monitor_group.py
```

### 7.3 测试代码要点

```python
import zstandard as zstd

def decode_message_content(message_value) -> str:
    """解码消息内容（处理zstd压缩）"""
    zstd_magic = b"\x28\xb5\x2f\xfd"
    
    # 处理 hex 编码的 zstd 数据
    text = str(message_value or "").strip()
    if len(text) >= 16 and len(text) % 2 == 0:
        raw = bytes.fromhex(text)
        if raw.startswith(zstd_magic):
            out = zstd.decompress(raw)
            return out.decode("utf-8", errors="ignore")
    return text
```

### 7.4 测试结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 解密 contact.db | ✅ 通过 | 获取群名称映射 |
| 找到目标群 | ✅ 通过 | 找到 "（不聊天群）市场资讯" |
| zstd 解压 | ✅ 通过 | 正确解压消息内容 |
| 消息显示 | ✅ 通过 | 正确显示中文消息 |

### 7.5 关键发现

**消息数据结构：**
```
{
    'create_time': 1784185573,        # 秒级时间戳
    'sender_username': 'leijian8981', # 发送者ID
    'message_content': '28b52ffd...',  # zstd压缩的hex字符串
    'local_type': 1,                  # 消息类型
    'packed_info_data': '0813...',    # protobuf数据
}
```

**群名称来源：**
- 从 `contact.db` 的 `remark`（备注）或 `nick_name`（昵称）字段获取

**消息内容解码流程：**
1. `message_content` 是 hex 编码字符串
2. 转换为 bytes 后以 `28b52ffd`（zstd magic）开头
3. 使用 zstandard 库解压
4. 解码为 UTF-8 文本

---

## 八、测试脚本清单

| 脚本文件 | 测试节点 | 说明 |
|----------|----------|------|
| `test_tn01_process.py` | TN-01 | 微信进程管理测试 |
| `test_tn02_account.py` | TN-02 | 账号检测测试 |
| `test_tn03_dll_scan.py` | TN-03 | 密钥获取测试（DLL扫描） |
| `test_tn03_hook.py` | TN-03 | 密钥获取测试（Hook注入） |
| `test_tn04_decrypt.py` | TN-04 | 数据库解密测试 |
| `test_tn05_realtime.py` | TN-05 | 实时监听测试 |
| `test_decrypt_contact.py` | TN-06 | contact.db 解密 |
| `test_analyze_group_names.py` | TN-06 | 群名称分析 |
| `test_monitor_group.py` | TN-06 | 群消息监听完整测试 |

---

## 九、依赖环境

### 9.1 Python 依赖

```bash
pip install pymem psutil zstandard pysqlcipher3
```

### 9.2 系统依赖

- **Visual C++ Redistributable** - WCDB DLL 运行所需
- **Windows 10/11** - 仅支持 Windows

### 9.3 微信要求

- 微信 4.x 版本
- 微信客户端需要运行中（获取密钥）

---

## 十、注意事项

### 10.1 风险提示
- 本工具仅供个人数据管理使用
- 请勿用于商业用途或侵犯他人隐私
- 使用者需自行承担法律责任

### 10.2 技术限制
- 仅支持 Windows 系统
- 需要微信客户端运行
- 密钥可能在微信更新后失效

### 10.3 已知问题
1. 部分消息显示乱码（非文本消息类型）
2. 发送者显示用户名而非昵称
3. 消息内容可能有重复前缀

---

## 十一、下一步计划

1. **代码整合** - 将测试代码整合为完整系统
2. **错误处理** - 添加完善的异常处理
3. **配置管理** - 支持配置文件
4. **日志系统** - 完善日志记录
5. **UI 界面** - 开发图形界面（可选）

---

**报告生成时间：** 2026年7月16日 15:24  
**文档版本：** v1.0