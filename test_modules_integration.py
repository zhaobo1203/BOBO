# -*- coding: utf-8 -*-
"""
三模块联动集成测试脚本

测试流程：
步骤1: 模块1启动（微信消息监听）
  ├─ 1.1 检测微信进程
  ├─ 1.2 账号识别
  ├─ 1.3 密钥获取（Hook自动注入）
  ├─ 1.4 数据库解密
  ├─ 1.5 加载群列表数据（显示所有群供选择）
  ├─ 1.6 选择指定群聊
  ├─ 1.7 从数据库获取指定群的历史消息
  └─ 1.8 开始实时监听指定群（实时聊天消息）

步骤2: 历史消息写入 messages.db

步骤3: 模块2启动 → 更新A股数据 → 写入 a_stock.db

步骤4: 模块3启动 → 执行匹配 → 写入 stock_mentions.db

步骤5: 看板显示（含实时消息监听显示）

测试成功标准：
- 正常采集到群内历史消息
- 看板能看到群内实时消息
- A股数据库正常更新
- 看板内功能正常信息功能正常使用
"""

import sys
import os
import time
import sqlite3
import threading
import subprocess
import signal
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 确保日志目录存在
(PROJECT_ROOT / "logs").mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "logs" / "integration_test.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class ModulesIntegrationTest:
    """三模块联动集成测试"""
    
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.messages_db = PROJECT_ROOT / "data" / "messages.db"
        self.stock_db = PROJECT_ROOT / "data" / "a_stock_db" / "a_stock.db"
        self.mentions_db = PROJECT_ROOT / "data" / "stock_mentions.db"
        
        # 模块1状态
        self.monitor_instance = None
        self.selected_group = None
        self.selected_group_id = None
        self.selected_group_name = None
        self.monitor_thread = None
        self.stop_event = threading.Event()
        
        # 模块3进程
        self.api_process = None
        
        # 实时消息缓存
        self.realtime_messages: List[Dict] = []
        self.realtime_lock = threading.Lock()
        
        # 历史消息
        self.history_messages: List[Dict] = []
        
    def print_header(self):
        """显示测试头部"""
        print()
        print("=" * 70)
        print("  三模块联动集成测试")
        print("  模块1: 微信消息监听 | 模块2: A股数据更新 | 模块3: 股票分析")
        print("=" * 70)
        print()
        
    def print_step(self, step: str, status: str, detail: str = ""):
        """显示步骤状态"""
        symbols = {'done': '[OK]', 'doing': '[..]', 'fail': '[FAIL]', 'info': '[INFO]'}
        symbol = symbols.get(status, '[??]')
        line = f"  {symbol} {step}"
        if detail:
            line += f": {detail}"
        print(line)
        
    # ==================== 步骤0: 环境准备 ====================
    
    def step0_setup(self):
        """环境准备"""
        self.print_header()
        self.print_step("环境检查", "doing")
        
        # 确保目录存在
        (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
        (PROJECT_ROOT / "data").mkdir(exist_ok=True)
        
        # 检查关键文件
        required_files = [
            "src/simple_monitor.py",
            "src/stock_analysis/main.py",
            "src/a_stock_db/database.py",
        ]
        
        missing = []
        for f in required_files:
            if not (PROJECT_ROOT / f).exists():
                missing.append(f)
        
        if missing:
            self.print_step("环境检查", "fail", f"缺少文件: {missing}")
            return False
        
        self.print_step("环境检查", "done", "所有依赖文件存在")
        return True
    
    # ==================== 步骤1: 模块1启动 ====================
    
    def step1_start_module1(self):
        """启动模块1 - 微信消息监听"""
        print()
        self.print_step("模块1", "info", "微信消息监听启动中...")
        
        try:
            # 导入并实例化SimpleMonitor
            from simple_monitor import SimpleMonitor
            
            self.monitor_instance = SimpleMonitor()
            
            # 1.1 进程检测
            self.print_step("1.1 进程检测", "doing")
            if not self.monitor_instance.step1_detect_process():
                self.print_step("1.1 进程检测", "fail", "请先启动微信客户端")
                return False
            self.print_step("1.1 进程检测", "done", f"PID={self.monitor_instance.pid}")
            
            # 1.2 账号识别
            self.print_step("1.2 账号识别", "doing")
            if not self.monitor_instance.step2_detect_account():
                self.print_step("1.2 账号识别", "fail")
                return False
            self.print_step("1.2 账号识别", "done", self.monitor_instance.account_id)
            
            # 1.3 密钥获取（Hook自动注入）
            self.print_step("1.3 密钥获取", "doing", "Hook自动注入中...")
            if not self.monitor_instance.step3_get_key():
                self.print_step("1.3 密钥获取", "fail")
                return False
            self.print_step("1.3 密钥获取", "done", "Hook自动注入成功")
            
            # 1.4 数据库连接
            self.print_step("1.4 数据库连接", "doing")
            if not self.monitor_instance.step4_connect_db():
                self.print_step("1.4 数据库连接", "fail")
                return False
            self.print_step("1.4 数据库连接", "done", "静态解密成功")
            
            return True
            
        except Exception as e:
            self.print_step("模块1启动", "fail", str(e))
            logger.error(f"模块1启动异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤1.5: 加载群列表数据 ====================
    
    def step1_5_load_groups(self):
        """加载群列表数据"""
        print()
        self.print_step("1.5 加载群列表", "doing")
        
        groups = self._load_groups_data()
        if not groups:
            self.print_step("1.5 加载群列表", "fail", "未找到群聊")
            return False
        
        self.print_step("1.5 加载群列表", "done", f"共{len(groups)}个群聊")
        
        # 显示群聊列表
        print()
        print("  " + "=" * 60)
        print("  请选择要监控的群聊")
        print("  " + "=" * 60)
        print()
        
        for i, group in enumerate(groups[:30], 1):
            name = group.get('displayName', '') or group.get('username', '')
            name = name[:50] + '...' if len(name) > 50 else name
            print(f"    {i:2d}. {name}")
        
        if len(groups) > 30:
            print(f"\n  ... 还有 {len(groups) - 30} 个群聊")
        print()
        
        return groups
    
    def _load_groups_data(self) -> List[Dict]:
        """从数据库加载群列表"""
        groups = []
        
        # 从SessionTable获取群聊
        if self.monitor_instance.decrypted_session_db:
            try:
                conn = sqlite3.connect(self.monitor_instance.decrypted_session_db)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT username, displayName
                    FROM SessionTable
                    WHERE username LIKE '%@chatroom'
                    ORDER BY username
                """)
                for row in cursor.fetchall():
                    groups.append({
                        'username': row[0],
                        'displayName': row[1] or row[0]
                    })
                conn.close()
                logger.info(f"从SessionTable加载{len(groups)}个群聊")
            except Exception as e:
                logger.warning(f"从SessionTable加载群聊失败: {e}")
        
        # 从contact表补充群聊（去重）
        if self.monitor_instance.decrypted_contact_db:
            try:
                conn = sqlite3.connect(self.monitor_instance.decrypted_contact_db)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT username, nick_name, remark
                    FROM contact
                    WHERE username LIKE '%@chatroom'
                """)
                existing = {g['username'] for g in groups}
                for row in cursor.fetchall():
                    if row[0] not in existing:
                        groups.append({
                            'username': row[0],
                            'displayName': row[2] or row[1] or row[0]
                        })
                conn.close()
                logger.info(f"合并后共{len(groups)}个群聊")
            except Exception as e:
                logger.warning(f"从contact加载群聊失败: {e}")
        
        return groups
    
    # ==================== 步骤1.6: 选择指定群聊 ====================
    
    def step1_6_select_group(self, groups: List[Dict], auto_select: int = None) -> bool:
        """选择指定群聊"""
        self.print_step("1.6 选择群聊", "doing")
        
        try:
            # 如果提供了自动选择编号，直接使用
            if auto_select is not None:
                idx = auto_select - 1
            else:
                choice = input("  请输入群聊编号: ").strip()
                if not choice:
                    self.print_step("1.6 选择群聊", "fail", "未输入")
                    return False
                idx = int(choice) - 1
            
            if 0 <= idx < len(groups):
                self.selected_group = groups[idx]
                self.selected_group_id = self.selected_group.get('username', '')
                self.selected_group_name = self.selected_group.get('displayName', '')
                self.print_step("1.6 选择群聊", "done", self.selected_group_name)
                return True
            else:
                self.print_step("1.6 选择群聊", "fail", "编号超出范围")
                return False
                
        except ValueError:
            self.print_step("1.6 选择群聊", "fail", "无效输入")
            return False
    
    # ==================== 步骤1.7: 获取历史消息 ====================
    
    def step1_7_get_history_messages(self) -> bool:
        """从数据库获取指定群的历史消息"""
        print()
        self.print_step("1.7 获取历史消息", "doing")
        
        try:
            messages = self._fetch_history_messages(self.selected_group_id)
            self.history_messages = messages
            
            self.print_step("1.7 获取历史消息", "done", f"获取{len(messages)}条历史消息")
            
            # 显示最近5条历史消息
            if messages:
                print()
                print("  最近历史消息预览:")
                print("  " + "-" * 50)
                for msg in messages[:5]:
                    time_str = msg['time'].strftime("%H:%M:%S") if isinstance(msg['time'], datetime) else str(msg['time'])
                    sender = msg['sender'][:10] if len(msg['sender']) > 10 else msg['sender']
                    content = msg['content'][:40] + '...' if len(msg['content']) > 40 else msg['content']
                    print(f"    [{time_str}] {sender}: {content}")
                print()
            
            return True
            
        except Exception as e:
            self.print_step("1.7 获取历史消息", "fail", str(e))
            logger.error(f"获取历史消息异常: {e}", exc_info=True)
            return False
    
    def _fetch_history_messages(self, group_id: str) -> List[Dict]:
        """从数据库读取历史消息"""
        messages = []
        
        try:
            if self.monitor_instance.decrypted_session_db:
                conn = sqlite3.connect(self.monitor_instance.decrypted_session_db)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT localId, createTime, content, senderId, type
                    FROM SessionContent
                    WHERE strTalker = ?
                    ORDER BY createTime DESC
                    LIMIT 100
                """, (group_id,))
                
                rows = cursor.fetchall()
                conn.close()
                
                for row in rows:
                    try:
                        local_id = row['localId']
                        create_time = row['createTime']
                        content = row['content']
                        sender_id = row['senderId']
                        msg_type = row['type']
                        
                        if not content or not content.strip():
                            continue
                        
                        # 解析时间
                        if isinstance(create_time, (int, float)):
                            send_time = datetime.fromtimestamp(create_time)
                        else:
                            send_time = datetime.now()
                        
                        # 获取发送者昵称
                        sender_name = self._get_sender_name(sender_id) if sender_id else '未知'
                        
                        messages.append({
                            'local_id': local_id,
                            'time': send_time,
                            'sender': sender_name,
                            'sender_id': sender_id,
                            'content': content,
                            'type': msg_type
                        })
                        
                    except Exception as e:
                        logger.warning(f"解析消息失败: {e}")
                
                logger.info(f"从群{self.selected_group_name}获取{len(messages)}条历史消息")
                
        except Exception as e:
            logger.error(f"读取历史消息失败: {e}", exc_info=True)
        
        return messages
    
    def _get_sender_name(self, sender_id: str) -> str:
        """获取发送者昵称"""
        if not sender_id:
            return '未知'
        
        # 尝试从contact表获取
        try:
            if self.monitor_instance.decrypted_contact_db:
                conn = sqlite3.connect(self.monitor_instance.decrypted_contact_db)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT nick_name, remark
                    FROM contact
                    WHERE username = ?
                """, (sender_id,))
                row = cursor.fetchone()
                conn.close()
                
                if row:
                    return row[1] or row[0] or sender_id
        except:
            pass
        
        return sender_id
    
    # ==================== 步骤1.8: 开始实时监听 ====================
    
    def step1_8_start_realtime_monitor(self) -> bool:
        """开始实时监听指定群"""
        print()
        self.print_step("1.8 实时监听", "doing")
        
        try:
            self.monitor_thread = threading.Thread(
                target=self._realtime_monitor_loop,
                daemon=True
            )
            self.monitor_thread.start()
            
            self.print_step("1.8 实时监听", "done", f"群: {self.selected_group_name}")
            return True
            
        except Exception as e:
            self.print_step("1.8 实时监听", "fail", str(e))
            return False
    
    def _realtime_monitor_loop(self):
        """实时监听循环"""
        from wechat_decrypt_tool.message_storage import MessageStorage
        
        storage = MessageStorage(str(self.messages_db))
        last_check_time = time.time()
        
        logger.info(f"开始实时监听群: {self.selected_group_name}")
        
        while not self.stop_event.is_set():
            try:
                # 轮询检查新消息
                new_messages = self._poll_new_messages(self.selected_group_id, last_check_time)
                
                for msg in new_messages:
                    # 保存到数据库
                    storage.save_message(
                        sender_nickname=msg['sender'],
                        message_content=msg['content'],
                        send_time=msg['time'],
                        group_name=self.selected_group_name,
                        group_id=self.selected_group_id
                    )
                    
                    # 添加到实时消息缓存
                    with self.realtime_lock:
                        self.realtime_messages.append(msg)
                        if len(self.realtime_messages) > 100:
                            self.realtime_messages = self.realtime_messages[-100:]
                    
                    logger.info(f"新消息: [{msg['sender']}] {msg['content'][:50]}")
                    
                    # 触发增量匹配
                    self._trigger_incremental_match()
                
                last_check_time = time.time()
                
            except Exception as e:
                logger.error(f"实时监听异常: {e}")
            
            time.sleep(3)  # 3秒轮询间隔
    
    def _poll_new_messages(self, group_id: str, since_time: float) -> List[Dict]:
        """轮询获取新消息"""
        messages = []
        
        try:
            if self.monitor_instance.decrypted_session_db:
                conn = sqlite3.connect(self.monitor_instance.decrypted_session_db)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 获取最近的消息
                cursor.execute("""
                    SELECT localId, createTime, content, senderId, type
                    FROM SessionContent
                    WHERE strTalker = ?
                    ORDER BY createTime DESC
                    LIMIT 10
                """, (group_id,))
                
                rows = cursor.fetchall()
                conn.close()
                
                existing_ids = {m.get('local_id') for m in self.realtime_messages}
                
                for row in rows:
                    local_id = row['localId']
                    create_time = row['createTime']
                    content = row['content']
                    sender_id = row['senderId']
                    
                    if not content or not content.strip():
                        continue
                    
                    if local_id in existing_ids:
                        continue
                    
                    # 只处理最近10秒的消息
                    if isinstance(create_time, (int, float)):
                        if create_time < since_time - 10:
                            continue
                        msg_time = datetime.fromtimestamp(create_time)
                    else:
                        continue
                    
                    sender_name = self._get_sender_name(sender_id) if sender_id else '未知'
                    
                    messages.append({
                        'local_id': local_id,
                        'time': msg_time,
                        'sender': sender_name,
                        'sender_id': sender_id,
                        'content': content
                    })
                
        except Exception as e:
            logger.warning(f"轮询新消息失败: {e}")
        
        return messages
    
    def _trigger_incremental_match(self):
        """触发增量匹配"""
        try:
            requests.post("http://localhost:8000/api/incremental-refresh", timeout=5)
        except:
            pass
    
    # ==================== 步骤2: 保存历史消息 ====================
    
    def step2_save_history_messages(self) -> bool:
        """保存历史消息到数据库"""
        print()
        self.print_step("步骤2", "info", "保存历史消息...")
        self.print_step("历史消息入库", "doing")
        
        try:
            from wechat_decrypt_tool.message_storage import MessageStorage
            
            storage = MessageStorage(str(self.messages_db))
            
            saved_count = 0
            for msg in self.history_messages:
                try:
                    storage.save_message(
                        sender_nickname=msg['sender'],
                        message_content=msg['content'],
                        send_time=msg['time'],
                        group_name=self.selected_group_name,
                        group_id=self.selected_group_id,
                        sender_id=msg.get('sender_id')
                    )
                    saved_count += 1
                except Exception as e:
                    logger.warning(f"保存消息失败: {e}")
            
            self.print_step("历史消息入库", "done", f"保存{saved_count}条")
            return True
            
        except Exception as e:
            self.print_step("历史消息入库", "fail", str(e))
            return False
    
    # ==================== 步骤3: 模块2启动 ====================
    
    def step3_start_module2(self) -> bool:
        """启动模块2 - A股数据更新"""
        print()
        self.print_step("步骤3", "info", "模块2 - A股数据更新")
        
        try:
            from a_stock_db.data_sources import DataSourceManager
            from a_stock_db.database import AStockDatabase
            
            self.print_step("A股数据获取", "doing")
            
            manager = DataSourceManager()
            result = manager.fetch_with_fallback()
            
            if not result.success:
                self.print_step("A股数据获取", "fail", result.error_message)
                return False
            
            self.print_step("A股数据获取", "done", f"获取{result.count}只股票")
            
            # 更新数据库
            self.print_step("A股数据写入", "doing")
            db = AStockDatabase()
            stocks_data = [(s.code, s.name) for s in result.stocks]
            stats = db.update_stocks(stocks_data, source=result.source_name)
            
            self.print_step("A股数据写入", "done", 
                f"总数{stats.total_count}, 新增{stats.added_count}")
            
            return True
            
        except Exception as e:
            self.print_step("模块2启动", "fail", str(e))
            logger.error(f"模块2启动异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤4: 模块3启动 ====================
    
    def step4_start_module3(self) -> bool:
        """启动模块3 - 股票分析服务"""
        print()
        self.print_step("步骤4", "info", "模块3 - 股票分析服务")
        
        try:
            # 启动API服务
            self.print_step("API服务启动", "doing")
            
            self.api_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn",
                 "src.stock_analysis.main:app",
                 "--host", "0.0.0.0",
                 "--port", "8000"],
                cwd=str(self.project_root),
            )
            
            # 等待服务就绪
            for i in range(30):
                try:
                    resp = requests.get("http://localhost:8000/api/health", timeout=2)
                    if resp.json().get("status") == "ok":
                        self.print_step("API服务启动", "done", "http://localhost:8000")
                        break
                except:
                    pass
                time.sleep(1)
            else:
                self.print_step("API服务启动", "fail", "服务未就绪")
                return False
            
            # 触发全量匹配
            self.print_step("全量匹配", "doing")
            try:
                resp = requests.post("http://localhost:8000/api/full-refresh", timeout=60)
                result = resp.json()
                self.print_step("全量匹配", "done", 
                    f"消息{result.get('total_messages', 0)}条, 提及{result.get('total_mentions', 0)}条")
            except Exception as e:
                self.print_step("全量匹配", "info", str(e))
            
            return True
            
        except Exception as e:
            self.print_step("模块3启动", "fail", str(e))
            logger.error(f"模块3启动异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤5: 看板显示 ====================
    
    def step5_show_dashboard(self):
        """显示看板（含实时消息）"""
        print()
        print("=" * 70)
        print("  看板监控（按Ctrl+C退出）")
        print("=" * 70)
        print()
        
        try:
            while not self.stop_event.is_set():
                try:
                    # 清屏并移动光标到顶部
                    print("\033[2J\033[H", end="")
                    
                    # 获取统计数据
                    try:
                        daily = requests.get("http://localhost:8000/api/stats/daily", timeout=5).json()
                        weekly = requests.get("http://localhost:8000/api/stats/weekly", timeout=5).json()
                    except:
                        daily = {}
                        weekly = {}
                    
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 打印看板头部
                    print()
                    print("+" + "-" * 68 + "+")
                    print(f"|  股票监控数据分析看板  {now:<44}|")
                    print("+" + "-" * 68 + "+")
                    
                    # 日统计
                    print(f"|  【日统计】{daily.get('period', '')}  当日股票 {daily.get('stock_count', 0)} 只")
                    stocks = daily.get('stocks', [])[:5]
                    if stocks:
                        print(f"|  {'排名':<4} {'股票名称':<12} {'代码':<10} {'提及次数':<8}")
                        print("|  " + "-" * 50)
                        for i, stock in enumerate(stocks, 1):
                            name = stock.get('name', '')[:10]
                            code = stock.get('code', '')
                            count = stock.get('mention_count', 0)
                            print(f"|  {i:<4} {name:<12} {code:<10} {count:<8}")
                    print("|")
                    
                    # 实时消息显示
                    print("+" + "-" * 68 + "+")
                    print(f"|  【实时消息监听】{self.selected_group_name}")
                    print("|  " + "-" * 60)
                    
                    with self.realtime_lock:
                        recent_msgs = self.realtime_messages[-10:]
                    
                    if recent_msgs:
                        for msg in recent_msgs[-5:]:
                            time_str = msg['time'].strftime("%H:%M:%S") if isinstance(msg['time'], datetime) else str(msg['time'])
                            sender = msg['sender'][:8] if len(msg['sender']) > 8 else msg['sender']
                            content = msg['content'][:45] + '...' if len(msg['content']) > 45 else msg['content']
                            print(f"|  [{time_str}] {sender}: {content}")
                    else:
                        print("|  等待新消息...")
                    
                    print("+" + "-" * 68 + "+")
                    print("|  按 Ctrl+C 退出")
                    print("+" + "-" * 68 + "+")
                    
                except Exception as e:
                    print(f"|  看板更新失败: {e}")
                
                time.sleep(5)  # 5秒刷新
                
        except KeyboardInterrupt:
            print("\n\n用户中断，正在退出...")
    
    # ==================== 清理 ====================
    
    def cleanup(self):
        """清理资源"""
        self.stop_event.set()
        
        if self.api_process:
            try:
                self.api_process.terminate()
                self.api_process.wait(timeout=5)
            except:
                pass
        
        print("\n测试结束")
    
    # ==================== 主运行方法 ====================
    
    def run(self):
        """执行完整测试流程"""
        try:
            # 步骤0: 环境准备
            if not self.step0_setup():
                return False
            
            # 步骤1: 模块1启动
            if not self.step1_start_module1():
                return False
            
            # 步骤1.5: 加载群列表
            groups = self.step1_5_load_groups()
            if not groups:
                return False
            
            # 步骤1.6: 选择群聊（自动选择第1个群）
            if not self.step1_6_select_group(groups, auto_select=1):
                return False
            
            # 步骤1.7: 获取历史消息
            if not self.step1_7_get_history_messages():
                return False
            
            # 步骤1.8: 开始实时监听
            if not self.step1_8_start_realtime_monitor():
                return False
            
            # 步骤2: 保存历史消息
            if not self.step2_save_history_messages():
                return False
            
            # 步骤3: 模块2启动
            if not self.step3_start_module2():
                return False
            
            # 步骤4: 模块3启动
            if not self.step4_start_module3():
                return False
            
            # 步骤5: 看板显示
            self.step5_show_dashboard()
            
            return True
            
        except KeyboardInterrupt:
            print("\n用户中断")
            return False
        except Exception as e:
            logger.error(f"测试异常: {e}", exc_info=True)
            return False
        finally:
            self.cleanup()


def main():
    """主入口"""
    test = ModulesIntegrationTest()
    success = test.run()
    
    if success:
        print("\n测试成功完成！")
    else:
        print("\n测试失败")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())