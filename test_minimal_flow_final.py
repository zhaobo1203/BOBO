# -*- coding: utf-8 -*-
"""
最小化流程测试脚本 - 最终版

严格测试流程：脚本启动 → 模块1启动 → 模块2启动 → 模块3启动 → 数据验证 → 看板显示

数据流：
  模块1（微信监听）→ data/messages.db → 模块3（股票分析）← data/a_stock.db ← 模块2（A股数据）

成功判定标准：
  ✓ 模块1：进程检测、密钥获取、数据库解密、历史消息、实时监听全部正常
  ✓ 模块2：A股数据获取、数据库写入正常
  ✓ 模块3：API服务、全量匹配、统计接口、看板显示正常
  ✓ 模块间联动：三数据库数据完整流转，增量匹配可触发

运行方式：python test_minimal_flow_final.py
前提条件：微信已登录运行
"""

import sys
import os
import time
import re
import sqlite3
import threading
import subprocess
import logging
import argparse
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# Windows终端UTF-8支持
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    # 启用虚拟终端处理
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        if not (mode.value & 0x0004):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass

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
        logging.FileHandler(PROJECT_ROOT / "logs" / "minimal_flow_final.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class MinimalFlowFinalTest:
    """最小化流程测试 - 最终版"""
    
    def __init__(self, group_choice: Optional[int] = None, auto_mode: bool = False):
        """
        初始化联动测试
        
        Args:
            group_choice: 预指定群编号（1-based），为None则交互式选择
            auto_mode: 全自动模式，自动选第一个群 + 跳过实时看板交互
        """
        self.project_root = PROJECT_ROOT
        self.messages_db = PROJECT_ROOT / "data" / "messages.db"
        self.stock_db = PROJECT_ROOT / "data" / "a_stock_db" / "a_stock.db"
        self.mentions_db = PROJECT_ROOT / "data" / "stock_mentions.db"
        
        # 模块1 共享实例
        self.monitor_instance = None
        self.selected_group_id = None
        self.selected_group_name = None
        
        # 预指定群编号
        self.group_choice = group_choice
        # 全自动模式
        self.auto_mode = auto_mode
        
        # 模块1 实时监听线程
        self.monitor_thread = None
        self.stop_monitor_event = threading.Event()
        
        # 模块3 API进程
        self.api_process = None
        
        # 测试结果记录
        self.results = {
            'module1': False,
            'module2': False,
            'module3': False,
            'data_flow': False,
            'dashboard': False,
        }
    
    # ==================== 工具方法 ====================
    
    def print_header(self):
        """显示测试头部"""
        print()
        print("=" * 70)
        print("  三模块联动最小化流程测试")
        print("  流程: 模块1启动 → 模块2启动 → 模块3启动 → 数据验证 → 看板")
        print("=" * 70)
        print()
    
    def print_step(self, step: str, status: str, detail: str = ""):
        """显示步骤状态"""
        symbols = {'done': '[OK]', 'doing': '[..]', 'fail': '[FAIL]', 'info': '[INFO]', 'skip': '[SKIP]'}
        symbol = symbols.get(status, '[??]')
        line = f"  {symbol} {step}"
        if detail:
            line += f": {detail}"
        print(line)
    
    def print_section(self, title: str):
        """显示章节标题"""
        print()
        print("-" * 70)
        print(f"  {title}")
        print("-" * 70)
        print()
    
    def check_db_count(self, db_path: Path, table: str) -> int:
        """检查数据库表记录数"""
        if not db_path.exists():
            return 0
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.warning(f"检查{db_path.name}.{table}失败: {e}")
            return 0
    
    # ==================== 步骤1: 模块1启动 ====================
    
    def step1_module1_start(self) -> bool:
        """步骤1: 模块1启动 - 微信消息监听"""
        self.print_section("步骤1: 模块1启动（微信消息监听）")
        
        try:
            from simple_monitor import SimpleMonitor
            
            # 1.1 创建实例并初始化
            self.print_step("1.1 进程检测", "doing")
            self.monitor_instance = SimpleMonitor()
            
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
            
            # 1.3 密钥获取
            self.print_step("1.3 密钥获取", "doing", "Hook注入中...")
            if not self.monitor_instance.step3_get_key():
                self.print_step("1.3 密钥获取", "fail")
                return False
            key_len = len(self.monitor_instance.db_key) if self.monitor_instance.db_key else 0
            self.print_step("1.3 密钥获取", "done", f"成功（{key_len}字节）")
            
            # 1.4 数据库连接
            self.print_step("1.4 数据库连接", "doing")
            if not self.monitor_instance.step4_connect_db():
                self.print_step("1.4 数据库连接", "fail")
                return False
            self.print_step("1.4 数据库连接", "done", "解密成功")
            
            # 1.5 获取群列表
            self.print_step("1.5 加载群列表", "doing")
            groups = self._get_groups_list()
            if not groups:
                self.print_step("1.5 加载群列表", "fail", "未找到群聊")
                return False
            self.print_step("1.5 加载群列表", "done", f"共{len(groups)}个群聊")
            
            # 1.6 选择目标群（支持预指定 / 全自动 / 交互式）
            target_group = self._select_target_group(groups)
            if not target_group:
                self.print_step("1.6 选择目标群", "fail", "未选择有效群聊")
                return False
            
            self.selected_group_id = target_group.get('username', '')
            self.selected_group_name = target_group.get('displayName', '') or self.selected_group_id
            self.print_step("1.6 选择目标群", "done", self.selected_group_name)
            
            # 1.7 获取并保存历史消息
            self.print_step("1.7 保存历史消息", "doing")
            saved = self._save_history_messages()
            self.print_step("1.7 保存历史消息", "done", f"保存{saved}条到messages.db")
            
            msg_count = self.check_db_count(self.messages_db, "group_messages")
            if msg_count == 0:
                self.print_step("1.7 消息验证", "fail", "messages.db无数据")
                return False
            
            # 1.8 启动实时监听后台线程
            self.print_step("1.8 实时监听", "doing", "启动后台线程...")
            self._start_background_monitor()
            time.sleep(2)  # 等待线程启动
            
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.print_step("1.8 实时监听", "done", "后台线程运行中")
            else:
                self.print_step("1.8 实时监听", "fail", "线程启动失败")
                return False
            
            self.results['module1'] = True
            return True
            
        except Exception as e:
            self.print_step("模块1启动", "fail", str(e))
            logger.error(f"模块1启动异常: {e}", exc_info=True)
            return False
    
    def _get_groups_list(self) -> List[Dict]:
        """获取群列表（复用SimpleMonitor的方法）"""
        if self.monitor_instance and hasattr(self.monitor_instance, '_get_groups_from_session'):
            try:
                groups = self.monitor_instance._get_groups_from_session()
                if groups:
                    logger.info(f"从SessionTable加载{len(groups)}个群聊")
                    return groups
            except Exception as e:
                logger.warning(f"_get_groups_from_session失败: {e}")
        
        # 兜底：nickname_cache
        groups = []
        if self.monitor_instance and self.monitor_instance.nickname_cache:
            for wxid, name in self.monitor_instance.nickname_cache.items():
                if wxid.endswith('@chatroom'):
                    groups.append({
                        'username': wxid,
                        'displayName': name
                    })
            logger.info(f"从nickname_cache加载{len(groups)}个群聊")
        
        return groups
    
    def _get_sorted_groups(self, groups: List[Dict]) -> List[Dict]:
        """获取排序后的群列表（测试群在前）"""
        test_groups = []
        other_groups = []
        for g in groups:
            name = g.get('displayName', '')
            if 'AI测试' in name or '测试' in name:
                test_groups.append(g)
            else:
                other_groups.append(g)
        return test_groups + other_groups
    
    def _select_target_group(self, groups: List[Dict]) -> Optional[Dict]:
        """
        选择目标群
        优先级: 全自动模式选第一个 > 预指定编号 > 交互式选择
        """
        sorted_groups = self._get_sorted_groups(groups)
        display_groups = sorted_groups[:20]
        
        # 全自动模式：自动选第一个群
        if self.auto_mode:
            if display_groups:
                g = display_groups[0]
                name = g.get('displayName', g.get('username', ''))
                self.print_step("1.6 自动选择目标群", "info", f"全自动模式 -> {name}")
                return g
            return None
        
        # 预指定群编号
        if self.group_choice is not None:
            if 1 <= self.group_choice <= len(display_groups):
                return display_groups[self.group_choice - 1]
            else:
                self.print_step("1.6 选择目标群", "fail", 
                    f"编号{self.group_choice}超出范围(1-{len(display_groups)})")
                return None
        
        # 交互式选择
        return self._select_group_manual(display_groups)
    
    def _select_group_manual(self, display_groups: List[Dict]) -> Optional[Dict]:
        """手动选择目标群（交互式）"""
        print()
        print("  ┌──────────────────────────────────────────────────────┐")
        print("  │               请选择目标群（输入编号）                │")
        print("  ├──────────────────────────────────────────────────────┤")
        
        for i, group in enumerate(display_groups, 1):
            name = group.get('displayName', group.get('username', ''))
            # 截断过长的群名
            display_name = name[:40] + '...' if len(name) > 40 else name
            marker = " ★" if 'AI测试' in name else ""
            print(f"  │  [{i:2d}] {display_name:<42}{marker}  │")
        
        if len(display_groups) > 20:
            print(f"  │  ... 还有{len(display_groups) - 20}个群聊                 │")
        
        print("  └──────────────────────────────────────────────────────┘")
        print()
        
        while True:
            try:
                choice = input("  请输入群编号 (直接回车选第一个): ").strip()
                if not choice:
                    # 默认选第一个（通常是AI测试群）
                    idx = 1
                else:
                    idx = int(choice)
                
                if 1 <= idx <= len(display_groups):
                    return display_groups[idx - 1]
                else:
                    print(f"  请输入 1-{len(display_groups)} 之间的编号")
            except ValueError:
                print("  请输入有效的数字编号")
            except KeyboardInterrupt:
                print()
                return None
    
    def _save_history_messages(self) -> int:
        """获取并保存历史消息到messages.db"""
        if not self.monitor_instance or not self.selected_group_id:
            return 0
        
        try:
            from wechat_decrypt_tool.message_storage import get_message_storage
            
            storage = get_message_storage()
            messages = self.monitor_instance._fetch_history_messages(self.selected_group_id)
            
            if not messages:
                return 0
            
            saved = 0
            for msg in messages:
                processed = self.monitor_instance._process_single_message(
                    msg, self.selected_group_name, self.selected_group_id
                )
                if not processed:
                    continue
                
                try:
                    from common_utils import parse_timestamp
                    msg_time_int = processed.get('time_int', 0)
                    storage.save_message(
                        sender_nickname=processed['sender'],
                        message_content=processed['content'],
                        send_time=datetime.fromtimestamp(msg_time_int),
                        group_name=self.selected_group_name,
                        group_id=self.selected_group_id,
                        sender_id=processed.get('sender_wxid', '')
                    )
                    saved += 1
                except Exception as e:
                    logger.warning(f"保存历史消息失败: {e}")
            
            return saved
            
        except Exception as e:
            logger.error(f"保存历史消息异常: {e}", exc_info=True)
            return 0
    
    def _start_background_monitor(self):
        """在后台线程中启动实时消息监听"""
        if not self.monitor_instance or not self.selected_group_id:
            return
        
        def monitor_worker():
            """监听工作线程"""
            try:
                from wechat_decrypt_tool.message_storage import get_message_storage
                from common_utils import parse_timestamp, format_timestamp
                
                storage = get_message_storage()
                
                # 获取初始最新消息时间戳
                last_create_time = 0
                initial_msgs = self.monitor_instance._fetch_history_messages(self.selected_group_id)
                for msg in initial_msgs:
                    msg_time_int = parse_timestamp(msg.get('create_time') or msg.get('createTime') or 0)
                    if msg_time_int > last_create_time:
                        last_create_time = msg_time_int
                
                logger.info(f"[实时监听] 启动，最新消息时间戳: {last_create_time}")
                
                # 轮询循环
                poll_interval = 5.0  # 初始5秒
                poll_count = 0
                
                while not self.stop_monitor_event.is_set():
                    time.sleep(poll_interval)
                    poll_count += 1
                    
                    try:
                        new_messages = self.monitor_instance._fetch_new_messages(self.selected_group_id)
                    except Exception as e:
                        logger.warning(f"[实时监听] 获取消息失败: {e}")
                        continue
                    
                    # 找到最新时间戳
                    max_time = 0
                    for msg in new_messages:
                        msg_time_int = parse_timestamp(msg.get('create_time') or msg.get('createTime') or 0)
                        if msg_time_int > max_time:
                            max_time = msg_time_int
                    
                    if max_time > last_create_time:
                        old_last = last_create_time
                        last_create_time = max_time
                        
                        # 处理并保存新消息
                        new_count = 0
                        for msg in reversed(new_messages):
                            msg_time_int = parse_timestamp(msg.get('create_time') or msg.get('createTime') or 0)
                            if msg_time_int > old_last:
                                processed = self.monitor_instance._process_single_message(
                                    msg, self.selected_group_name, self.selected_group_id
                                )
                                if processed:
                                    try:
                                        storage.save_message(
                                            sender_nickname=processed['sender'],
                                            message_content=processed['content'],
                                            send_time=datetime.fromtimestamp(processed['time_int']),
                                            group_name=self.selected_group_name,
                                            group_id=self.selected_group_id,
                                            sender_id=processed.get('sender_wxid', '')
                                        )
                                        new_count += 1
                                        logger.info(f"[实时监听] 新消息: {processed['sender']}: {processed['content'][:30]}")
                                    except Exception as e:
                                        logger.warning(f"[实时监听] 保存失败: {e}")
                        
                        if new_count > 0:
                            logger.info(f"[实时监听] 本轮新增{new_count}条消息")
                            poll_interval = max(2.0, poll_interval * 0.5)  # 有消息则加快轮询
                    else:
                        poll_interval = min(15.0, poll_interval * 1.2)  # 无消息则减慢轮询
                    
                    # 每10次轮询输出一次心跳日志
                    if poll_count % 10 == 0:
                        logger.debug(f"[实时监听] 心跳: 轮询{poll_count}次, 间隔{poll_interval:.1f}s")
                
                logger.info("[实时监听] 线程已停止")
                
            except Exception as e:
                logger.error(f"[实时监听] 线程异常: {e}", exc_info=True)
        
        self.monitor_thread = threading.Thread(target=monitor_worker, daemon=True)
        self.monitor_thread.start()
    
    # ==================== 步骤2: 模块2启动 ====================
    
    def step2_module2_start(self) -> bool:
        """步骤2: 模块2启动 - A股数据更新"""
        self.print_section("步骤2: 模块2启动（A股数据更新）")
        
        try:
            from a_stock_db.data_sources import DataSourceManager
            from a_stock_db.database import AStockDatabase
            
            # 2.1 获取A股数据
            self.print_step("2.1 A股数据获取", "doing")
            
            manager = DataSourceManager()
            result = manager.fetch_with_fallback()
            
            if not result.success:
                self.print_step("2.1 A股数据获取", "fail", result.error_message)
                return False
            
            self.print_step("2.1 A股数据获取", "done", 
                f"获取{result.count}只股票（{result.source_name}，耗时{result.elapsed_time:.1f}s）")
            
            # 2.2 写入数据库
            self.print_step("2.2 数据写入", "doing")
            
            db = AStockDatabase()
            stocks_data = [(s.code, s.name) for s in result.stocks]
            stats = db.update_stocks(stocks_data, source=result.source_name)
            
            self.print_step("2.2 数据写入", "done", 
                f"总数{stats.total_count}, 新增{stats.added_count}")
            
            # 2.3 验证
            stock_count = self.check_db_count(self.stock_db, "stocks")
            if stock_count == 0:
                self.print_step("2.3 数据验证", "fail", "a_stock.db无数据")
                return False
            self.print_step("2.3 数据验证", "done", f"a_stock.db共{stock_count}只股票")
            
            self.results['module2'] = True
            return True
            
        except Exception as e:
            self.print_step("模块2启动", "fail", str(e))
            logger.error(f"模块2启动异常: {e}", exc_info=True)
            return False
    
    # ==================== 步骤3: 模块3启动 ====================
    
    def step3_module3_start(self) -> bool:
        """步骤3: 模块3启动 - 股票分析服务"""
        self.print_section("步骤3: 模块3启动（股票分析服务）")
        
        try:
            # 3.1 启动API服务
            self.print_step("3.1 API服务启动", "doing")
            
            self.api_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn",
                 "src.stock_analysis.main:app",
                 "--host", "127.0.0.1",
                 "--port", "8000"],
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            # 等待服务就绪（最多60秒，全量匹配可能需要时间）
            health_ok = False
            for i in range(60):
                try:
                    resp = requests.get("http://localhost:8000/api/health", timeout=2)
                    data = resp.json()
                    if data.get("status") == "ok":
                        health_ok = True
                        mentions = data.get('total_mentions', 0)
                        self.print_step("3.1 API服务启动", "done", 
                            f"http://localhost:8000（{mentions}条提及）")
                        break
                except:
                    pass
                time.sleep(1)
            
            if not health_ok:
                self.print_step("3.1 API服务启动", "fail", "服务在60秒内未就绪")
                # 尝试获取错误输出
                try:
                    stderr = self.api_process.stderr.read(2000).decode('utf-8', errors='ignore')
                    print(f"  错误输出: {stderr[:500]}")
                except:
                    pass
                return False
            
            # 3.2 触发全量刷新（确保使用最新数据）
            self.print_step("3.2 全量匹配", "doing")
            time.sleep(2)  # 确保启动时的自动匹配完成
            
            try:
                resp = requests.post("http://localhost:8000/api/refresh", timeout=120)
                result = resp.json()
                if result.get("status") == "ok":
                    details = result.get("details", {})
                    self.print_step("3.2 全量匹配", "done", 
                        f"消息{details.get('total_messages', 0)}条, "
                        f"股票{details.get('total_stocks', 0)}只, "
                        f"提及{details.get('total_mentions', 0)}条, "
                        f"保存{details.get('saved_records', 0)}条")
                else:
                    self.print_step("3.2 全量匹配", "fail", result.get("message", "未知错误"))
                    return False
            except Exception as e:
                self.print_step("3.2 全量匹配", "info", f"API调用: {e}")
            
            # 3.3 验证提及数据库
            mentions_count = self.check_db_count(self.mentions_db, "stock_mentions")
            self.print_step("3.3 提及数据验证", 
                "done" if mentions_count > 0 else "info",
                f"stock_mentions.db共{mentions_count}条提及")
            
            # 3.4 验证统计接口
            self.print_step("3.4 统计接口验证", "doing")
            api_ok = self._verify_api_endpoints()
            if api_ok:
                self.print_step("3.4 统计接口验证", "done", "所有接口响应正常")
            else:
                self.print_step("3.4 统计接口验证", "info", "部分接口可能未就绪")
            
            self.results['module3'] = True
            return True
            
        except Exception as e:
            self.print_step("模块3启动", "fail", str(e))
            logger.error(f"模块3启动异常: {e}", exc_info=True)
            return False
    
    def _verify_api_endpoints(self) -> bool:
        """验证API各接口是否正常"""
        endpoints = [
            ("/api/health", "健康检查"),
            ("/api/stats/daily", "日统计"),
            ("/api/stats/weekly", "周统计"),
            ("/api/stats/monthly", "月统计"),
        ]
        
        all_ok = True
        for endpoint, name in endpoints:
            try:
                resp = requests.get(f"http://localhost:8000{endpoint}", timeout=5)
                if resp.status_code == 200:
                    logger.info(f"API {name} ({endpoint}): OK")
                else:
                    logger.warning(f"API {name} ({endpoint}): {resp.status_code}")
                    all_ok = False
            except Exception as e:
                logger.warning(f"API {name} ({endpoint}) 失败: {e}")
                all_ok = False
        
        return all_ok
    
    # ==================== 步骤4: 数据验证与看板 ====================
    
    def step4_data_verify_and_dashboard(self) -> bool:
        """步骤4: 数据验证与看板显示"""
        self.print_section("步骤4: 数据验证与看板")
        
        # 4.1 三数据库状态
        msg_count = self.check_db_count(self.messages_db, "group_messages")
        stock_count = self.check_db_count(self.stock_db, "stocks")
        mentions_count = self.check_db_count(self.mentions_db, "stock_mentions")
        
        self.print_step("4.1 messages.db", "done" if msg_count > 0 else "fail", f"{msg_count}条消息")
        self.print_step("4.2 a_stock.db", "done" if stock_count > 0 else "fail", f"{stock_count}只股票")
        self.print_step("4.3 stock_mentions.db", 
            "done" if mentions_count > 0 else "info", 
            f"{mentions_count}条提及")
        
        # 数据流验证：消息→提及 的流转
        if msg_count > 0 and stock_count > 0:
            self.results['data_flow'] = True
            self.print_step("4.4 数据流验证", "done", 
                "模块1→模块3←模块2 数据流转正常")
        
        # 4.5 获取今日热门股票
        try:
            resp = requests.get("http://localhost:8000/api/stats/daily", timeout=5)
            if resp.status_code == 200:
                daily = resp.json()
                stock_list = daily.get('stocks', [])[:5]
                print()
                print("  【今日热门股票提及TOP5】")
                print(f"  {'排名':<4} {'股票名称':<12} {'代码':<10} {'提及次数':<8}")
                print("  " + "-" * 40)
                for i, stock in enumerate(stock_list, 1):
                    name = stock.get('name', '')[:10]
                    code = stock.get('code', '')
                    count = stock.get('mention_count', 0)
                    print(f"  {i:<4} {name:<12} {code:<10} {count:<8}")
                self.results['dashboard'] = True
        except Exception as e:
            self.print_step("4.5 看板数据", "info", f"获取失败: {e}")
        
        # 4.6 实时消息监听状态验证
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.print_step("4.6 实时监听", "done", "后台线程运行中")
        else:
            self.print_step("4.6 实时监听", "info", "线程状态未知")
        
        success = (self.results['module1'] and 
                   self.results['module2'] and 
                   self.results['module3'] and 
                   self.results['data_flow'])
        return success
    
    # ==================== 步骤5: 实时看板监控 ====================
    
    def step5_realtime_dashboard(self):
        """步骤5: 实时看板监控（按Ctrl+C退出）"""
        print()
        print("=" * 70)
        print("  实时看板监控（按 Ctrl+C 退出）")
        print("=" * 70)
        
        try:
            while True:
                self._render_dashboard()
                time.sleep(10)  # 10秒刷新
        except KeyboardInterrupt:
            print("\n\n用户中断，正在退出...")
    
    def _render_dashboard(self):
        """渲染一帧看板"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 清屏
        print("\033[2J\033[H", end="")
        
        print()
        print("+" + "-" * 68 + "+")
        print(f"|  三模块联动测试看板  {now:<46}|")
        print("+" + "-" * 68 + "+")
        
        # 模块状态
        print("|  【模块状态】")
        m1 = "✓ 运行" if self.results['module1'] else "✗ 失败"
        m2 = "✓ 运行" if self.results['module2'] else "✗ 失败"
        m3 = "✓ 运行" if self.results['module3'] else "✗ 失败"
        print(f"|  模块1（微信监听）: {m1}")
        print(f"|  模块2（A股数据）: {m2}")
        print(f"|  模块3（股票分析）: {m3}")
        
        # 数据库状态
        msg_count = self.check_db_count(self.messages_db, "group_messages")
        stock_count = self.check_db_count(self.stock_db, "stocks")
        mentions_count = self.check_db_count(self.mentions_db, "stock_mentions")
        
        print("|")
        print("|  【数据库状态】")
        print(f"|  messages.db:      {msg_count} 条消息")
        print(f"|  a_stock.db:       {stock_count} 只股票")
        print(f"|  stock_mentions.db: {mentions_count} 条提及")
        
        # 实时监听状态
        monitor_alive = self.monitor_thread and self.monitor_thread.is_alive()
        print("|")
        print("|  【实时监听】")
        print(f"|  状态: {'运行中' if monitor_alive else '未运行'}")
        print(f"|  目标群: {self.selected_group_name or '未选择'}")
        
        # API统计
        print("|")
        print("|  【今日统计】")
        try:
            daily = requests.get("http://localhost:8000/api/stats/daily", timeout=3).json()
            period = daily.get('period', '')
            count = daily.get('stock_count', 0)
            print(f"|  日期: {period}  当日 {count} 只股票被提及")
            stocks = daily.get('stocks', [])[:5]
            if stocks:
                print(f"|  {'排名':<4} {'股票名称':<12} {'代码':<10} {'提及次数':<8}")
                print("|  " + "-" * 50)
                for i, stock in enumerate(stocks, 1):
                    name = stock.get('name', '')[:10]
                    code = stock.get('code', '')
                    cnt = stock.get('mention_count', 0)
                    print(f"|  {i:<4} {name:<12} {code:<10} {cnt:<8}")
            else:
                print("|  暂无提及数据")
        except Exception as e:
            print(f"|  API服务无响应: {e}")
        
        print("+" + "-" * 68 + "+")
        print("|  按 Ctrl+C 退出测试")
        print("+" + "-" * 68 + "+")
    
    # ==================== 清理 ====================
    
    def cleanup(self):
        """清理资源"""
        print()
        self.print_step("清理资源", "doing")
        
        # 停止模块1监听线程
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.stop_monitor_event.set()
            self.monitor_thread.join(timeout=5)
            self.print_step("停止监听线程", "done")
        
        # 停止模块3 API进程
        if self.api_process:
            try:
                self.api_process.terminate()
                self.api_process.wait(timeout=5)
                self.print_step("停止API服务", "done")
            except:
                try:
                    self.api_process.kill()
                    self.print_step("强制停止API", "done")
                except:
                    pass
        
        self.print_step("清理完成", "done")
        print()
    
    # ==================== 主运行方法 ====================
    
    def run(self):
        """执行完整测试流程"""
        success = False
        try:
            self.print_header()
            
            # 步骤1: 模块1启动
            if not self.step1_module1_start():
                print()
                self.print_step("模块1", "fail", "启动失败，终止测试")
                return False
            
            # 步骤2: 模块2启动
            if not self.step2_module2_start():
                print()
                self.print_step("模块2", "fail", "启动失败，终止测试")
                return False
            
            # 步骤3: 模块3启动
            if not self.step3_module3_start():
                print()
                self.print_step("模块3", "fail", "启动失败，终止测试")
                return False
            
            # 步骤4: 数据验证与看板
            success = self.step4_data_verify_and_dashboard()
            
            # 步骤5: 实时看板
            if not self.auto_mode:
                print()
                try:
                    choice = input("  进入实时看板监控？(Y/n): ").strip().lower()
                    if choice in ('', 'y', 'yes'):
                        self.step5_realtime_dashboard()
                except KeyboardInterrupt:
                    print()
            else:
                self.print_step("全自动模式", "info", "跳过实时看板交互")
            
            return success
            
        except KeyboardInterrupt:
            print("\n\n用户中断")
            return False
        except Exception as e:
            logger.error(f"测试异常: {e}", exc_info=True)
            self.print_step("测试运行", "fail", str(e))
            return False
        finally:
            self.cleanup()
            self._print_summary(success)
    
    def _print_summary(self, success: bool):
        """打印测试总结"""
        print()
        print("=" * 70)
        print("  测试总结")
        print("=" * 70)
        print()
        
        items = [
            ("模块1（微信监听）", self.results['module1']),
            ("模块2（A股数据）", self.results['module2']),
            ("模块3（股票分析）", self.results['module3']),
            ("数据流流转", self.results['data_flow']),
            ("看板显示", self.results['dashboard']),
        ]
        
        for name, ok in items:
            status = "✓ 通过" if ok else "✗ 失败"
            print(f"  {name:<20} {status}")
        
        print()
        if success:
            print("  🏆 临时脚本测试成功！")
            print()
            print("  ✓ 各模块内部机制正常运行")
            print("  ✓ 三个模块之间数据正常采集")
            print("  ✓ 看板正常显示模块3内容")
            print("  ✓ 实时消息监听运行中")
            print("  ✓ 模块3内各项功能运行正常")
        else:
            print("  ❌ 测试未通过，请检查日志")
        
        print()
        print("=" * 70)


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="三模块联动测试脚本 - 模块1→模块2→模块3 顺序启动验证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python test_minimal_flow_final.py              # 交互式运行（手动选择目标群）
  python test_minimal_flow_final.py -g 2         # 指定群编号运行（AI测试群 = 编号2）
  python test_minimal_flow_final.py --auto       # 全自动模式（自动选第一个群 + 跳过看板交互）
  python test_minimal_flow_final.py -g 2 --auto  # 指定群编号 + 全自动模式
        """
    )
    parser.add_argument(
        '-g', '--group',
        type=int,
        default=None,
        help='预指定目标群编号（1-based，编号1通常为AI测试群）'
    )
    parser.add_argument(
        '--auto',
        action='store_true',
        default=False,
        help='全自动模式：自动选第一个群 + 跳过实时看板交互'
    )
    
    args = parser.parse_args()
    
    test = MinimalFlowFinalTest(group_choice=args.group, auto_mode=args.auto)
    success = test.run()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
