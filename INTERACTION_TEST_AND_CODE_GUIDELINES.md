# 交互测试方案与代码固化准则

**项目**: WeChatDataAnalysis (微信群消息监听)  
**版本**: v1.0  
**文档日期**: 2026-07-21  
**文档性质**: 承上启下 - 连接开发与维护的核心文档

---

## 第一章 项目状态回顾

### 1.1 已完成功能模块清单

| 模块编号 | 模块名称 | 主要文件 | 状态 |
|---------|---------|----------|------|
| TN-01 | 进程检测 | `wechat_detection.py` | ✅ 已通过 |
| TN-02 | 账号检测 | `wechat_detection.py` | ✅ 已通过 |
| TN-03 | 密钥获取 | `key_v4.py`, `hook_injector.py` | ✅ 已通过 |
| TN-04 | 密钥存储 | `key_store.py` | ✅ 已通过 |
| TN-05 | WCDB连接 | `wcdb_realtime.py` | ✅ 已通过 |
| TN-06 | 消息监听 | `chat_realtime_reader.py` | ✅ 已通过 |

### 1.2 集成测试结论汇总

| 测试类型 | 测试结果 | 备注 |
|---------|---------|------|
| 功能测试 | ✅ 通过 | 所有核心功能正常运行 |
| 接口测试 | ✅ 通过 | 模块间接口调用正常 |
| 边界测试 | ✅ 通过 | 边界条件处理正确 |
| 异常测试 | ✅ 通过 | 异常情况处理合理 |
| 性能测试 | ✅ 通过 | 满足实时监听需求 |

### 1.3 代码健康度评估

基于静态测试报告 (`STATIC_TEST_REPORT.md`) 的评估结果：

| 维度 | 评分 | 说明 |
|------|------|------|
| 安全性 | ⚠️ 中等 | 存在潜在安全风险，已在本次版本中缓解 |
| 可维护性 | ✅ 良好 | 模块划分清晰，接口定义明确 |
| 类型安全 | ⚠️ 需改进 | 建议后续版本完善类型注解 |
| 代码风格 | ⚠️ 需改进 | 建议后续版本统一风格 |

---

## 第二章 交互测试方案

### 2.1 启动流程测试场景

#### 场景 2.1.1 正常启动流程

```
前置条件: 微信已登录运行
测试步骤:
  1. 执行 python src/main_exe.py
  2. 观察初始化日志输出
  3. 验证主菜单显示

预期结果:
  ✓ 检测到微信进程 (显示PID)
  ✓ 识别当前登录账号 (显示账号ID)
  ✓ 获取/加载数据库密钥
  ✓ 连接WCDB数据库
  ✓ 显示主菜单选项

测试命令:
  python E:\code2\WeChatDataAnalysis\src\main_exe.py
```

#### 场景 2.1.2 微信未启动场景

```
前置条件: 微信未运行
测试步骤:
  1. 执行 python src/main_exe.py
  2. 观察等待提示
  3. 启动微信并登录
  4. 观察自动检测

预期结果:
  ✓ 显示"等待微信进程启动"提示
  ✓ 微信启动后自动检测到进程
  ✓ 自动继续初始化流程

超时处理:
  - 默认等待60秒
  - 超时后提示用户手动启动微信
```

#### 场景 2.1.3 HOOK模式启动

```
前置条件: 管理员权限终端
测试步骤:
  1. 以管理员身份打开PowerShell
  2. 执行 .\run_hook.ps1
  3. 启动微信并登录
  4. 观察密钥自动获取

预期结果:
  ✓ HOOK注入成功
  ✓ 微信登录时自动获取密钥
  ✓ 密钥保存到 account_keys.json

测试命令:
  powershell -ExecutionPolicy Bypass -File E:\code2\WeChatDataAnalysis\run_hook.ps1
```

### 2.2 密钥获取测试场景

#### 场景 2.2.1 已存储密钥使用

```
前置条件: account_keys.json 中存在有效密钥
测试步骤:
  1. 确认 account_keys.json 存在
  2. 启动程序
  3. 观察密钥加载日志

预期结果:
  ✓ 读取已存储的密钥
  ✓ 显示密钥预览 (前8位)
  ✓ 跳过密钥获取步骤
```

#### 场景 2.2.2 HOOK回调获取密钥

```
前置条件: 无已存储密钥，使用HOOK模式
测试步骤:
  1. 删除或重命名 account_keys.json
  2. 以管理员权限运行 run_hook.ps1
  3. 启动微信并登录
  4. 观察密钥获取过程

预期结果:
  ✓ 显示"等待微信登录获取密钥"
  ✓ 登录成功后自动获取密钥
  ✓ 显示获取成功提示
  ✓ 密钥自动保存到存储

失败处理:
  - 超时后提示用户重新登录微信
  - 提供重试选项
```

### 2.3 消息监听测试场景

#### 场景 2.3.1 选择群聊并开始监听

```
前置条件: 已完成初始化，WCDB已连接
测试步骤:
  1. 在主菜单选择 [1] 查看群聊列表
  2. 选择要监听的群聊
  3. 在主菜单选择 [2] 开始监控
  4. 在微信群中发送测试消息
  5. 观察程序输出

预期结果:
  ✓ 显示群聊列表 (名称 + ID)
  ✓ 成功选择目标群聊
  ✓ 开始轮询监听
  ✓ 实时显示新消息
  ✓ 消息保存到 data/messages.db

测试数据:
  - 发送文字消息: "测试消息123"
  - 验证显示: 发送者昵称 + 消息内容 + 时间
```

#### 场景 2.3.2 消息解码测试

```
测试内容:
  1. 发送纯文字消息
  2. 发送包含表情的消息
  3. 发送包含特殊字符的消息

预期结果:
  ✓ 文字消息正常解码显示
  ✓ 表情符号正确处理
  ✓ 特殊字符正确显示
  ✓ 排除图片/视频等非文字消息
```

### 2.4 异常处理测试场景

#### 场景 2.4.1 数据库连接失败

```
触发条件: session.db 文件不存在或损坏
预期行为:
  ✓ 显示明确的错误信息
  ✓ 提供解决方案建议
  ✓ 不崩溃退出

恢复方式:
  - 等待数据库文件生成
  - 重新登录微信
```

#### 场景 2.4.2 密钥获取失败

```
触发条件: HOOK模式未能成功获取密钥
预期行为:
  ✓ 显示失败原因
  ✓ 提供重试选项
  ✓ 提供手动输入密钥选项

恢复方式:
  - 重新登录微信
  - 使用管理员权限运行
```

#### 场景 2.4.3 微信进程异常退出

```
触发条件: 监听过程中微信被关闭
预期行为:
  ✓ 检测到进程退出
  ✓ 显示提示信息
  ✓ 保存当前状态
  ✓ 提供重新连接选项
```

### 2.5 用户交互测试场景

#### 场景 2.5.1 主菜单导航

```
测试步骤:
  1. 启动程序进入主菜单
  2. 依次选择每个菜单项
  3. 验证功能正常
  4. 测试返回/退出操作

菜单项:
  [1] 查看群聊列表
  [2] 开始监控群聊
  [3] 查看历史消息
  [4] 解密数据库
  [5] 密钥管理
  [6] 系统状态
  [0] 退出程序

预期结果:
  ✓ 每个选项功能正常
  ✓ 返回主菜单正常
  ✓ 退出程序正常
```

#### 场景 2.5.2 参数输入验证

```
测试内容:
  1. 输入非数字选项
  2. 输入超出范围的数字
  3. 输入空值

预期结果:
  ✓ 显示错误提示
  ✓ 允许重新输入
  ✓ 不崩溃不退出
```

---

## 第三章 代码固化准则

### 3.1 文件结构规范

```
src/
├── main_exe.py              # 主程序入口 - 严禁重命名
├── simple_monitor.py        # 简化版启动 - 保持向后兼容
├── wechat_main.py           # 微信主模块
│
└── wechat_decrypt_tool/     # 核心工具包 - 严禁重命名
    ├── __init__.py
    ├── constants.py         # 常量定义
    ├── app_paths.py         # 路径管理
    ├── exe_logging.py       # 日志模块
    ├── logging_config.py    # 日志配置
    │
    ├── wechat_detection.py  # TN-01/02 进程/账号检测
    ├── wechat_waiter.py     # 初始化等待器
    ├── key_v4.py            # TN-03 V4密钥获取
    ├── key_store.py         # TN-04 密钥存储
    ├── hook_injector.py     # HOOK注入器
    ├── dll_key_scan.py      # DLL密钥扫描
    │
    ├── wcdb_realtime.py     # TN-05 WCDB实时监听
    ├── chat_realtime_reader.py  # 实时消息读取
    ├── chat_helpers.py      # 聊天辅助函数
    │
    ├── wechat_decrypt.py    # 数据库解密
    └── message_storage.py   # 消息存储
```

**固化规则**:
- 禁止修改核心模块的文件名
- 新增功能必须放入对应模块
- 禁止在根目录创建新的 Python 文件

### 3.2 编码风格规范

#### 3.2.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块名 | 小写+下划线 | `wechat_detection.py` |
| 类名 | 大驼峰 | `WeChatWaiter` |
| 函数名 | 小写+下划线 | `get_process_list` |
| 常量 | 全大写+下划线 | `POLL_INTERVAL_DEFAULT` |
| 私有变量 | 单下划线前缀 | `_temp_db_paths` |

#### 3.2.2 行长度限制

```python
# 规则: 单行不超过 120 字符
# 正确示例:
result = some_function_with_long_name(
    param1, param2, param3
)

# 错误示例:
result = some_function_with_long_name(param1, param2, param3, param4, param5, param6, param7)
```

#### 3.2.3 导入顺序

```python
# 1. 标准库
import os
import sys
import logging

# 2. 第三方库
import zstandard as zstd

# 3. 本地模块
from .constants import POLL_INTERVAL_DEFAULT
from .app_paths import get_app_data_dir
```

### 3.3 类型注解要求

#### 3.3.1 函数签名注解

```python
# 必须添加类型注解的函数
def detect_current_logged_in_account(
    data_dir: str | None = None
) -> dict[str, Any] | None:
    """检测当前登录的微信账号"""
    pass

def get_messages(
    conn: Any,
    table_name: str,
    group_id: str,
    limit: int = 50
) -> list[dict[str, Any]]:
    """获取群聊消息"""
    pass
```

#### 3.3.2 Optional 类型处理

```python
# 正确: 使用 | None 或 Optional
def find_session_db(data_path: str) -> str | None:
    pass

# 错误: 参数默认值 None 但类型注解为 str
def find_session_db(data_path: str = None):  # 错误!
    pass
```

### 3.4 错误处理规范

#### 3.4.1 禁止使用裸 except

```python
# 禁止:
try:
    do_something()
except:
    pass

# 正确:
try:
    do_something()
except FileNotFoundError as e:
    logger.error(f"文件未找到: {e}")
except Exception as e:
    logger.error(f"未知错误: {e}")
```

#### 3.4.2 异常日志记录

```python
# 必须记录异常信息
try:
    risky_operation()
except SpecificException as e:
    logger.error(f"操作失败: {e}", exc_info=True)
    raise
```

### 3.5 日志记录规范

#### 3.5.1 日志级别使用

| 级别 | 使用场景 |
|------|----------|
| DEBUG | 详细调试信息 |
| INFO | 正常运行状态 |
| WARNING | 潜在问题提醒 |
| ERROR | 错误但可恢复 |
| CRITICAL | 严重错误 |

#### 3.5.2 日志格式规范

```python
# 正确: 使用 % 格式化
logger.info("检测到微信进程: PID=%d", pid)
logger.error("连接失败: %s", error_msg)

# 不推荐: 使用 f-string (性能问题)
logger.info(f"检测到微信进程: PID={pid}")
```

---

## 第四章 版本发布标准

### 4.1 功能完整性检查清单

| 检查项 | 要求 | 验证方法 |
|--------|------|----------|
| 进程检测 | 正确检测微信进程 | 手动测试 |
| 账号识别 | 正确识别登录账号 | 手动测试 |
| 密钥获取 | HOOK模式正常工作 | 手动测试 |
| 数据库连接 | 成功连接WCDB | 手动测试 |
| 消息监听 | 实时显示新消息 | 手动测试 |
| 消息存储 | 正确保存到SQLite | 数据验证 |

### 4.2 安全性检查清单

| 检查项 | 状态 | 备注 |
|--------|------|------|
| 无命令注入风险 | ✅ | 不使用 shell=True |
| 无SQL注入风险 | ✅ | 使用参数化查询 |
| 密钥安全存储 | ✅ | JSON文件权限控制 |
| 临时文件安全 | ✅ | 使用 NamedTemporaryFile |

### 4.3 性能检查清单

| 指标 | 要求 | 实测值 |
|------|------|--------|
| 启动时间 | < 5秒 | ✅ 通过 |
| 内存占用 | < 100MB | ✅ 通过 |
| 消息延迟 | < 3秒 | ✅ 通过 |
| CPU占用 | < 5% | ✅ 通过 |

### 4.4 文档完整性检查

| 文档 | 状态 | 位置 |
|------|------|------|
| 设计报告 | ✅ | `DESIGN_REPORT.md` |
| 技术规范 | ✅ | `TECHNICAL_SPECIFICATION_REPORT.md` |
| 测试报告 | ✅ | `TEST_REPORT_TN01_TN06.md` |
| 静态测试 | ✅ | `STATIC_TEST_REPORT.md` |
| 工作流程 | ✅ | `WORKFLOW_DIAGRAM.md` |
| 本文档 | ✅ | `INTERACTION_TEST_AND_CODE_GUIDELINES.md` |

---

## 第五章 维护指南

### 5.1 已知问题与解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 首次启动无数据目录 | 微信未完全初始化 | 使用 WeChatWaiter 等待 |
| 密钥获取失败 | 权限不足或微信版本变化 | 使用管理员权限运行 |
| 消息解码乱码 | 编码格式变化 | 更新解码逻辑 |

### 5.2 技术债务清单

| 债务类型 | 描述 | 优先级 | 建议 |
|----------|------|--------|------|
| 类型注解 | 683个类型错误 | 中 | 分批完善 |
| 代码风格 | 行尾空白等问题 | 低 | 使用格式化工具 |
| 代码复杂度 | 部分函数过长 | 中 | 重构拆分 |

### 5.3 未来迭代方向

#### 短期计划 (v1.1)

1. 完善类型注解 (目标: 0类型错误)
2. 优化代码风格 (目标: 0风格警告)
3. 增加单元测试覆盖

#### 中期计划 (v1.5)

1. 支持多账号同时监听
2. 增加消息搜索功能
3. 优化内存占用

#### 长期计划 (v2.0)

1. 图形化界面
2. 消息分析统计
3. 导出功能增强

---

## 附录A 快速参考

### A.1 启动命令

```bash
# 完整版启动
python E:\code2\WeChatDataAnalysis\src\main_exe.py

# 简化版启动
python E:\code2\WeChatDataAnalysis\src\simple_monitor.py

# HOOK模式启动 (需管理员权限)
powershell -ExecutionPolicy Bypass -File E:\code2\WeChatDataAnalysis\run_hook.ps1
```

### A.2 关键文件位置

| 文件 | 用途 |
|------|------|
| `key_store.json` | 密钥存储 |
| `account_keys.json` | 账号密钥映射 |
| `data/messages.db` | 消息存储数据库 |
| `logs/` | 日志文件目录 |

### A.3 常见错误码

| 错误码 | 描述 | 解决方案 |
|--------|------|----------|
| ERR_PROC_001 | 未检测到微信进程 | 启动微信 |
| ERR_ACCOUNT_003 | 未检测到数据目录 | 等待微信初始化 |
| ERR_KEY_002 | 密钥获取失败 | 重新登录微信 |
| ERR_WCDB_001 | session.db 未找到 | 检查数据目录 |
| ERR_WCDB_003 | WCDB 连接失败 | 检查密钥 |

---

## 附录B 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-07-21 | 初始版本，完成全部核心模块测试 |

---

**文档维护者**: AI Assistant  
**最后更新**: 2026-07-21 21:30