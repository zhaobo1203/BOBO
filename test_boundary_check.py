# -*- coding: utf-8 -*-
"""测试边界检查逻辑 - 与matcher.py同步"""
import sys
import io
import unicodedata

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 与matcher.py同步的边界字符
BOUNDARY_CHARS = set(
    "，。！？、；：""''【】《》（）""''…—·\n\r\t "
    ",.!?;:\"'[]{}()<>/\\|@#$%^&*+=~`"
)

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

# 中文常见前缀词（与matcher.py同步）
CHINESE_PREFIX_WORDS = set(
    # 量词
    "个只手股份笔项家次条块段节批组类种场"
    # 名词性前缀（专栏、板块等）
    "栏版块区层篇集期轮项"
    # 动词性前缀（动宾结构：卖出XX、买入XX、持有XX等）
    "出入到有过了去来起给让被把"
)

# 中文常见动词/副词/助词（与matcher.py同步）
CHINESE_VERB_PARTICLES = set(
    # 助词/语气词
    "了着过地得呢吗吧啊呀嘛"
    # 副词/连词
    "已经也已正在将将要会能不能得可以可"
    "还还有又却但而且或者与及和跟比较更"
    "最就才只是到从被把给让向对于按很"
    # 财经新闻常见动词
    "披发布宣告称说表显提涨跌停收开"
    "完该此其每各另再因如若则虽"
    "进成获受持买卖换操盘拉砸冲破"
    "创超达占涵盖包扩预估计测算"
    "在是于为与由以据依经通借"
    "更被将"
)


def _is_unicode_symbol(char):
    """判断字符是否为Unicode符号/emoji"""
    try:
        category = unicodedata.category(char)
        if category in ('So', 'Sk', 'Sm', 'Sc'):
            return True
        cp = ord(char)
        if (0x1F300 <= cp <= 0x1F9FF or
            0x2600 <= cp <= 0x27BF or
            0xFE00 <= cp <= 0xFE0F or
            0x1FA00 <= cp <= 0x1FA6F or
            0x1FA70 <= cp <= 0x1FAFF):
            return True
    except (ValueError, TypeError):
        pass
    return False


def check_boundary(text, start, end):
    """检查名称匹配的边界条件（与matcher.py _check_boundary同步）"""
    # 检查前一个字符
    if start > 0:
        prev_char = text[start - 1]
        if prev_char not in BOUNDARY_CHARS and not prev_char.isdigit():
            if prev_char not in CHINESE_PREFIX_WORDS:
                if not _is_unicode_symbol(prev_char):
                    return False, f"前字符'{prev_char}'不是边界/数字/前缀词/符号"

    # 检查后一个字符或后缀词
    if end < len(text):
        next_char = text[end]
        if next_char not in BOUNDARY_CHARS and not next_char.isdigit():
            remaining = text[end:]
            if not any(remaining.startswith(suffix) for suffix in CONTEXT_SUFFIX_WORDS):
                if next_char not in CHINESE_VERB_PARTICLES:
                    return False, f"后字符'{next_char}'不是边界/数字/后缀词/动词助词"

    return True, "通过"


# ========== 测试用例 ==========

print("=" * 60)
print("边界检查测试 - 与matcher.py同步")
print("=" * 60)

# 测试1: 原有消息边界检查
msg1 = "美利信已经走出了趋势，只要不跌破5日均线就可以放心，因为这波行情起来都是在5日线运行，华微电子也走出了趋势，如果回踩5日均线再承接上去更佳。大元泵业，汉中精机还观察是否有效突破，作为潜力来观察。"

test_stocks = ["美利信", "华微电子", "大元泵业", "汉中精机"]

print("\n=== 测试1: 原有消息边界检查 ===")
print(f"消息: {msg1[:80]}...")
print()

for name in test_stocks:
    pos = msg1.find(name)
    if pos == -1:
        print(f"  {name}: 未找到")
        continue
    end = pos + len(name)
    prev_char = msg1[pos-1] if pos > 0 else "<START>"
    next_char = msg1[end] if end < len(msg1) else "<END>"
    ok, reason = check_boundary(msg1, pos, end)
    status = "✓" if ok else "✗"
    print(f"  {status} {name}: 位置{pos}-{end}, 前='{prev_char}', 后='{next_char}', {reason}")

# 测试2: 动词前缀边界（本次修复的核心场景）
print("\n=== 测试2: 动词前缀边界（核心修复场景） ===")
verb_prefix_cases = [
    # (股票名, 消息, 期望结果)
    ("民德电子", "卖出民德电子，买了澳柯玛", True),       # "出"在CHINESE_PREFIX_WORDS
    ("澳柯玛", "买了澳柯玛，一天又亏了13个点", True),     # "了"在CHINESE_PREFIX_WORDS
    ("民德电子", "看到汤圆卖出民德电子", True),           # "出"在CHINESE_PREFIX_WORDS
    ("平安银行", "持有平安银行很久了", True),              # "有"在CHINESE_PREFIX_WORDS
    ("澳柯玛", "买入澳柯玛", True),                       # "入"在CHINESE_PREFIX_WORDS
    ("美利信", "三个美利信", True),                        # "个"在CHINESE_PREFIX_WORDS（量词）
    ("美利信", "专栏美利信", True),                        # "栏"在CHINESE_PREFIX_WORDS（名词前缀）
    ("民德电子", "民德电子披露投资者关系", True),          # 后边界"披"在CHINESE_VERB_PARTICLES
    ("民德电子", "民德电子涨停", True),                    # 后边界"涨"在CHINESE_VERB_PARTICLES
    ("民德电子", "民德电子，今天怎么样", True),            # 后边界"，"在BOUNDARY_CHARS
    ("民德电子", "民德电子", True),                        # 首尾边界
]

all_pass = True
for name, text, expected in verb_prefix_cases:
    pos = text.find(name)
    if pos == -1:
        print(f"  ✗ {name} in '{text}': 未找到")
        all_pass = False
        continue
    end = pos + len(name)
    prev_char = text[pos-1] if pos > 0 else "<START>"
    next_char = text[end] if end < len(text) else "<END>"
    ok, reason = check_boundary(text, pos, end)
    match = ok == expected
    status = "✓" if match else "✗ FAIL"
    if not match:
        all_pass = False
    print(f"  {status} {name} in '{text}': 前='{prev_char}', 后='{next_char}', 期望={expected}, 实际={ok} ({reason})")

# 测试3: 不应匹配的边界（确保没有过度匹配）
print("\n=== 测试3: 不应匹配的边界（防误匹配） ===")
negative_cases = [
    # (股票名, 消息, 期望结果) - 边界检查层面
    # "平安夜"：边界检查不通过（"安"后跟"夜"不是有效后边界），黑名单也会过滤
    ("平安", "平安夜快乐", False),
    # "经济发展"：边界检查不通过（"济"不是有效前边界，"迅"不是有效后边界）
    ("发展", "经济发展迅速", False),
    # 以下才是边界检查应拒绝的
    ("美利信", "xxx美利信yyy", False),           # 前后都是普通字母
]

for name, text, expected in negative_cases:
    pos = text.find(name)
    if pos == -1:
        print(f"  - {name} in '{text}': 未找到（跳过）")
        continue
    end = pos + len(name)
    prev_char = text[pos-1] if pos > 0 else "<START>"
    next_char = text[end] if end < len(text) else "<END>"
    ok, reason = check_boundary(text, pos, end)
    match = ok == expected
    status = "✓" if match else "✗ FAIL"
    if not match:
        all_pass = False
    print(f"  {status} {name} in '{text}': 前='{prev_char}', 后='{next_char}', 期望={expected}, 实际={ok} ({reason})")

# 测试4: 完整匹配引擎测试（使用真实Matcher）
print("\n=== 测试4: 完整匹配引擎测试 ===")
sys.path.insert(0, 'src')
from stock_analysis.services.matcher import Matcher
from stock_analysis.models.stock import Stock

test_stocks_data = {
    '民德电子': Stock(code='300656', name='民德电子'),
    '澳柯玛': Stock(code='600336', name='澳柯玛'),
    '美利信': Stock(code='301307', name='美利信'),
    '华微电子': Stock(code='600360', name='华微电子'),
    '平安银行': Stock(code='000001', name='平安银行'),
}
matcher = Matcher(
    name_index=test_stocks_data,
    code_index={s.code: s for s in test_stocks_data.values()}
)

full_test_cases = [
    # (消息, 期望匹配的股票名称列表)
    ("卖出民德电子，买了澳柯玛", ["民德电子", "澳柯玛"]),
    ("wxid_v8g6uleh63ms11: 汤圆 看到汤圆卖出民德电子，买了澳柯玛，一天又亏了13个点", ["民德电子", "澳柯玛"]),
    ("持有平安银行很久了", ["平安银行"]),
    ("美利信已经走出了趋势", ["美利信"]),
    ("民德电子披露投资者关系活动记录表", ["民德电子"]),
    ("民德电子涨停了", ["民德电子"]),
]

for content, expected_names in full_test_cases:
    cleaned = matcher._clean_content(content)
    if cleaned is None:
        print(f"  ✗ '{content[:40]}': 被过滤为非文本消息")
        all_pass = False
        continue
    name_matches = matcher._match_by_name(cleaned)
    matched_names = [s.name for s, m in name_matches]
    match = set(matched_names) == set(expected_names)
    status = "✓" if match else "✗ FAIL"
    if not match:
        all_pass = False
    print(f"  {status} '{content[:40]}': 期望={expected_names}, 实际={matched_names}")

# 汇总
print("\n" + "=" * 60)
if all_pass:
    print("✓ 所有测试通过！")
else:
    print("✗ 存在失败的测试用例，请检查！")
print("=" * 60)
