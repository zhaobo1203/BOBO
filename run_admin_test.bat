@echo off
cd /d e:\code2\WeChatDataAnalysis
python test_minimal_flow_final.py --auto -g 2 > test_admin_output.txt 2> test_admin_error.txt
echo ExitCode: %errorlevel% >> test_admin_output.txt