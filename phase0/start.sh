#!/bin/bash
# Phase 0 一键启动：本目录的 mapserv HTTP 网关（server.py）+ MapServer
# 用法：bash start.sh   （Ctrl+C 停止；沙箱重启后重跑本脚本即可）
# 注意：不用 python -m http.server --cgi，那个会把 CGI 子进程 setuid(nobody)，
# 而 workspace 目录是 2770，nobody 进不去会 EACCES。
set -e
cd "$(dirname "$0")"
mkdir -p /tmp/ms_tmp
export MAPSERVER_CONFIG_FILE="$PWD/mapserver.conf"
echo "mapserv: /usr/bin/mapserv ($(mapserv -v 2>&1 | cut -d' ' -f1-3))"
echo "MAPSERVER_CONFIG_FILE: $MAPSERVER_CONFIG_FILE"
echo "服务地址：http://localhost:8080/ （首页有 WMS/WMTS/WFS/GetMap 链接）"
echo "按 Ctrl+C 停止"
exec python3 server.py 8080
