#!/bin/bash

if command -v python3 >/dev/null 2>&1; then
    echo "使用 python3 启动..."
    python3 mksoft.py
elif command -v python >/dev/null 2>&1; then
    echo "使用 python 启动..."
    python mksoft.py
else
    echo "错误：未找到 python 或 python3"
    exit 1
fi
