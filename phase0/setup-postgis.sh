#!/bin/bash
# Phase 0: PostgreSQL + PostGIS 启动与入库（apt 装好后跑一次）
# 用系统自带 cluster（/var/lib/postgresql/16/main，apt 安装时已 initdb），
# 不用 workspace 下的新 cluster（postgres 用户进不去 2770 的 workspace 目录）。
# 密码 gis/gis 仅本地验证用，不要用于生产。
set -e
PGBIN="/usr/lib/postgresql/16/bin"
PGDATA="/var/lib/postgresql/16/main"
# 1. 启动 cluster（Debian 布局：数据在 /var/lib，配置在 /etc，用 pg_ctlcluster）
if ! pg_lsclusters 2>/dev/null | grep -q "16.*main.*online"; then
  pg_ctlcluster 16 main start
fi
# 3. 建库 + PostGIS + 业务账号
su postgres -c "psql -tA -c \"SELECT 1 FROM pg_database WHERE datname='gisdb'\"" | grep -q 1 || \
  su postgres -c "createdb gisdb"
su postgres -c "psql -d gisdb -c 'CREATE EXTENSION IF NOT EXISTS postgis;'"
su postgres -c "psql -tA -c \"SELECT 1 FROM pg_roles WHERE rolname='gis'\"" | grep -q 1 || \
  su postgres -c "psql -c \"CREATE USER gis WITH PASSWORD 'gis';\""
su postgres -c "psql -d gisdb -c 'GRANT ALL ON SCHEMA public TO gis;'"
# 4. 入库：GeoJSON 先拷到 /tmp（postgres 用户读不到 workspace），再用本地 socket 导
cp ~/workspace/gis-replicate/phase0/data/parks.geojson ~/workspace/gis-replicate/phase0/data/roads.geojson /tmp/ms_tmp/
chmod 644 /tmp/ms_tmp/parks.geojson /tmp/ms_tmp/roads.geojson
su postgres -c "ogr2ogr -f PostgreSQL PG:dbname=gisdb /tmp/ms_tmp/parks.geojson -nln parks -overwrite"
su postgres -c "ogr2ogr -f PostgreSQL PG:dbname=gisdb /tmp/ms_tmp/roads.geojson -nln roads -overwrite"
su postgres -c "psql -d gisdb -c 'GRANT SELECT ON parks, roads TO gis; SELECT count(*) AS parks FROM parks; SELECT count(*) AS roads FROM roads;'"
echo "PostGIS 就绪：gisdb，表 parks / roads，账号 gis/gis"
