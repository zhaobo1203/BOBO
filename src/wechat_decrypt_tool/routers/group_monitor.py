"""群消息监听 API 路由

提供群消息实时监听的启动、停止、状态查询等 API 接口。
"""

import asyncio
import threading
import time
import re
import tempfile
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..logging_config import get_logger
from ..message_storage import get_message_storage, MessageStorage
from ..key_store import get_account_keys_from_store
from ..wechat_detection import auto_detect_wechat_data_dirs
from ..wcdb_realtime import (
    open_account as wcdb_open_account,
    get_sessions as wcdb_get_sessions,
    get_messages as wcdb_get_messages,
    close_account as wcdb_close_account,
)
from ..wechat_decrypt import WeChatDatabaseDecryptor

logger = get_logger(__name__)

router = APIRouter(prefix="/api/group-monitor", tags=["群消息监听"])

# 尝试导入 zstandard
try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except Exception:
    ZSTD_AVAILABLE = False


# ============== 数据模型 ==============

class MonitorStartRequest(BaseModel):
    """启动监听请求"""
    group_name: Optional[str] = None
    group_id: Optional[str] = None
    account_name: Optional[str] = None
    poll_interval: int = 2
    save_to_db: bool = True


class MonitorStatusResponse(BaseModel):
    """监听状态响应"""
    is_running: bool
    group_name: Optional[str] = None
    group_id: Optional[str] = None
    start_time: Optional[str] = None
    messages_received: int = 0
    messages_saved: int = 0
    errors_count: int = 0
    mode: str = "idle"  # idle, realtime, polling


class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    sender_nickname: str
    message_content: str
    send_time: str
    group_name: str
    group_id: Optional[str]
    sender_id: Optional[str]


class GroupsListResponse(BaseModel):
    """群聊列表响应"""
    groups: List[Dict[str, Any]]
    total: int


# ============== 监听器管理类 ==============

class GroupMonitorManager:
    """群消息监听管理器"""
    
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 监听配置
        self.group_name: Optional[str] = None
        self.group_id: Optional[str] = None
        self.account_name: Optional[str] = None
        self.poll_interval: int = 2
        self.save_to_db: bool = True
        
        # 状态追踪
        self.start_time: Optional[datetime] = None
        self.messages_received: int = 0
        self.messages_saved: int = 0
        self.errors_count: int = 0
        self.mode: str = "idle"
        
        # 数据库信息
        self._db_key: Optional[str] = None
        self._session_db_path: Optional[Path] = None
        self._contact_db_path: Optional[Path] = None
        self._handle: Optional[int] = None
        self._group_names: Dict[str, str] = {}
        self._last_create_time: int = 0
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "is_running": self._running,
            "group_name": self.group_name,
            "group_id": self.group_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "messages_received": self.messages_received,
            "messages_saved": self.messages_saved,
            "errors_count": self.errors_count,
            "mode": self.mode
        }
    
    def start(
        self,
        group_name: Optional[str] = None,
        group_id: Optional[str] = None,
        account_name: Optional[str] = None,
        poll_interval: int = 2,
        save_to_db: bool = True
    ) -> Dict[str, Any]:
        """
        启动监听
        
        Returns:
            启动结果
        """
        if self._running:
            return {"success": False, "error": "监听已在运行中"}
        
        try:
            # 1. 获取密钥
            key_store = get_account_keys_from_store()
            if not key_store:
                return {"success": False, "error": "没有找到已保存的密钥，请先获取密钥"}
            
            self.account_name = account_name or list(key_store.keys())[0]
            if self.account_name not in key_store:
                return {"success": False, "error": f"账号 {self.account_name} 的密钥不存在"}
            
            self._db_key = key_store[self.account_name].get('db_key')
            if not self._db_key:
                return {"success": False, "error": "密钥无效"}
            
            # 2. 查找数据库目录
            data_dirs = auto_detect_wechat_data_dirs()
            db_dir = None
            
            for d in data_dirs:
                d_path = Path(d)
                if d_path.exists() and d_path.is_dir():
                    for sub_dir in d_path.iterdir():
                        if sub_dir.is_dir() and self.account_name.lower() in sub_dir.name.lower():
                            test_path = sub_dir / 'db_storage' / 'session' / 'session.db'
                            if test_path.exists():
                                db_dir = sub_dir / 'db_storage'
                                break
                if db_dir:
                    break
            
            if not db_dir:
                return {"success": False, "error": "找不到账号的数据库目录"}
            
            self._session_db_path = db_dir / 'session' / 'session.db'
            self._contact_db_path = db_dir / 'contact' / 'contact.db'
            
            # 3. 获取群名称映射
            if self._contact_db_path.exists():
                self._group_names = self._get_group_names()
            
            # 4. 连接数据库
            self._handle = wcdb_open_account(str(self._session_db_path), self._db_key)
            if self._handle <= 0:
                return {"success": False, "error": "数据库连接失败"}
            
            # 5. 获取群聊列表
            sessions = wcdb_get_sessions(self._handle)
            group_sessions = [s for s in sessions if '@chatroom' in s.get('username', '')]
            
            # 6. 确定目标群
            target_group = None
            
            if group_id:
                for s in group_sessions:
                    if s.get('username') == group_id:
                        target_group = {
                            'id': group_id,
                            'name': self._group_names.get(group_id, group_id)
                        }
                        break
            
            if not target_group and group_name:
                for s in group_sessions:
                    gid = s.get('username', '')
                    gname = self._group_names.get(gid, gid)
                    if group_name in gname:
                        target_group = {'id': gid, 'name': gname}
                        break
            
            if not target_group:
                # 返回群列表供选择
                groups_info = [
                    {'id': s.get('username', ''), 'name': self._group_names.get(s.get('username', ''), s.get('username', ''))}
                    for s in group_sessions
                ]
                return {
                    "success": False, 
                    "error": "请指定群名称或群ID",
                    "available_groups": groups_info[:50]  # 限制返回数量
                }
            
            self.group_id = target_group['id']
            self.group_name = target_group['name']
            self.poll_interval = poll_interval
            self.save_to_db = save_to_db
            
            # 7. 获取历史消息以确定起始时间戳
            messages = wcdb_get_messages(self._handle, self.group_id, limit=10)
            self._last_create_time = 0
            for msg in messages:
                msg_time = msg.get('create_time') or msg.get('createTime') or 0
                try:
                    msg_time_int = int(msg_time) if msg_time else 0
                except:
                    msg_time_int = 0
                if msg_time_int > self._last_create_time:
                    self._last_create_time = msg_time_int
            
            # 8. 启动监听线程
            self._running = True
            self._stop_event.clear()
            self.start_time = datetime.now()
            self.messages_received = 0
            self.messages_saved = 0
            self.errors_count = 0
            self.mode = "polling"
            
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
            
            logger.info(f"群消息监听已启动: {self.group_name} ({self.group_id})")
            
            return {
                "success": True,
                "group_name": self.group_name,
                "group_id": self.group_id,
                "start_time": self.start_time.isoformat(),
                "mode": self.mode
            }
            
        except Exception as e:
            logger.exception(f"启动监听失败: {e}")
            return {"success": False, "error": str(e)}
    
    def stop(self) -> Dict[str, Any]:
        """停止监听"""
        if not self._running:
            return {"success": False, "error": "监听未运行"}
        
        self._running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        
        if self._handle and self._handle > 0:
            try:
                wcdb_close_account(self._handle)
            except:
                pass
            self._handle = None
        
        self.mode = "idle"
        
        logger.info("群消息监听已停止")
        
        return {
            "success": True,
            "messages_received": self.messages_received,
            "messages_saved": self.messages_saved
        }
    
    def _get_group_names(self) -> Dict[str, str]:
        """解密 contact.db 获取群名称映射"""
        group_names = {}
        
        if not self._contact_db_path or not self._db_key:
            return group_names
        
        temp_db = tempfile.mktemp(suffix='.db')
        try:
            decryptor = WeChatDatabaseDecryptor(self._db_key)
            if not decryptor.decrypt_database(str(self._contact_db_path), temp_db):
                return group_names
            
            conn = sqlite3.connect(temp_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT username, remark, nick_name, alias 
                FROM contact 
                WHERE username LIKE '%@chatroom'
            """)
            
            for row in cursor.fetchall():
                group_id = row['username']
                name = row['remark'] or row['nick_name'] or row['alias'] or group_id
                group_names[group_id] = name
            
            conn.close()
        except Exception as e:
            logger.warning(f"获取群名称失败: {e}")
        finally:
            try:
                import os
                os.remove(temp_db)
            except:
                pass
        
        return group_names
    
    def _decode_message_content(self, message_value) -> str:
        """解码消息内容（处理zstd压缩）"""
        zstd_magic = b"\x28\xb5\x2f\xfd"
        
        if isinstance(message_value, (bytes, bytearray, memoryview)):
            raw = bytes(message_value) if isinstance(message_value, memoryview) else message_value
            if raw.startswith(zstd_magic) and ZSTD_AVAILABLE:
                try:
                    out = zstd.decompress(raw)
                    return out.decode("utf-8", errors="ignore")
                except Exception:
                    pass
            try:
                return raw.decode("utf-8", errors="replace")
            except Exception:
                return ""
        
        text = str(message_value or "").strip()
        if not text:
            return ""
        
        if len(text) >= 16 and len(text) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", text):
            try:
                raw = bytes.fromhex(text)
                if raw.startswith(zstd_magic) and ZSTD_AVAILABLE:
                    try:
                        out = zstd.decompress(raw)
                        return out.decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                return raw.decode("utf-8", errors="replace")
            except Exception:
                pass
        
        return text
    
    def _is_text_message(self, content: str) -> bool:
        """判断是否为文字消息"""
        if not content or len(content.strip()) < 1:
            return False
        if content.strip().startswith('<?xml') or content.strip().startswith('<msg>'):
            return False
        return True
    
    def _monitor_loop(self):
        """监听循环"""
        poll_count = 0
        
        while self._running and not self._stop_event.is_set():
            try:
                time.sleep(self.poll_interval)
                poll_count += 1
                
                # 每隔一段时间重新连接数据库
                if poll_count % 10 == 1:
                    try:
                        if self._handle and self._handle > 0:
                            wcdb_close_account(self._handle)
                        self._handle = wcdb_open_account(str(self._session_db_path), self._db_key)
                    except:
                        pass
                
                if not self._handle or self._handle <= 0:
                    self.errors_count += 1
                    continue
                
                # 获取最新消息
                new_messages = wcdb_get_messages(self._handle, self.group_id, limit=10)
                
                # 查找新消息
                for msg in new_messages:
                    msg_time = msg.get('create_time') or msg.get('createTime') or 0
                    try:
                        msg_time_int = int(msg_time) if msg_time else 0
                    except:
                        msg_time_int = 0
                    
                    if msg_time_int > self._last_create_time:
                        self._last_create_time = msg_time_int
                        self.messages_received += 1
                        
                        # 解析消息
                        sender = msg.get('sender_username') or msg.get('sender') or '未知'
                        content = self._decode_message_content(
                            msg.get('message_content') or msg.get('content') or ''
                        )
                        
                        if self._is_text_message(content):
                            send_time = datetime.fromtimestamp(msg_time_int)
                            
                            # 保存到数据库
                            if self.save_to_db:
                                try:
                                    storage = get_message_storage()
                                    storage.save_message(
                                        sender_nickname=sender,
                                        message_content=content,
                                        send_time=send_time,
                                        group_name=self.group_name,
                                        group_id=self.group_id,
                                        sender_id=sender
                                    )
                                    self.messages_saved += 1
                                except Exception as e:
                                    logger.warning(f"保存消息失败: {e}")
                            
                            logger.debug(f"[新消息] {sender}: {content[:50]}...")
            
            except Exception as e:
                logger.warning(f"监听循环异常: {e}")
                self.errors_count += 1


# 全局监听管理器
_monitor_manager = GroupMonitorManager()


# ============== API 路由 ==============

@router.post("/start", summary="启动群消息监听")
async def start_monitor(request: MonitorStartRequest):
    """
    启动群消息实时监听
    
    - **group_name**: 群名称（支持部分匹配）
    - **group_id**: 群ID（如 53109723645@chatroom）
    - **account_name**: 微信账号名（可选，默认使用第一个账号）
    - **poll_interval**: 轮询间隔（秒，默认2秒）
    - **save_to_db**: 是否保存到数据库（默认True）
    """
    result = _monitor_manager.start(
        group_name=request.group_name,
        group_id=request.group_id,
        account_name=request.account_name,
        poll_interval=request.poll_interval,
        save_to_db=request.save_to_db
    )
    return result


@router.post("/stop", summary="停止群消息监听")
async def stop_monitor():
    """停止当前的群消息监听"""
    result = _monitor_manager.stop()
    return result


@router.get("/status", response_model=MonitorStatusResponse, summary="获取监听状态")
async def get_monitor_status():
    """获取当前监听状态"""
    status = _monitor_manager.get_status()
    return MonitorStatusResponse(**status)


@router.get("/messages", summary="查询历史消息")
async def get_messages(
    group_name: Optional[str] = Query(None, description="群名称（支持模糊匹配）"),
    group_id: Optional[str] = Query(None, description="群ID"),
    limit: int = Query(100, ge=1, le=1000, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    查询已保存的消息
    
    - **group_name**: 群名称（可选，支持模糊匹配）
    - **group_id**: 群ID（可选）
    - **limit**: 返回数量限制
    - **offset**: 偏移量（用于分页）
    """
    storage = get_message_storage()
    messages = storage.get_messages(
        group_name=group_name,
        group_id=group_id,
        limit=limit,
        offset=offset
    )
    total = storage.get_message_count(
        group_name=group_name,
        group_id=group_id
    )
    
    return {
        "messages": messages,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/groups", response_model=GroupsListResponse, summary="获取已监听的群列表")
async def get_monitored_groups():
    """获取所有已保存消息的群聊列表"""
    storage = get_message_storage()
    groups = storage.get_groups()
    return GroupsListResponse(groups=groups, total=len(groups))


@router.delete("/messages", summary="清理消息")
async def clear_messages(
    group_name: Optional[str] = Query(None, description="群名称"),
    days: Optional[int] = Query(None, description="清理多少天前的消息")
):
    """
    清理消息
    
    - **group_name**: 群名称（可选，不指定则清理所有）
    - **days**: 清理多少天前的消息（可选）
    """
    storage = get_message_storage()
    
    before_time = None
    if days:
        from datetime import timedelta
        before_time = datetime.now() - timedelta(days=days)
    
    deleted_count = storage.clear_messages(
        group_name=group_name,
        before_time=before_time
    )
    
    return {"success": True, "deleted_count": deleted_count}