#!/usr/bin/env python3
"""
测试命令脚本 - 手动执行
==========================

测试命令:

1. 查看历史消息（非实时）:
   python src/monitor_group_simple.py -g AI测试 -n 10

2. 实时监听模式:
   python src/monitor_group_simple.py -g AI测试 -r

3. 列出所有群聊:
   python src/monitor_group_simple.py --list

4. 测试指定群ID:
   python src/monitor_group_simple.py -g 59157387978@chatroom -n 10

参数说明:
  -g, --group    指定群名称或群ID
  -n, --limit    显示消息数量（默认20）
  -r, --realtime 实时监听模式
  -i, --interval 轮询间隔秒数（默认2）
  -l, --list     列出所有可用群聊

完整测试流程:

  # 步骤1: 列出群聊
  python src/monitor_group_simple.py --list

  # 步骤2: 查看指定群的历史消息
  python src/monitor_group_simple.py -g AI测试 -n 10

  # 步骤3: 实时监听（按Ctrl+C停止）
  python src/monitor_group_simple.py -g AI测试 -r
"""

if __name__ == "__main__":
    print(__doc__)
    print("\n请复制上面的命令到终端执行。")