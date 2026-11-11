#!/bin/bash
# Phase 0 验证脚本：对本地 WMS/WMTS/WFS 做一轮请求并检查结果
# 用法：先 bash start.sh 起服务（另一个终端），再 bash test.sh
set -u
BASE="http://localhost:8080/cgi-bin/mapserv?map=$HOME/workspace/gis-replicate/phase0/phase0.map"
mkdir -p out
fail=0
check() { # check <名字> <命令...>
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then echo "PASS: $name"; else echo "FAIL: $name"; fail=1; fi
}
curl -s "$BASE&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities" -o out/wms_caps.xml
check "WMS GetCapabilities 返回 parks 图层" grep -q "<Name>parks</Name>" out/wms_caps.xml
check "WMS GetCapabilities 返回 roads 图层" grep -q "<Name>roads</Name>" out/wms_caps.xml
curl -s "$BASE&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=parks,roads&STYLES=&CRS=EPSG:4326&BBOX=39.85,116.30,40.00,116.50&WIDTH=800&HEIGHT=600&FORMAT=image/png" -o out/test_map.png
check "WMS GetMap 返回 PNG（800x600）" bash -c "file out/test_map.png | grep -q 'PNG image data, 800 x 600'"
# WMTS 由 MapCache 提供（Ubuntu 的 mapserv 8.0.1 不认 SERVICE=WMTS；原版架构里 WMTS 本来就是 MapCache 的活）
MCCACHE="http://localhost:8080/cgi-bin/mapcache"
curl -s "$MCCACHE?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetCapabilities" -o out/wmts_caps.xml
check "WMTS GetCapabilities 返回 TileMatrixSet" grep -q "TileMatrixSet" out/wmts_caps.xml
curl -s "$MCCACHE?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile&LAYER=phase0&STYLE=&FORMAT=image/png&TILEMATRIXSET=wgs84&TILEMATRIX=0&TILEROW=0&TILECOL=0" -o out/tile0.png
check "WMTS GetTile 返回 PNG（256x256）" bash -c "file out/tile0.png | grep -q 'PNG image data, 256 x 256'"
curl -s "$BASE&SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAME=parks&COUNT=10" -o out/wfs_parks.xml
check "WFS GetFeature 返回 3 个公园" bash -c "grep -o 'Chaoyang Park\|Olympic Forest Park\|Beihai Park' out/wfs_parks.xml | wc -l | grep -q 3"
curl -s "$BASE&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=parks_pg&STYLES=&CRS=EPSG:4326&BBOX=39.85,116.30,40.00,116.50&WIDTH=800&HEIGHT=600&FORMAT=image/png" -o out/test_pg.png
check "PostGIS 图层 GetMap 返回 PNG（800x600）" bash -c "file out/test_pg.png | grep -q 'PNG image data, 800 x 600'"
echo "----"
if [ "$fail" = 0 ]; then echo "全部通过。示例图：out/test_map.png"; else echo "有失败项，检查 out/ 下的原始响应"; exit 1; fi
