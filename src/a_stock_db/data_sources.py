# -*- coding: utf-8 -*-
"""
A股数据源模块
支持多个数据源（按优先级排列）：
- 新浪财经分页（主）- 实时、当天同步新股
- 东方财富API（备1）- 实时、当天同步新股（可能被封）
- AKShare聚合（备2）- 轻量级东财列表接口
- Baostock（备3）- 稳定但新股同步滞后1-2天
- Efinance（备4）- 东方财富
- 新浪财经单页（备5）- 可能不完整
- TuShare（备6）- 需要token
自动测试速度和稳定性，选择最优数据源
"""

import time
import os
import sys
from typing import Optional
from dataclasses import dataclass
import logging
import requests
import json

logger = logging.getLogger(__name__)


@dataclass
class StockInfo:
    """股票信息数据类"""
    code: str  # 股票代码
    name: str  # 股票名称


@dataclass
class DataSourceResult:
    """数据源获取结果"""
    success: bool
    stocks: list[StockInfo]
    count: int
    elapsed_time: float  # 耗时（秒）
    source_name: str = "unknown"  # 数据源名称
    error_message: Optional[str] = None


class DataSourceBase:
    """数据源基类"""
    
    # 子类应设置此属性
    SOURCE_NAME: str = "unknown"
    
    def fetch_stock_list(self) -> DataSourceResult:
        """获取股票列表"""
        raise NotImplementedError
    
    def _is_valid_stock(self, code: str) -> bool:
        """判断是否为有效股票（沪深主板、创业板、科创板，不含ETF和北交所）"""
        if not code:
            return False
        
        # 沪主板: 60xxxx
        if code.startswith('60') and len(code) == 6:
            return True
        # 深主板: 00xxxx (不含指数)
        if code.startswith('00') and len(code) == 6:
            return True
        # 创业板: 30xxxx
        if code.startswith('30') and len(code) == 6:
            return True
        # 科创板: 68xxxx
        if code.startswith('68') and len(code) == 6:
            return True
        
        return False
    
    def _clean_stock_name(self, name: str) -> str:
        """清理股票名称 - 保留新股N/C前缀以利于匹配
        
        新股上市初期名称带N/C前缀（如N长鑫），几天后变为正式名（如长鑫科技）。
        保留前缀的原因：
        1. 群里讨论新股时常说"N长鑫"，保留前缀有利于匹配
        2. 去掉前缀后名称不完整（N长鑫→长鑫，但正式名是长鑫科技）
        3. 几天后API自动返回正式名称，更新时会自动修正
        4. 代码匹配（如688825）不受名称影响
        """
        if not name:
            return name
        return name.strip()
    
    @staticmethod
    def _fix_akshare_path():
        """修复AKShare在PyInstaller打包环境下的路径问题
        
        PyInstaller将文件解压到临时目录_MEIxxxxx，但akshare的file_fold可能不存在，
        导致calendar.json找不到。此方法在导入akshare前创建必要的目录和文件。
        """
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
            akshare_file_fold = os.path.join(base_path, 'akshare', 'file_fold')
            if not os.path.exists(akshare_file_fold):
                os.makedirs(akshare_file_fold, exist_ok=True)
                calendar_file = os.path.join(akshare_file_fold, 'calendar.json')
                if not os.path.exists(calendar_file):
                    with open(calendar_file, 'w', encoding='utf-8') as f:
                        json.dump({}, f)
                    logger.info(f"已创建AKShare临时文件: {calendar_file}")


class SinaFinancePagedSource(DataSourceBase):
    """新浪财经分页数据源 - 实时、当天同步新股（主数据源）
    
    使用新浪财经API分页获取沪深A股完整列表。
    优点：免费、无需注册、当天同步新股、数据准确
    注意：需要分页获取（每页最多80条），完整获取约需30秒
    """
    SOURCE_NAME = "新浪财经分页"
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            stocks, seen = [], set()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "http://vip.stock.finance.sina.com.cn/"
            }
            base_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            
            # 分别获取上交所(sh_a)和深交所(sz_a)数据，使用分页
            for node in ["sh_a", "sz_a"]:
                page = 1
                while True:
                    params = {
                        "page": page, "num": 80, "sort": "symbol", "asc": 1,
                        "node": node, "symbol": "", "_s_r_a": "page"
                    }
                    try:
                        resp = requests.get(base_url, params=params, headers=headers, timeout=30)
                        if resp.status_code != 200:
                            break
                        data = resp.json()
                        if not data:
                            break
                        for item in data:
                            # 注意：使用'code'字段而非'symbol'字段
                            # symbol带前缀如bj920000/sh600000/sz000001
                            # code是纯数字如920000/600000/000001
                            code = item.get('code', '')
                            name = item.get('name', '')
                            if self._is_valid_stock(code) and code not in seen:
                                stocks.append(StockInfo(code=code, name=self._clean_stock_name(name)))
                                seen.add(code)
                        if len(data) < 80:
                            break
                        page += 1
                        if page > 100:  # 安全限制
                            break
                    except Exception as e:
                        logger.warning(f"新浪财经{node}第{page}页失败: {e}")
                        break
            
            if not stocks:
                raise Exception("新浪财经分页接口未返回有效数据")
            elapsed = time.time() - start_time
            logger.info(f"新浪财经分页获取 {len(stocks)} 只股票, 耗时{elapsed:.1f}秒")
            return DataSourceResult(
                success=True, stocks=stocks, count=len(stocks),
                elapsed_time=elapsed, source_name=self.SOURCE_NAME
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"新浪财经分页获取数据失败: {e}")
            return DataSourceResult(
                success=False, stocks=[], count=0,
                elapsed_time=elapsed, error_message=str(e)
            )


class SinaFinanceSource(DataSourceBase):
    """新浪财经数据源 - 单页获取（备用，可能不完整）"""
    SOURCE_NAME = "新浪财经"
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            stocks, seen = [], set()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "http://vip.stock.finance.sina.com.cn/"
            }
            base_url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
            
            for node in ["sh_a", "sz_a"]:
                params = {
                    "page": 1, "num": 6000, "sort": "symbol", "asc": 1,
                    "node": node, "symbol": "", "_s_r_a": "page"
                }
                try:
                    resp = requests.get(base_url, params=params, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data:
                            for item in data:
                                code = item.get('code', '')
                                name = item.get('name', '')
                                if self._is_valid_stock(code) and code not in seen:
                                    stocks.append(StockInfo(code=code, name=self._clean_stock_name(name)))
                                    seen.add(code)
                except Exception as e:
                    logger.warning(f"新浪财经{node}接口失败: {e}")
            
            if not stocks:
                raise Exception("新浪财经接口未返回有效数据")
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True, stocks=stocks, count=len(stocks),
                elapsed_time=elapsed, source_name=self.SOURCE_NAME
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"新浪财经获取数据失败: {e}")
            return DataSourceResult(
                success=False, stocks=[], count=0,
                elapsed_time=elapsed, error_message=str(e)
            )


class TencentFinanceSource(DataSourceBase):
    """东方财富API数据源 - push2可能被封，自动降级"""
    SOURCE_NAME = "东方财富API"
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            stocks, seen = [], set()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://quote.eastmoney.com/",
            }
            # 沪深A股参数 - 使用市场类型过滤（非板块过滤）
            params = {
                "pn": 1, "pz": 6000, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f12",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f12,f14", "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            }
            # 尝试多个东方财富URL
            for url in ["http://82.push2.eastmoney.com/api/qt/clist/get",
                        "https://push2.eastmoney.com/api/qt/clist/get"]:
                try:
                    resp = requests.get(url, params=params, headers=headers, timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and 'data' in data and 'diff' in data['data']:
                            for item in data['data']['diff']:
                                code, name = item.get('f12', ''), item.get('f14', '')
                                if self._is_valid_stock(code) and code not in seen:
                                    stocks.append(StockInfo(code=code, name=self._clean_stock_name(name)))
                                    seen.add(code)
                            if stocks:
                                break
                except Exception as e:
                    logger.debug(f"东方财富接口{url}失败: {e}")
            if not stocks:
                raise Exception("无法从任何免费接口获取数据")
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True, stocks=stocks, count=len(stocks),
                elapsed_time=elapsed, source_name=self.SOURCE_NAME
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"东方财富API获取数据失败: {e}")
            return DataSourceResult(
                success=False, stocks=[], count=0,
                elapsed_time=elapsed, error_message=str(e)
            )


class BaostockSource(DataSourceBase):
    """Baostock数据源 - 稳定但新股同步滞后1-2天，增加新股补充查询"""
    SOURCE_NAME = "Baostock"
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import baostock as bs
            from datetime import datetime, timedelta
            
            # 登录系统
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"Baostock登录失败: {lg.error_msg}")
            
            # 获取所有证券基本信息
            rs = bs.query_stock_basic()
            stocks, seen = [], set()
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                code = str(row[0]).strip()  # 代码格式: sh.600000 或 sz.000001
                name = str(row[1]).strip() if len(row) > 1 else ""
                
                # 转换代码格式
                if '.' in code:
                    pure_code = code.split('.')[1]
                else:
                    pure_code = code[2:] if len(code) > 6 else code
                
                if self._is_valid_stock(pure_code) and pure_code not in seen:
                    stocks.append(StockInfo(code=pure_code, name=name))
                    seen.add(pure_code)
            
            # 补充查询：获取最近7天上市的新股（Baostock基础数据可能滞后）
            try:
                today = datetime.now().strftime('%Y-%m-%d')
                week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                rs2 = bs.query_stock_basic(code_name="", start_date=week_ago, end_date=today)
                supplement_count = 0
                while (rs2.error_code == '0') & rs2.next():
                    row = rs2.get_row_data()
                    code = str(row[0]).strip()
                    name = str(row[1]).strip() if len(row) > 1 else ""
                    if '.' in code:
                        pure_code = code.split('.')[1]
                    else:
                        pure_code = code[2:] if len(code) > 6 else code
                    if self._is_valid_stock(pure_code) and pure_code not in seen:
                        stocks.append(StockInfo(code=pure_code, name=name))
                        seen.add(pure_code)
                        supplement_count += 1
                        logger.info(f"Baostock补充新股: {pure_code} {name}")
                if supplement_count > 0:
                    logger.info(f"Baostock新股补充查询: 新增{supplement_count}只")
            except Exception as e:
                logger.debug(f"Baostock新股补充查询失败(非致命): {e}")
            
            bs.logout()
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True, stocks=stocks, count=len(stocks),
                elapsed_time=elapsed, source_name=self.SOURCE_NAME
            )
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Baostock获取数据失败: {e}")
            return DataSourceResult(
                success=False, stocks=[], count=0,
                elapsed_time=elapsed, error_message=str(e)
            )


class AKShareSource(DataSourceBase):
    """AKShare数据源 - 使用官方聚合接口获取完整A股列表"""
    SOURCE_NAME = "AKShare聚合"
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        stocks = []
        
        try:
            # 修复PyInstaller打包环境下的路径问题
            self._fix_akshare_path()
            import akshare as ak
            
            # 使用 stock_info_a_code_name 获取沪深京A股完整列表
            # 该接口自动合并：上交所主板 + 科创板 + 深交所A股 + 北交所A股
            try:
                df = ak.stock_info_a_code_name()
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = str(row.get('code', '')).strip()
                        name = str(row.get('name', '')).strip()
                        if self._is_valid_stock(code):
                            stocks.append(StockInfo(code=code, name=name))
                    logger.info(f"AKShare聚合接口获取 {len(stocks)} 只股票")
            except Exception as e:
                logger.warning(f"AKShare聚合接口失败: {e}")
            
            # 备用方案：分步获取各交易所数据
            if len(stocks) < 3000:
                seen_codes = {s.code for s in stocks}
                
                # 获取深交所A股
                try:
                    sz_df = ak.stock_info_sz_name_code(symbol="A股列表")
                    if sz_df is not None and not sz_df.empty:
                        sz_count = 0
                        for _, row in sz_df.iterrows():
                            code = str(row.get('A股代码', '')).strip()
                            name = str(row.get('A股简称', '')).strip()
                            if self._is_valid_stock(code) and code not in seen_codes:
                                stocks.append(StockInfo(code=code, name=name))
                                seen_codes.add(code)
                                sz_count += 1
                        logger.info(f"深交所接口补充 {sz_count} 只股票")
                except Exception as e:
                    logger.warning(f"深交所接口失败: {e}")
                
                # 获取上交所主板A股
                try:
                    sh_df = ak.stock_info_sh_name_code(symbol="主板A股")
                    if sh_df is not None and not sh_df.empty:
                        sh_count = 0
                        for _, row in sh_df.iterrows():
                            code = str(row.get('证券代码', '')).strip()
                            name = str(row.get('证券简称', '')).strip()
                            if self._is_valid_stock(code) and code not in seen_codes:
                                stocks.append(StockInfo(code=code, name=name))
                                seen_codes.add(code)
                                sh_count += 1
                        logger.info(f"上交所主板接口补充 {sh_count} 只股票")
                except Exception as e:
                    logger.warning(f"上交所主板接口失败: {e}")
                
                # 获取科创板
                try:
                    kcb_df = ak.stock_info_sh_name_code(symbol="科创板")
                    if kcb_df is not None and not kcb_df.empty:
                        kcb_count = 0
                        for _, row in kcb_df.iterrows():
                            code = str(row.get('证券代码', '')).strip()
                            name = str(row.get('证券简称', '')).strip()
                            if self._is_valid_stock(code) and code not in seen_codes:
                                stocks.append(StockInfo(code=code, name=name))
                                seen_codes.add(code)
                                kcb_count += 1
                        logger.info(f"科创板接口补充 {kcb_count} 只股票")
                except Exception as e:
                    logger.warning(f"科创板接口失败: {e}")
            
            if not stocks:
                raise Exception("AKShare所有接口均获取失败")
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"AKShare获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class EfinanceSource(DataSourceBase):
    """Efinance数据源（东方财富）"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import efinance as ef
            
            df = ef.stock.get_realtime_quotes()
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row['股票代码']).strip()
                name = str(row['股票名称']).strip()
                
                if self._is_valid_stock(code):
                    stocks.append(StockInfo(code=code, name=name))
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Efinance获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class TuShareSource(DataSourceBase):
    """TuShare数据源 - 需要注册获取token，免费使用"""
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            import tushare as ts
            
            # TuShare需要token，如果未设置则跳过
            # 用户需要在 tushare.pro 注册并设置 token
            try:
                pro = ts.pro_api()
            except Exception as e:
                raise Exception("TuShare需要配置token，请先注册 https://tushare.pro 并设置token")
            
            # 获取股票列表
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row['symbol']).strip()
                name = str(row['name']).strip()
                
                if self._is_valid_stock(code):
                    stocks.append(StockInfo(code=code, name=name))
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"TuShare获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class SinaSpotSource(DataSourceBase):
    """新浪财经实时行情数据源 - 通过AKShare调用"""
    SOURCE_NAME = "新浪实时行情"
    
    def fetch_stock_list(self) -> DataSourceResult:
        start_time = time.time()
        try:
            self._fix_akshare_path()
            import akshare as ak
            
            # 使用 stock_zh_a_spot 获取A股实时行情（包含代码和名称）
            df = ak.stock_zh_a_spot()
            
            stocks = []
            for _, row in df.iterrows():
                code_raw = str(row.get('代码', '')).strip()
                name = str(row.get('名称', '')).strip()
                
                # 新浪返回的代码带前缀如 sz301550，需要去掉前缀
                if len(code_raw) > 6:
                    code = code_raw[-6:]  # 取后6位
                else:
                    code = code_raw
                
                if self._is_valid_stock(code):
                    stocks.append(StockInfo(code=code, name=name))
            
            elapsed = time.time() - start_time
            return DataSourceResult(
                success=True,
                stocks=stocks,
                count=len(stocks),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"新浪实时行情获取数据失败: {e}")
            return DataSourceResult(
                success=False,
                stocks=[],
                count=0,
                elapsed_time=elapsed,
                error_message=str(e)
            )


class DataSourceManager:
    """数据源管理器 - 自动测试并选择最优数据源"""
    
    def __init__(self):
        # 数据源优先级（新浪分页为主；AKShare/Baostock为校准备用；东方财富可能被封）
        self.sources = [
            ("新浪财经分页", SinaFinancePagedSource()),         # 主数据源 - 实时、当天同步新股
            ("AKShare聚合", AKShareSource()),                   # 备用1 - 官方聚合接口，可校准新股
            ("Baostock", BaostockSource()),                     # 备用2 - 稳定，含新股补充查询
            ("东方财富API", TencentFinanceSource()),            # 备用3 - 可能被封
            ("Efinance", EfinanceSource()),                     # 备用4 - 东方财富
            ("新浪财经", SinaFinanceSource()),                  # 备用5 - 单页可能不完整
            ("TuShare", TuShareSource()),                       # 备用6 - 需要token
        ]
        self.test_results: dict[str, DataSourceResult] = {}
    
    def test_all_sources(self) -> dict[str, DataSourceResult]:
        """测试所有数据源的速度和稳定性"""
        print("\n正在测试各数据源的速度和稳定性...")
        print("-" * 60)
        
        for name, source in self.sources:
            print(f"测试 {name}...", end=" ")
            result = source.fetch_stock_list()
            self.test_results[name] = result
            
            if result.success:
                print(f"[OK] 成功 | 获取 {result.count} 只股票 | 耗时 {result.elapsed_time:.2f}秒")
            else:
                print(f"[FAIL] 失败 | 错误: {result.error_message}")
        
        print("-" * 60)
        return self.test_results
    
    def get_best_source(self) -> tuple[Optional[str], Optional[DataSourceBase]]:
        """获取最优数据源"""
        successful = [
            (name, result) 
            for name, result in self.test_results.items() 
            if result.success
        ]
        
        if not successful:
            return None, None
        
        successful.sort(key=lambda x: x[1].elapsed_time)
        best_name = successful[0][0]
        
        for name, source in self.sources:
            if name == best_name:
                return best_name, source
        
        return None, None
    
    def fetch_with_fallback(self, current_count: int = 0) -> DataSourceResult:
        """按优先级依次尝试获取数据
        
        Args:
            current_count: 当前数据库中的股票数量，用于数量验证
        """
        for name, source in self.sources:
            print(f"尝试从 {name} 获取数据...")
            result = source.fetch_stock_list()
            
            if result.success:
                print(f"[OK] {name} 获取成功: {result.count} 只股票, 耗时 {result.elapsed_time:.2f}秒")
                return result
            else:
                print(f"[FAIL] {name} 获取失败: {result.error_message}")
        
        return DataSourceResult(
            success=False,
            stocks=[],
            count=0,
            elapsed_time=0,
            error_message="所有数据源均获取失败"
        )


def test_data_sources():
    """测试数据源函数"""
    manager = DataSourceManager()
    results = manager.test_all_sources()
    
    print("\n测试结果汇总:")
    print("=" * 60)
    for name, result in results.items():
        status = "[OK] 成功" if result.success else "[FAIL] 失败"
        print(f"{name}: {status}")
        if result.success:
            print(f"  - 股票数量: {result.count}")
            print(f"  - 耗时: {result.elapsed_time:.2f}秒")
        else:
            print(f"  - 错误: {result.error_message}")
    
    best_name, _ = manager.get_best_source()
    if best_name:
        print(f"\n推荐使用: {best_name}")
    else:
        print("\n警告: 没有可用的数据源!")


if __name__ == "__main__":
    test_data_sources()