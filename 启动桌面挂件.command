#!/bin/bash
# 双击本文件即可启动「雪团」全屏桌面壁纸
cd "$(dirname "$0")"
PY="/Users/leo/.workbuddy/binaries/python/envs/video/bin/python"
if [ ! -x "$PY" ]; then PY="$(command -v python3)"; fi
exec "$PY" desktop_pet.py
