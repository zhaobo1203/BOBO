# A股数据库模块

## 功能说明
- 建立本地SQLite数据库存储A股股票基本信息（股票代码、股票名称）
- 支持多数据源自动切换：Baostock（主）、AKShare（备1）、新浪实时行情（备2）
- 支持手动更新数据（增量更新，自动识别新股和退市股）

## 目录结构
```
src/a_stock_db/
├── __init__.py          # 模块初始化
├── data_sources.py      # 数据源管理（7个数据源）
├── database.py          # 数据库操作（SQLite）
├── main.py              # 交互式主程序
└── README.md            # 说明文档

data/a_stock_db/
└── a_stock.db           # SQLite数据库文件
```

## 使用方法

### 1. 命令行运行（推荐）
```bash
# 更新数据
python src/a_stock_db/main.py --update

# 查看数据
python src/a_stock_db/main.py --view

# 测试数据源
python src/a_stock_db/main.py --test
```

### 2. 交互式运行
```bash
python src/a_stock_db/main.py
```

菜单选项：
- `1` - 更新数据：从数据源获取最新股票列表并保存到数据库
- `2` - 查看数据：显示数据库统计信息和部分股票示例
- `0` - 退出程序

### 3. 作为模块调用
```python
from a_stock_db.database import AStockDatabase
from a_stock_db.data_sources import DataSourceManager

# 初始化数据库
db = AStockDatabase()

# 更新数据
manager = DataSourceManager()
result = manager.fetch_with_fallback()
if result.success:
    stocks = [(s.code, s.name) for s in result.stocks]
    db.update_stocks(stocks, source="baostock")

# 查询股票
stock = db.get_stock_by_code("000001")  # ('000001', '平安银行')
stocks = db.get_stock_by_name("平安")    # 模糊查询
all_stocks = db.get_all_stocks()         # 获取所有股票
```

## 数据源说明

| 数据源 | 类型 | 股票数量 | 特点 |
|--------|------|----------|------|
| Baostock | 主数据源 | ~5767只 | 稳定性高，数据准确，需登录 |
| AKShare聚合 | 备用1 | ~5201只 | 数据丰富，接口简单 |
| 新浪实时行情 | 备用2 | ~5200只 | 速度快，无需额外依赖 |

其他备选数据源：TuShare（需token）、Efinance、新浪财经、腾讯财经

## 数据范围
- 沪主板：60xxxx
- 深主板：00xxxx
- 创业板：30xxxx
- 科创板：68xxxx

## 依赖
```
akshare>=1.12.0
baostock>=0.8.9
efinance>=0.5.5
```

安装依赖：
```bash
# 方式1：pip安装
pip install akshare baostock efinance

# 方式2：uv安装（推荐，用于.venv环境）
uv pip install akshare baostock efinance --python .venv/Scripts/python.exe
```

## 环境说明

如果使用VS Code运行，请确保选择正确的Python解释器：
- 使用.venv虚拟环境：`Python 3.11 (.venv)`
- 或使用系统Python：`Python 3.14`（需先安装依赖）

切换解释器：VS Code底部状态栏点击Python版本 → 选择对应环境

## 数据库位置
```
e:\code2\WeChatDataAnalysis\data\a_stock_db\a_stock.db