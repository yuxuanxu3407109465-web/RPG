#!/bin/bash
# 封城第七天 - 网页版启动器（macOS）
# 在访达里双击这个文件：启动本地服务并自动在浏览器里打开游戏。
# 游戏已经在运行时只会打开页面，不会再起第二个服务。
# 玩的时候别关这个终端窗口；关掉网页或点游戏里的“退出游戏”会自动停掉服务。
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 webui.py
else
  echo "没找到 python3，请先安装 Python 3。"
fi
code=$?
# webui.py 退出码：2 = 页面关了 / 退出游戏，3 = 游戏已经在运行；这两种直接结束
if [ "$code" -ne 2 ] && [ "$code" -ne 3 ]; then
  echo
  read -n 1 -s -r -p "服务已停止，按任意键关闭窗口。"
fi
