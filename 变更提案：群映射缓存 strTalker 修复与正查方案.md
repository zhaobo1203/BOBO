# 变更提案：群映射缓存 strTalker 修复与正查方案

## 一、问题总结

### 核心 Bug：`_build_group_db_mapping` 使用 3.x 字段反查 4.x 数据库

`simple_monitor.py:1676` 的 `_build_group_db_mapping()` 方法在建立`{group_id → db_path}`映射缓存时，试图从消息表的 `strTalker` 字段反推群 ID：

```python
# line 1749 (当前代码)
if 'strTalker' in columns:
    cursor.execute(
        f"SELECT DISTINCT strTalker FROM {table_name} WHERE strTalker LIKE '%@chatroom' LIMIT 1"
    )
```

**问题**：微信 4.x 的 `Msg_*` 表中**没有 `strTalker` 字段**。替代字段是 `real_sender_id`（整数，指向 `Name2Id.rowid`），无法从中提取群 ID。

**后果**：
- `_build_group_db_mapping()` 始终返回空字典 `{}` — 表面上"找到 0 个群"
- `_get_messages_static()`（line 1777）的缓存优化完全失效，每次查询都走慢路径（解密全部 message db 逐一搜索）
- 日志显示 `[映射缓存] 共发现 0 个群`，但群消息仍然能查到，因为 fallback 逻辑直接按表名 `Msg_<MD5>` 搜索

### 相关问题 1：映射方向反了

当前方案是**反查**（从消息表的字段反推群 ID），正确方案应该是**正查**（从 `SessionTable` 获取群 ID → 计算 MD5 → 在 message db 中找 `Msg_<MD5>` 表）：

```
旧（反查）: Msg_<md5> 表 → strTalker 字段 → 群 ID
新（正查）: SessionTable → 群 ID → MD5 → Msg_<md5> 表
```

正查的优势：
- 不依赖消息表的 schema 版本（3.x 的 `strTalker` 或 4.x 的 `real_sender_id`）
- `SessionTable` 结构稳定（`username` 字段从 3.x 到 4.x 一致）
- 只需查询一次 session.db，无需解密所有 message db

### 相关问题 2：映射目标是"定位数据库"，但实际没必要

当前映射缓存试图回答"哪个群在哪个 message 数据库里"。但 MD5 查询天然可以跨所有 message db 搜索 — 即使没有映射缓存，逐个 db 搜索 `Msg_<MD5>` 表的开销也极低（每 db 执行一次 `sqlite_master` 查询，解密后 < 10ms）。

映射缓存本身并非错误设计，但**不应该在启动时构建**，应该在首次查询时按需缓存。

---

## 二、方案设计

### 核心思路：删除反查逻辑，改为正查 + 惰性缓存

#### 改动 1：重写 `_build_group_db_mapping()` — SessionTable 正查

新逻辑：
1. 查询已解密的 `session.db` 的 `SessionTable` 表，获取所有群 ID（`username LIKE '%@chatroom'`）
2. 对每个群 ID 计算 `Msg_<MD5>` 表名
3. 在 message 目录下逐个解密 message db，按需查找对应表
4. 找到后缓存 `{group_id → db_path}`

```python
def _build_group_db_mapping(self):
    mapping = {}
    session_conn = sqlite3.connect(self.decrypted_session_db)
    cursor = session_conn.cursor()
    cursor.execute(
        "SELECT username FROM SessionTable WHERE username LIKE '%@chatroom'"
    )
    group_ids = [row[0] for row in cursor.fetchall()]
    session_conn.close()

    for gid in group_ids:
        expected = f"Msg_{hashlib.md5(gid.encode()).hexdigest()}"
        db_path = self._find_message_db_by_table(expected)
        if db_path:
            mapping[gid] = db_path
    return mapping
```

#### 改动 2：新增 `_find_message_db_by_table(table_name)`

辅助方法，遍历 message db 查找包含指定表的数据库：

```python
def _find_message_db_by_table(self, target_table: str) -> str | None:
    for db_path in self._list_message_dbs():
        temp_db = self._decrypt_temp(db_path)
        if not temp_db:
            continue
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
            (target_table,)
        )
        if cursor.fetchone():
            conn.close()
            return db_path
        conn.close()
    return None
```

#### 改动 3：`_get_messages_static` 中的 fallback 也走正查

当前 fallback 路径（line 1839+）遍历所有 message db 查找 `Msg_<MD5>` 表，这个逻辑本身正确。只需确保：
- fallback 查到的结果也写入 `self._group_db_mapping` 缓存，避免下次再遍历
- 缓存的 key 统一为群 ID

#### 改动 4：删除 `strTalker` 相关代码

直接删除 line 1749 的 `if 'strTalker' in columns:` 及其整个分支。

---

## 三、修改清单

| 文件 | 行号 | 当前代码 | 改为 |
|------|------|---------|------|
| `src/simple_monitor.py` | 1742-1756 | 遍历 Msg_ 表查 strTalker 字段反推群 ID | SessionTable 正查群 ID → MD5 → Msg_ 表 |
| `src/simple_monitor.py` | 1676-1774 | `_build_group_db_mapping` 完整方法 | 重写为 SessionTable 正查方案 |
| `src/simple_monitor.py` | 1796-1797 | 保留（MD5 计算正确） | 无需修改 |
| `src/simple_monitor.py` | 1840+ | fallback 遍历路径 | 补充：查询结果写入缓存 |

### 不需要修改的代码

以下代码已经是**正确的**，使用正查逻辑：

- `src/simple_monitor.py:1175-1226` `_get_groups_from_session()` — 已正确使用 `SessionTable WHERE username LIKE '%@chatroom'`
- `src/wechat_decrypt_tool/chat_realtime_reader.py:137` — 已正确使用 MD5 正查
- `src/wechat_decrypt_tool/routers/chat.py:1112+` — 已正确使用 MD5 正查
- `src/wechat_decrypt_tool/routers/biz.py:393+` — 已正确使用 MD5 正查

---

## 四、验证方案

### 单元测试

| 编号 | 场景 | 方法 | 预期 |
|------|------|------|------|
| 01 | `_build_group_db_mapping` 有已解密的 session.db | Mock `SessionTable` 返回 3 个群 | 返回 3 个映射条目 |
| 02 | SessionTable 中无群（无 `@chatroom`） | Mock `SessionTable` 返回空 | 返回空 dict |
| 03 | 群对应的 Msg_ 表在 message_0.db | Mock message db 结构 | 映射到 message_0.db |
| 04 | 群对应的 Msg_ 表在 message_1.db | Mock message db 结构 | 映射到 message_1.db |
| 05 | Msg_ 表跨 db 不存在 | Mock sqlite_master 查询 | 映射中跳过该群 |
| 06 | `strTalker` 相关旧代码已删除 | grep `strTalker` | 文件中无匹配 |
| 07 | fallback 路径写入缓存 | 首次查询后检查 `_group_db_mapping` | 缓存包含该群 |
| 08 | 多个群映射到同一 db | 正常场景 | 正确合并 |

### 集成验证（已通过）

测试脚本 `test_find_group_messages.py` 已实际验证正查流程：

```
检测数据目录: 3 个
找到 session.db: 2 个
群列表: 44 个（SessionTable 正查）
目标群: 14126468@chatroom
MD5 表名: Msg_e3697b49cb1c6228fe0bc98f1bd63f45
定位数据库: message_0.db（遍历找到）
消息查询: 15 条 ✓
```

---

## 五、验收标准

1. `_build_group_db_mapping()` 返回非空映射（测试环境有 44 个群）
2. 旧代码中 `strTalker` 相关分支全部删除
3. `_get_messages_static()` 首次查询后缓存命中，后续查询走快路径
4. 日志中不再出现 `[映射缓存] 共发现 0 个群`
5. 启动时 `[映射缓存] 发现群: xx -> xx` 正常输出 44 条
