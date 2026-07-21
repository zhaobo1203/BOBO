# WeChatDataAnalysis 项目运行流程图

**文档日期：** 2026年7月20日  
**版本：** v1.0

---

## 一、系统整体架构流程图

```mermaid
flowchart TB
    subgraph 用户层["用户层"]
        USER["用户"]
        CLI["命令行界面 (CLI)"]
    end
    
    subgraph 应用层["应用层"]
        MAIN["tn_combined_v3.py<br/>主程序入口"]
        MONITOR["monitor_group.py<br/>单群监听脚本"]
    end
    
    subgraph 业务层["业务层"]
        PROC["进程管理模块"]
        ACCOUNT["账号检测模块"]
        KEY["密钥管理模块"]
        DECRYPT["数据库解密模块"]
        REALTIME["实时监听模块"]
        STORAGE["消息存储模块"]
    end
    
    subgraph 数据层["数据层"]
        WXPROC["微信进程"]
        WXDB["微信数据库<br/>(session.db/contact.db)"]
        LOCALDB["本地存储<br/>(messages.db)"]
        KEYSTORE["密钥存储<br/>(key_store.json)"]
    end
    
    USER --> CLI
    CLI --> MAIN
    CLI --> MONITOR
    
    MAIN --> PROC
    MAIN --> ACCOUNT
    MAIN --> KEY
    MAIN --> DECRYPT
    MAIN --> REALTIME
    MAIN --> STORAGE
    
    PROC --> WXPROC
    ACCOUNT --> WXPROC
    KEY --> WXPROC
    KEY --> KEYSTORE
    DECRYPT --> WXDB
    REALTIME --> WXDB
    STORAGE --> LOCALDB
```

---

## 二、主程序启动流程图

```mermaid
flowchart TD
    START([程序启动]) --> INIT["初始化环境<br/>设置日志、检测工作目录"]
    INIT --> CHECK_WX{"微信进程<br/>是否运行?"}
    
    CHECK_WX -->|否| DETECT_PATH["检测微信安装路径<br/>(注册表/常见路径)"]
    DETECT_PATH --> LAUNCH_WX["启动微信进程"]
    LAUNCH_WX --> WAIT_LOGIN["等待用户登录<br/>(最多30秒)"]
    WAIT_LOGIN --> CHECK_WX
    
    CHECK_WX -->|是| DETECT_ACCOUNT["检测当前登录账号<br/>(文件句柄检测)"]
    DETECT_ACCOUNT --> MATCH_KEY{"密钥存储中<br/>是否存在?"}
    
    MATCH_KEY -->|是| LOAD_KEY["加载已保存密钥"]
    MATCH_KEY -->|否| SCAN_KEY["V4内存扫描<br/>获取密钥"]
    SCAN_KEY --> SCAN_OK{"扫描成功?"}
    
    SCAN_OK -->|否| HOOK_KEY["Hook注入获取密钥"]
    HOOK_KEY --> HOOK_OK{"Hook成功?"}
    HOOK_OK -->|否| ERROR_EXIT([错误退出])
    
    SCAN_OK -->|是| VERIFY_KEY
    HOOK_OK -->|是| VERIFY_KEY
    LOAD_KEY --> VERIFY_KEY["验证密钥<br/>(尝试解密数据库)"]
    
    VERIFY_KEY --> VERIFY_OK{"解密成功?"}
    VERIFY_OK -->|否| SCAN_KEY
    
    VERIFY_OK -->|是| SCAN_DB["扫描数据库文件<br/>(session.db/contact.db)"]
    SCAN_DB --> LOAD_GROUPS["加载群聊列表<br/>(从contact.db)"]
    LOAD_GROUPS --> SELECT_GROUP["选择要监控的群"]
    SELECT_GROUP --> START_MONITOR["进入实时监控循环"]
    START_MONITOR --> MONITOR_LOOP([监控循环])
```

---

## 三、密钥获取与匹配流程图

```mermaid
flowchart TD
    subgraph 密钥获取流程
        START([需要密钥]) --> CHECK_STORE{"检查密钥存储<br/>key_store.json"}
        
        CHECK_STORE -->|文件存在| LOAD_STORE["加载密钥存储"]
        LOAD_STORE --> MATCH_PATH{"通过 data_path<br/>精确匹配"}
        
        MATCH_PATH -->|匹配成功| RETURN_KEY(["返回密钥"])
        MATCH_PATH -->|匹配失败| MATCH_WXID{"通过 wxid<br/>精确匹配"}
        
        MATCH_WXID -->|匹配成功| RETURN_KEY
        MATCH_WXID -->|匹配失败| MATCH_PREFIX{"通过 wxid前缀<br/>模糊匹配"}
        
        MATCH_PREFIX -->|匹配成功| RETURN_KEY
        MATCH_PREFIX -->|匹配失败| NEED_NEW_KEY["需要获取新密钥"]
        
        CHECK_STORE -->|文件不存在| NEED_NEW_KEY
        
        NEED_NEW_KEY --> SCAN_MEMORY["V4内存扫描"]
        SCAN_MEMORY --> SCAN_RESULT{"扫描结果"}
        
        SCAN_RESULT -->|成功| VERIFY_DB["验证密钥<br/>(尝试解密数据库)"]
        SCAN_RESULT -->|失败| HOOK_INJECT["Hook注入方式"]
        
        HOOK_INJECT --> HOOK_RESULT{"注入结果"}
        HOOK_RESULT -->|成功| VERIFY_DB
        HOOK_RESULT -->|失败| ERROR([密钥获取失败])
        
        VERIFY_DB --> VERIFY_OK{"验证通过?"}
        VERIFY_OK -->|是| SAVE_KEY["保存密钥到存储"]
        VERIFY_OK -->|否| SCAN_MEMORY
        
        SAVE_KEY --> RETURN_KEY
    end
```

---

## 四、实时消息监听流程图

```mermaid
flowchart TD
    subgraph 监控循环["实时监控循环"]
        START_MONITOR([开始监控]) --> CONNECT_WCDB["连接WCDB数据库<br/>(open_account)"]
        CONNECT_WCDB --> GET_HISTORY["获取历史消息<br/>(最近100条)"]
        GET_HISTORY --> PARSE_HISTORY["解析历史消息<br/>(解码zstd压缩)"]
        PARSE_HISTORY --> SET_BASELINE["设置基准时间戳<br/>(last_create_time)"]
        
        SET_BASELINE --> POLL_LOOP{"轮询循环"}
        
        POLL_LOOP --> SLEEP["等待轮询间隔<br/>(自适应0.5-5秒)"]
        SLEEP --> GET_NEW["获取最新消息<br/>(limit=30)"]
        
        GET_NEW --> FILTER_NEW["过滤新消息<br/>(时间戳 > last_create_time)"]
        FILTER_NEW --> HAS_NEW{"有新消息?"}
        
        HAS_NEW -->|是| PROCESS_MSG["处理新消息"]
        HAS_NEW -->|否| ADJUST_INTERVAL["调整轮询间隔<br/>(延长)"]
        
        PROCESS_MSG --> DECODE_MSG["解码消息内容<br/>(zstd解压)"]
        DECODE_MSG --> CHECK_TYPE{"消息类型判断"}
        
        CHECK_TYPE -->|文字消息| DISPLAY_MSG["显示消息"]
        CHECK_TYPE -->|非文字| FILTER_MSG["过滤消息"]
        
        DISPLAY_MSG --> GET_SENDER["获取发送者昵称"]
        GET_SENDER --> SAVE_MSG["保存到本地数据库"]
        SAVE_MSG --> UPDATE_TIME["更新last_create_time"]
        
        FILTER_MSG --> UPDATE_TIME
        UPDATE_TIME --> SHORTEN_INTERVAL["缩短轮询间隔<br/>(快速响应)"]
        
        SHORTEN_INTERVAL --> POLL_LOOP
        ADJUST_INTERVAL --> POLL_LOOP
        
        POLL_LOOP -->|用户中断| CLEANUP["清理资源"]
        CLEANUP --> CLOSE_WCDB["关闭WCDB连接"]
        CLOSE_WCDB --> STOP_MONITOR([监控停止])
    end
```

---

## 五、数据库解密流程图

```mermaid
flowchart TD
    subgraph 解密流程["SQLCipher数据库解密"]
        START_DECRYPT([开始解密]) --> READ_FILE["读取加密数据库文件"]
        READ_FILE --> CALC_PAGES["计算总页数<br/>(文件大小 / 4096)"]
        
        CALC_PAGES --> LOOP_PAGES["遍历每一页"]
        
        LOOP_PAGES --> READ_PAGE["读取页面数据<br/>(4096字节)"]
        READ_PAGE --> EXTRACT_IV["提取IV<br/>(前16字节)"]
        EXTRACT_IV --> EXTRACT_HMAC["提取HMAC<br/>(后64字节)"]
        EXTRACT_HMAC --> GET_ENCRYPTED["获取加密内容<br/>(去掉IV和HMAC)"]
        
        GET_ENCRYPTED --> AES_DECRYPT["AES-256-CBC解密"]
        AES_DECRYPT --> REMOVE_PADDING["移除PKCS7填充"]
        REMOVE_PADDING --> APPEND_PAGE["追加到解密数据"]
        
        APPEND_PAGE --> MORE_PAGES{"还有更多页面?"}
        MORE_PAGES -->|是| LOOP_PAGES
        MORE_PAGES -->|否| WRITE_FILE["写入解密后文件"]
        
        WRITE_FILE --> VERIFY_DB["验证数据库完整性<br/>(PRAGMA quick_check)"]
        VERIFY_DB --> VERIFY_OK{"验证通过?"}
        
        VERIFY_OK -->|是| SUCCESS([解密成功])
        VERIFY_OK -->|否| FAIL([解密失败])
    end
```

---

## 六、消息内容解码流程图

```mermaid
flowchart TD
    subgraph 消息解码["消息内容解码"]
        START_DECODE([开始解码]) --> CHECK_TYPE{"检查数据类型"}
        
        CHECK_TYPE -->|bytes| CHECK_ZSTD{"检测zstd魔数<br/>(0x28b52ffd)"}
        CHECK_TYPE -->|str| RETURN_STR(["返回原字符串"])
        
        CHECK_ZSTD -->|是zstd压缩| DECOMPRESS["zstd解压"]
        CHECK_ZSTD -->|否| DECODE_UTF8["UTF-8解码"]
        
        DECOMPRESS --> DECODE_UTF8
        DECODE_UTF8 --> DECODE_OK{"解码成功?"}
        
        DECODE_OK -->|是| RETURN_DECODE(["返回解码字符串"])
        DECODE_OK -->|否| REPLACE_CHAR["替换无效字符<br/>(errors='replace')"]
        REPLACE_CHAR --> RETURN_DECODE
    end
```

---

## 七、账号检测流程图

```mermaid
flowchart TD
    subgraph 账号检测["当前登录账号检测"]
        START_DETECT([开始检测]) --> FIND_PROCESS["查找微信进程<br/>(Weixin.exe/WeChat.exe)"]
        FIND_PROCESS --> PROCESS_FOUND{"找到进程?"}
        
        PROCESS_FOUND -->|否| NO_ACCOUNT([返回空])
        PROCESS_FOUND -->|是| ITERATE_PROCESS["遍历进程列表"]
        
        ITERATE_PROCESS --> GET_HANDLE["获取进程文件句柄"]
        GET_HANDLE --> ITERATE_FILES["遍历打开的文件"]
        
        ITERATE_FILES --> CHECK_PATH{"路径包含<br/>xwechat_files?"}
        CHECK_PATH -->|否| ITERATE_FILES
        CHECK_PATH -->|是| EXTRACT_ACCOUNT["提取账号ID"]
        
        EXTRACT_ACCOUNT --> PARSE_WXID["解析wxid<br/>(wxid_xxx_随机后缀)"]
        PARSE_WXID --> GET_DATA_PATH["获取数据目录路径"]
        GET_DATA_PATH --> PARSE_CONFIG["解析global_config.db<br/>(获取昵称)"]
        
        PARSE_CONFIG --> RETURN_RESULT(["返回账号信息<br/>{account_id, data_path, nickname}"])
    end
```

---

## 八、群聊选择与消息处理流程图

```mermaid
flowchart TD
    subgraph 群聊选择["群聊选择流程"]
        START_SELECT([开始]) --> DECRYPT_CONTACT["解密contact.db"]
        DECRYPT_CONTACT --> QUERY_GROUPS["查询群聊<br/>(WHERE username LIKE '%@chatroom')"]
        QUERY_GROUPS --> BUILD_LIST["构建群聊列表<br/>(群名称、群ID)"]
        BUILD_LIST --> DISPLAY_GROUPS["显示群聊列表<br/>(编号、群名、成员数)"]
        DISPLAY_GROUPS --> USER_SELECT["用户选择群聊"]
        USER_SELECT --> CACHE_GROUP["缓存群-表映射<br/>(group_table_cache.json)"]
        CACHE_GROUP --> START_MONITORING([开始监控该群])
    end
    
    subgraph 消息处理["消息处理流程"]
        RECEIVE_MSG([收到消息]) --> PARSE_CONTENT["解析消息内容"]
        PARSE_CONTENT --> DETECT_TYPE{"检测消息类型"}
        
        DETECT_TYPE -->|"文字消息"| TEXT_MSG["文字消息处理"]
        DETECT_TYPE -->|"图片 <img>"| IMG_MSG["过滤图片消息"]
        DETECT_TYPE -->|"表情 <emoji>"| EMOJI_MSG["过滤表情消息"]
        DETECT_TYPE -->|"视频 <videomsg>"| VIDEO_MSG["过滤视频消息"]
        DETECT_TYPE -->|"位置 <location>"| LOCATION_MSG["过滤位置消息"]
        DETECT_TYPE -->|"撤回 type=revokemsg"| REVOKE_MSG["过滤撤回消息"]
        
        TEXT_MSG --> FORMAT_TIME["格式化时间戳"]
        FORMAT_TIME --> GET_NICKNAME["获取发送者昵称"]
        GET_NICKNAME --> DISPLAY_CONSOLE["输出到控制台"]
        DISPLAY_CONSOLE --> SAVE_DB["保存到messages.db"]
        
        IMG_MSG --> FILTER_LOG["记录过滤日志"]
        EMOJI_MSG --> FILTER_LOG
        VIDEO_MSG --> FILTER_LOG
        LOCATION_MSG --> FILTER_LOG
        REVOKE_MSG --> FILTER_LOG
        
        FILTER_LOG --> NEXT_MSG([等待下一条消息])
        SAVE_DB --> NEXT_MSG
    end
```

---

## 九、自适应轮询算法流程图

```mermaid
flowchart TD
    subgraph 自适应轮询["自适应轮询算法"]
        START_ALGO([开始监控]) --> INIT_INTERVAL["初始间隔 = 1.0秒"]
        INIT_INTERVAL --> SLEEP_INTERVAL["等待当前间隔时间"]
        SLEEP_INTERVAL --> POLL_MESSAGES["轮询获取消息"]
        
        POLL_MESSAGES --> CHECK_NEW{"检测到新消息?"}
        
        CHECK_NEW -->|是| PROCESS_NEW["处理新消息"]
        PROCESS_NEW --> DECREASE_INTERVAL["缩短间隔<br/>interval = max(0.5, interval * 0.5)"]
        DECREASE_INTERVAL --> UPDATE_TIME["更新最新消息时间"]
        UPDATE_TIME --> SLEEP_INTERVAL
        
        CHECK_NEW -->|否| INCREASE_INTERVAL["延长间隔<br/>interval = min(5.0, interval * 1.5)"]
        INCREASE_INTERVAL --> CHECK_RECONNECT{"达到重连间隔?<br/>(60秒)"}
        
        CHECK_RECONNECT -->|是| RECONNECT["重连WCDB"]
        CHECK_RECONNECT -->|否| SLEEP_INTERVAL
        
        RECONNECT --> RECONNECT_OK{"重连成功?"}
        RECONNECT_OK -->|是| SLEEP_INTERVAL
        RECONNECT_OK -->|否| ERROR_HANDLE["错误处理"]
        ERROR_HANDLE --> SLEEP_INTERVAL
    end
    
    style DECREASE_INTERVAL fill:#90EE90
    style INCREASE_INTERVAL fill:#FFB6C1
```

---

## 十、文件读写与数据流图

```mermaid
flowchart LR
    subgraph 输入文件["输入文件"]
        WX_SESSION["session.db<br/>(加密)"]
        WX_CONTACT["contact.db<br/>(加密)"]
        WX_CONFIG["global_config.db"]
    end
    
    subgraph 处理过程["处理过程"]
        DECRYPT["解密模块"]
        PARSE["解析模块"]
        ENCODE["编码模块"]
    end
    
    subgraph 输出文件["输出文件"]
        LOCAL_MSG["messages.db<br/>(本地存储)"]
        KEY_FILE["key_store.json<br/>(密钥存储)"]
        CACHE_FILE["group_table_cache.json"]
        LOG_FILE["logs/*.log"]
    end
    
    WX_SESSION --> DECRYPT
    WX_CONTACT --> DECRYPT
    WX_CONFIG --> PARSE
    
    DECRYPT --> PARSE
    PARSE --> ENCODE
    
    ENCODE --> LOCAL_MSG
    ENCODE --> KEY_FILE
    ENCODE --> CACHE_FILE
    ENCODE --> LOG_FILE
```

---

## 十一、错误处理与重试机制流程图

```mermaid
flowchart TD
    subgraph 错误处理["错误处理机制"]
        ERROR_OCCUR([发生错误]) --> CLASSIFY_ERROR["错误分类"]
        
        CLASSIFY_ERROR --> PROC_ERROR{"进程管理错误?"}
        CLASSIFY_ERROR --> ACCOUNT_ERROR{"账号检测错误?"}
        CLASSIFY_ERROR --> KEY_ERROR{"密钥获取错误?"}
        CLASSIFY_ERROR --> DECRYPT_ERROR{"解密错误?"}
        CLASSIFY_ERROR --> WCDB_ERROR{"WCDB错误?"}
        
        PROC_ERROR -->|是| RETRY_PROC["重试进程操作<br/>(最多3次)"]
        ACCOUNT_ERROR -->|是| RETRY_ACCOUNT["重试账号检测<br/>(等待进程稳定)"]
        KEY_ERROR -->|是| FALLBACK_KEY["托底方案<br/>(V4失败→Hook)"]
        DECRYPT_ERROR -->|是| REFRESH_KEY["重新获取密钥"]
        WCDB_ERROR -->|是| RECONNECT_WCDB["重连WCDB"]
        
        RETRY_PROC --> RETRY_OK{"重试成功?"}
        RETRY_ACCOUNT --> RETRY_OK
        FALLBACK_KEY --> RETRY_OK
        REFRESH_KEY --> RETRY_OK
        RECONNECT_WCDB --> RETRY_OK
        
        RETRY_OK -->|是| CONTINUE([继续执行])
        RETRY_OK -->|否| LOG_ERROR["记录错误日志"]
        LOG_ERROR --> EXIT_ERROR([错误退出])
    end
```

---

## 十二、模块调用时序图

```mermaid
sequenceDiagram
    participant User as 用户
    participant CLI as 命令行
    participant Main as 主程序
    participant Proc as 进程模块
    participant Account as 账号模块
    participant Key as 密钥模块
    participant Decrypt as 解密模块
    participant WCDB as 实时监听
    participant Store as 存储模块
    
    User->>CLI: 运行程序
    CLI->>Main: 启动主程序
    
    Main->>Proc: 检测微信进程
    Proc-->>Main: 返回进程信息
    
    Main->>Account: 检测当前账号
    Account->>Proc: 获取进程句柄
    Proc-->>Account: 返回文件句柄
    Account-->>Main: 返回账号信息
    
    Main->>Key: 获取密钥
    Key->>Key: 检查密钥存储
    alt 密钥存在
        Key-->>Main: 返回已保存密钥
    else 密钥不存在
        Key->>Key: V4内存扫描
        Key-->>Main: 返回新密钥
    end
    
    Main->>Decrypt: 解密数据库
    Decrypt->>Decrypt: 解密contact.db
    Decrypt->>Decrypt: 解密session.db
    Decrypt-->>Main: 返回解密结果
    
    Main->>WCDB: 连接WCDB
    WCDB-->>Main: 返回连接句柄
    
    Main->>Store: 初始化存储
    Store-->>Main: 存储就绪
    
    loop 监控循环
        WCDB->>Main: 新消息通知
        Main->>Store: 保存消息
        Main->>CLI: 显示消息
        CLI->>User: 输出消息
    end
```

---

**文档生成时间：** 2026年7月20日 14:25  
**文档版本：** v1.0