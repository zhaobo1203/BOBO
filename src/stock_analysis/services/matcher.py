"""
消息文本匹配引擎
精确匹配股票名称和代码，严格边界判断
"""
import re
import logging
from typing import List, Tuple, Optional

from ..config.settings import (
    ENCRYPTED_DATA_MIN_LENGTH,
    XML_START_MARKERS,
    SENDER_PREFIX_PATTERN,
)
from ..models.stock import Stock
from ..models.mention import MentionRecord

logger = logging.getLogger(__name__)


class Matcher:
    """消息文本匹配引擎"""

    # 边界字符集合：标点、空格、换行等
    BOUNDARY_CHARS = set(
        "，。！？、；：""''【】《》（）""''…—·\n\r\t "
        ",.!?;:\"'[]{}()<>/\\|@#$%^&*+=~`"
    )

    # 股票上下文后缀词：股票名称后面紧跟这些词时，也算有效匹配
    CONTEXT_SUFFIX_WORDS = [
        "合资", "科技", "集团", "股份", "控股", "银行", "证券",
        "信息", "电子", "发展", "实业", "能源", "电力", "医药",
        "通信", "建设", "机械", "材料", "新材", "产业", "投资",
        "基金", "有限", "责任", "公司", "股份制", "上市", "A股",
        "板块", "涨停", "跌停", "买入", "卖出", "加仓", "减仓",
        "看多", "看空", "走势", "行情", "复盘", "龙头", "白马",
        "蓝筹", "妖股", "停牌", "复牌", "分红", "配股", "增发",
        "半年报", "年报", "季报", "财报", "业绩", "公告", "研报",
        "评级", "目标价", "市盈率", "市净率", "净利润", "营收",
    ]

    # 6位股票代码正则
    STOCK_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")

    def __init__(self, name_index: dict, code_index: dict):
        """
        初始化匹配引擎

        Args:
            name_index: 股票名称索引 {name: Stock}
            code_index: 股票代码索引 {code: Stock}
        """
        self.name_index = name_index
        self.code_index = code_index
        # 按名称长度降序排列，优先匹配更长的名称
        self.sorted_names = sorted(name_index.keys(), key=len, reverse=True)
        logger.info(f"匹配引擎初始化完成，名称索引{len(name_index)}条，代码索引{len(code_index)}条")

    def match_message(self, message_id: int, content: str,
                      sender: str, send_time: str,
                      group_name: str) -> List[MentionRecord]:
        """
        对单条消息进行匹配

        Args:
            message_id: 消息ID
            content: 消息内容
            sender: 发送人
            send_time: 发送时间
            group_name: 群名称

        Returns:
            匹配到的MentionRecord列表
        """
        # 1. 过滤非文本消息
        cleaned_content = self._clean_content(content)
        if cleaned_content is None:
            return []

        records = []

        # 2. 名称精确匹配
        name_matches = self._match_by_name(cleaned_content)
        for stock, match_type in name_matches:
            record = MentionRecord(
                message_id=message_id,
                stock_code=stock.code,
                stock_name=stock.name,
                match_type=match_type,
                sender=sender,
                message_content=content,  # 保留原始内容
                send_time=send_time,
                group_name=group_name,
            )
            records.append(record)

        # 3. 代码精确匹配
        code_matches = self._match_by_code(cleaned_content)
        for stock, match_type in code_matches:
            # 避免重复（同一条消息同一只股票不重复计数）
            if not any(r.stock_code == stock.code for r in records):
                record = MentionRecord(
                    message_id=message_id,
                    stock_code=stock.code,
                    stock_name=stock.name,
                    match_type=match_type,
                    sender=sender,
                    message_content=content,
                    send_time=send_time,
                    group_name=group_name,
                )
                records.append(record)

        if records:
            logger.debug(
                f"消息匹配结果: 消息ID={message_id}, "
                f"匹配到{len(records)}只股票: "
                f"{[r.stock_name for r in records]}"
            )

        return records

    def _clean_content(self, content: str) -> Optional[str]:
        """
        清洗消息内容，过滤非文本消息

        Returns:
            清洗后的内容，如果应跳过则返回None
        """
        if not content or not content.strip():
            return None

        # 过滤加密数据：以十六进制字符为主且长度超过阈值
        stripped = content.strip()
        if len(stripped) > ENCRYPTED_DATA_MIN_LENGTH:
            # 检查是否大部分是十六进制字符
            hex_chars = set("0123456789abcdefABCDEF")
            hex_ratio = sum(1 for c in stripped if c in hex_chars) / len(stripped)
            if hex_ratio > 0.8:
                logger.debug(f"过滤加密数据: 长度={len(stripped)}, 十六进制比例={hex_ratio:.2f}")
                return None

        # 过滤XML格式消息
        for marker in XML_START_MARKERS:
            if stripped.startswith(marker):
                logger.debug(f"过滤XML消息: 以'{marker}'开头")
                return None

        # 去掉发送人前缀（如 "leijian8981:\n实际内容"）
        cleaned = re.sub(SENDER_PREFIX_PATTERN, "", content)

        return cleaned

    def _match_by_name(self, text: str) -> List[Tuple[Stock, str]]:
        """
        按股票名称精确匹配（严格边界判断）

        Returns:
            (Stock, match_type) 列表
        """
        matches = []
        matched_positions = set()  # 记录已匹配的位置，避免重叠

        for name in self.sorted_names:
            stock = self.name_index[name]
            start = 0
            while True:
                pos = text.find(name, start)
                if pos == -1:
                    break

                end = pos + len(name)

                # 检查是否与已匹配的位置重叠
                if any(pos <= mp < end for mp in matched_positions):
                    start = end
                    continue

                # 严格边界判断
                if self._check_boundary(text, pos, end):
                    matches.append((stock, "name"))
                    # 记录匹配位置
                    for i in range(pos, end):
                        matched_positions.add(i)

                start = end

        return matches

    def _match_by_code(self, text: str) -> List[Tuple[Stock, str]]:
        """
        按股票代码精确匹配（6位数字，严格边界判断）

        Returns:
            (Stock, match_type) 列表
        """
        matches = []

        for match in self.STOCK_CODE_PATTERN.finditer(text):
            code = match.group(1)
            stock = self.code_index.get(code)
            if stock:
                pos = match.start(1)
                end = match.end(1)
                # 代码匹配时，前后不能是数字（已由正则保证）
                # 但还需检查前后不能是字母（避免匹配到更长编号中的部分）
                if self._check_code_boundary(text, pos, end):
                    matches.append((stock, "code"))

        return matches

    def _check_boundary(self, text: str, start: int, end: int) -> bool:
        """
        检查名称匹配的边界条件

        名称前后必须是：消息首尾、标点、空格、换行、数字
        名称后面可以是：上下文后缀词（如"合资"、"科技"、"涨停"等）
        """
        # 检查前一个字符
        if start > 0:
            prev_char = text[start - 1]
            # 前面可以是标点、空格、换行、数字
            if prev_char not in self.BOUNDARY_CHARS and not prev_char.isdigit():
                return False

        # 检查后一个字符或后缀词
        if end < len(text):
            next_char = text[end]
            # 后面可以是标点、空格、换行、数字
            if next_char not in self.BOUNDARY_CHARS and not next_char.isdigit():
                # 检查后面是否紧跟上下文后缀词
                remaining = text[end:]
                if not any(remaining.startswith(suffix) for suffix in self.CONTEXT_SUFFIX_WORDS):
                    return False

        return True

    def _check_code_boundary(self, text: str, start: int, end: int) -> bool:
        """
        检查代码匹配的边界条件

        代码前后必须是：消息首尾、标点、空格、换行
        代码前后不能是字母或数字（数字已由正则保证）
        """
        # 检查前一个字符
        if start > 0:
            prev_char = text[start - 1]
            if prev_char.isalpha():
                return False
            if prev_char not in self.BOUNDARY_CHARS and prev_char.isdigit():
                return False

        # 检查后一个字符
        if end < len(text):
            next_char = text[end]
            if next_char.isalpha():
                return False
            if next_char not in self.BOUNDARY_CHARS and next_char.isdigit():
                return False

        return True

    def match_messages_batch(self, messages: List[tuple]) -> List[MentionRecord]:
        """
        批量匹配消息

        Args:
            messages: 消息元组列表 (id, sender_nickname, message_content, send_time, group_name)

        Returns:
            所有匹配到的MentionRecord列表
        """
        all_records = []
        matched_msg_count = 0

        for msg in messages:
            msg_id, sender, content, send_time, group_name = msg
            records = self.match_message(
                message_id=msg_id,
                content=content,
                sender=sender,
                send_time=send_time,
                group_name=group_name,
            )
            if records:
                matched_msg_count += 1
            all_records.extend(records)

        logger.info(
            f"批量匹配完成: 处理{len(messages)}条消息, "
            f"匹配到{matched_msg_count}条含股票提及, "
            f"共{len(all_records)}条提及记录"
        )

        return all_records
