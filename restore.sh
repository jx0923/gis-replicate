#!/bin/bash
# GIS 复刻 Phase 0+1 运行栈一键恢复（沙箱重置后重跑）
# 覆盖：apt 源精简（坑 6）→ 装 MapServer/GDAL/PostgreSQL+PostGIS/MapCache
#       → 建 gisdb 入库 → 起 :8080/:8090 → 跑 Phase 0 7 项验证 + Phase 1 轻量验证
# 用法：bash ~/workspace/gis-replicate/restore.sh
# 日志：~/workspace/gis-replicate/restore.log
# 幂等：已装好的包会跳过；gisdb 已存在时 setup-postgis.sh 会复用并重新入库。
# 注意：Phase 1 的 services.db、maps/、data/ 都在 workspace 里，重置丢不掉，
#       但 test_phase1.sh 收尾已清空列表，所以恢复后列表为空（[]），属正常；
#       如需重新验证，跑 test_phase1.sh 会重新发 4 个服务。
set -u
cd ~/workspace/gis-replicate
LOG="$HOME/workspace/gis-replicate/restore.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== restore 开始 $(date '+%Y-%m-%d %H:%M:%S %Z') ====="

# 1. apt 源精简（按 phase0 README 坑 6；重置后会回到默认双镜像 + 第三方源）
if [ ! -x /usr/bin/mapserv ]; then
  echo "--- 精简 apt 源 ---"
  mkdir -p /root/apt-sources-bak
  for f in github-cli.sources nodesource.sources; do
    [ -f "/etc/apt/sources.list.d/$f" ] && mv "/etc/apt/sources.list.d/$f" /root/apt-sources-bak/
  done
  # 有些系统文件属主是 nobody，root 也写不了，先 rm 再重建
  rm -f /etc/apt/sources.list.d/ubuntu.sources
  cat > /etc/apt/sources.list.d/ubuntu.sources <<'EOF'
Types: deb
URIs: http://azure.archive.ubuntu.com/ubuntu
Suites: noble noble-updates
Components: main restricted universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
  echo 'Acquire::Languages "none";' > /etc/apt/apt.conf.d/99-no-translations
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  echo "--- 安装 GIS 栈 ---"
  apt-get install -y cgi-mapserver gdal-bin postgresql postgresql-16-postgis-3 mapcache-cgi mapcache-tools
else
  echo "mapserv 已存在，跳过 apt 安装"
fi

# 2. PostGIS 建库入库（幂等）
mkdir -p /tmp/ms_tmp && chmod 755 /tmp/ms_tmp
bash phase0/setup-postgis.sh

# 3. 烟囱检查
echo "--- 烟囱检查 ---"
mapserv -v 2>&1 | head -2
pg_lsclusters
su postgres -c "psql -d gisdb -tA -c 'SELECT count(*) FROM parks; SELECT count(*) FROM roads;'"

# 4. 起服务（setsid 脱离会话后台；nohup 起的会在 exec 会话收尾时被清掉。
#    沙箱再重置仍得重跑本脚本——这是沙箱的结构性问题）
echo "--- 启动服务 ---"
pkill -f "server.py 8080" 2>/dev/null; pkill -f "server.py$" 2>/dev/null; sleep 1
(cd phase0 && MAPSERVER_CONFIG_FILE="$PWD/mapserver.conf" setsid python3 server.py 8080 > /tmp/ms_tmp/phase0.log 2>&1 < /dev/null &)
(cd phase1/app && setsid python3 server.py > /tmp/ms_tmp/phase1.log 2>&1 < /dev/null &)
for i in $(seq 1 20); do
  sleep 1
  if curl -s -m 2 -o /dev/null http://localhost:8080/ && curl -s -m 2 -o /dev/null http://localhost:8090/api/services; then
    echo "服务已起：:8080 与 :8090 均响应"
    break
  fi
  [ "$i" = 20 ] && echo "WARN: 20 秒后仍有端口未响应，见 /tmp/ms_tmp/phase0.log / phase1.log"
done

# 5. 验证
echo "--- Phase 0 验证（7 项） ---"
(cd phase0 && bash test.sh) || echo "WARN: Phase 0 test.sh 有失败项"
echo "--- Phase 1 轻量验证（当前服务列表；验证收尾已清空时为空属正常） ---"
curl -s http://localhost:8090/api/services | head -c 600; echo
echo "===== restore 结束 $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
