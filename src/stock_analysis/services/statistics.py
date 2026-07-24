"""
时间维度统计服务
按日/周/月统计股票提及次数，含周标注计算
"""
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from ..models.mention import MentionRecord

logger = logging.getLogger(__name__)


class StatisticsService:
    """时间维度统计服务"""

    def get_daily_stats(self, mentions: List[MentionRecord],
                        target_date: date = None) -> Dict[str, Any]:
        """获取日统计汇总"""
        if target_date is None:
            target_date = date.today()

        daily_mentions = [
            m for m in mentions
            if self._parse_date(m.send_time) == target_date
        ]

        stock_counts = defaultdict(int)
        for m in daily_mentions:
            stock_counts[m.stock_code] += 1

        stocks = []
        for rank, (code, count) in enumerate(
            sorted(stock_counts.items(), key=lambda x: x[1], reverse=True), 1
        ):
            name = next((m.stock_name for m in daily_mentions if m.stock_code == code), "")
            stocks.append({
                "code": code,
                "name": name,
                "mention_count": count,
                "rank": rank,
            })

        result = {
            "period": target_date.strftime("%Y-%m-%d"),
            "period_type": "daily",
            "total_mentions": len(daily_mentions),
            "stock_count": len(stocks),
            "stocks": stocks,
        }
        logger.info(f"日统计完成: {target_date}, {len(stocks)}只股票, {len(daily_mentions)}次提及")
        return result

    def get_weekly_stats(self, mentions: List[MentionRecord],
                         target_date: date = None) -> Dict[str, Any]:
        """获取周统计汇总"""
        if target_date is None:
            target_date = date.today()

        week_start, week_end = self._get_week_range(target_date)

        weekly_mentions = [
            m for m in mentions
            if week_start <= self._parse_date(m.send_time) <= week_end
        ]

        stock_counts = defaultdict(int)
        for m in weekly_mentions:
            stock_counts[m.stock_code] += 1

        stocks = []
        for rank, (code, count) in enumerate(
            sorted(stock_counts.items(), key=lambda x: x[1], reverse=True), 1
        ):
            name = next((m.stock_name for m in weekly_mentions if m.stock_code == code), "")
            stocks.append({
                "code": code,
                "name": name,
                "mention_count": count,
                "rank": rank,
            })

        week_label = self._get_week_label(target_date)

        result = {
            "period": week_label,
            "period_type": "weekly",
            "week_start": week_start.strftime("%Y-%m-%d"),
            "week_end": week_end.strftime("%Y-%m-%d"),
            "total_mentions": len(weekly_mentions),
            "stock_count": len(stocks),
            "stocks": stocks,
        }
        logger.info(f"周统计完成: {week_label}, {len(stocks)}只股票, {len(weekly_mentions)}次提及")
        return result

    def get_monthly_stats(self, mentions: List[MentionRecord],
                          year: int = None, month: int = None) -> Dict[str, Any]:
        """获取月统计汇总"""
        now = datetime.now()
        if year is None:
            year = now.year
        if month is None:
            month = now.month

        month_start = date(year, month, 1)
        month_end = self._get_month_last_day(year, month)

        today = date.today()
        if month_end > today:
            month_end = today

        monthly_mentions = [
            m for m in mentions
            if month_start <= self._parse_date(m.send_time) <= month_end
        ]

        stock_counts = defaultdict(int)
        for m in monthly_mentions:
            stock_counts[m.stock_code] += 1

        stocks = []
        for rank, (code, count) in enumerate(
            sorted(stock_counts.items(), key=lambda x: x[1], reverse=True), 1
        ):
            name = next((m.stock_name for m in monthly_mentions if m.stock_code == code), "")
            stocks.append({
                "code": code,
                "name": name,
                "mention_count": count,
                "rank": rank,
            })

        result = {
            "period": f"{year}年{month}月",
            "period_type": "monthly",
            "year": year,
            "month": month,
            "month_start": month_start.strftime("%Y-%m-%d"),
            "month_end": month_end.strftime("%Y-%m-%d"),
            "total_mentions": len(monthly_mentions),
            "stock_count": len(stocks),
            "stocks": stocks,
        }
        logger.info(f"月统计完成: {year}年{month}月, {len(stocks)}只股票, {len(monthly_mentions)}次提及")
        return result

    def get_stock_details(self, mentions: List[MentionRecord],
                          stock_code: str, period_type: str,
                          target_date: date = None,
                          year: int = None, month: int = None) -> Dict[str, Any]:
        """获取指定股票在指定时段的提及详情"""
        if period_type == "daily":
            if target_date is None:
                target_date = date.today()
            filtered = [
                m for m in mentions
                if m.stock_code == stock_code and self._parse_date(m.send_time) == target_date
            ]
            period_label = target_date.strftime("%Y-%m-%d")
        elif period_type == "weekly":
            if target_date is None:
                target_date = date.today()
            week_start, week_end = self._get_week_range(target_date)
            filtered = [
                m for m in mentions
                if m.stock_code == stock_code
                and week_start <= self._parse_date(m.send_time) <= week_end
            ]
            period_label = self._get_week_label(target_date)
        elif period_type == "monthly":
            now = datetime.now()
            if year is None:
                year = now.year
            if month is None:
                month = now.month
            month_start = date(year, month, 1)
            month_end = self._get_month_last_day(year, month)
            today = date.today()
            if month_end > today:
                month_end = today
            filtered = [
                m for m in mentions
                if m.stock_code == stock_code
                and month_start <= self._parse_date(m.send_time) <= month_end
            ]
            period_label = f"{year}年{month}月"
        else:
            filtered = []
            period_label = ""

        stock_name = next((m.stock_name for m in filtered), "")

        details = [
            {
                "sender": m.sender,
                "timestamp": m.send_time,
                "content": m.message_content,
            }
            for m in sorted(filtered, key=lambda x: x.send_time)
        ]

        return {
            "code": stock_code,
            "name": stock_name,
            "period": period_label,
            "period_type": period_type,
            "mention_count": len(filtered),
            "details": details,
        }

    def get_week_info(self, year: int, month: int) -> List[Dict[str, Any]]:
        """
        获取指定月份的周标注信息

        周定义：ISO标准，周一为每周第一天
        月份第1周：从本月1日到第一个周日
        月份中间周：完整的周一至周日
        月份最后一周：从最后一个周一到月末最后一天
        """
        weeks = []
        month_start = date(year, month, 1)
        month_end = self._get_month_last_day(year, month)

        current = month_start
        week_num = 0

        while current <= month_end:
            week_num += 1

            # 确定本周的开始日期
            if current == month_start:
                week_start = current
            else:
                week_start = current  # 应该是周一

            # 确定本周的结束日期（周日或月末最后一天）
            days_until_sunday = 6 - week_start.weekday()  # weekday(): 周一=0, 周日=6
            week_end = week_start + timedelta(days=days_until_sunday)
            if week_end > month_end:
                week_end = month_end

            # 周标注格式：X月Y周 M.D-M.D
            label = f"{month}月{week_num}周 {week_start.month}.{week_start.day}-{week_end.month}.{week_end.day}"

            weeks.append({
                "week_num": week_num,
                "label": label,
                "start_date": week_start.strftime("%Y-%m-%d"),
                "end_date": week_end.strftime("%Y-%m-%d"),
                "days": (week_end - week_start).days + 1,
            })

            # 移动到下周一
            current = week_end + timedelta(days=1)

        return weeks

    # ========== 辅助方法 ==========

    def _parse_date(self, time_str: str) -> date:
        """解析时间字符串为date对象"""
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return dt.date()
        except (ValueError, TypeError):
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d")
                return dt.date()
            except (ValueError, TypeError):
                logger.warning(f"无法解析时间字符串: {time_str}")
                return date.today()

    def _get_week_range(self, target_date: date) -> tuple:
        """获取target_date所在周的周一和周日"""
        # weekday(): 周一=0, 周日=6
        days_since_monday = target_date.weekday()
        week_start = target_date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        return week_start, week_end

    def _get_week_label(self, target_date: date) -> str:
        """获取周标注，格式：X月Y周 M.D-M.D"""
        week_start, week_end = self._get_week_range(target_date)
        # 确定这是本月的第几周
        month = week_start.month
        # 计算week_start是本月的第几周
        month_first_day = date(week_start.year, month, 1)
        # 本月1号的weekday
        first_day_weekday = month_first_day.weekday()
        # week_start与本月1号之间的周数
        days_diff = (week_start - month_first_day).days
        week_num = days_diff // 7 + 1
        # 如果本月1号不是周一，第1周包含1号
        if first_day_weekday > 0 and week_start > month_first_day:
            # week_start是第2周或更后
            week_num = (days_diff + first_day_weekday) // 7 + 1

        return f"{month}月{week_num}周 {week_start.month}.{week_start.day}-{week_end.month}.{week_end.day}"

    def _get_month_last_day(self, year: int, month: int) -> date:
        """获取指定月份的最后一天"""
        if month == 12:
            return date(year, 12, 31)
        next_month_first = date(year, month + 1, 1)
        return next_month_first - timedelta(days=1)
