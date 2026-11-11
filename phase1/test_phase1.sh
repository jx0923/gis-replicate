#!/bin/bash
# Phase 1 端到端验证：发影像 → 发矢量 → 发切片 → 查 → 删，全程走 HTTP API
# 前置：PostgreSQL 已起（pg_ctlcluster 16 main start），Phase 1 应用已起（:8090）
set -u
BASE="http://localhost:8090"
P0="$HOME/workspace/gis-replicate/phase0/data"
fail=0
slug_of() { python3 -c "import json,sys; print(json.load(open('$1'))['slug'])"; }
check() { # check <名字> <命令...>
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then echo "PASS: $name"; else echo "FAIL: $name"; fail=1; fi
}
echo "===== 1. 发布影像服务（test_raster.tif） ====="
curl -s -X POST "$BASE/api/services" \
  -F "name=测试影像" -F "type=raster" \
  -F "file=@$P0/test_raster.tif" -o /tmp/ms_tmp/p1_raster.json
head -c 300 /tmp/ms_tmp/p1_raster.json; echo
check "影像服务已发布" grep -q '"status": "active"' /tmp/ms_tmp/p1_raster.json
RASTER_SLUG=$(slug_of /tmp/ms_tmp/p1_raster.json)

echo "===== 2. 发布矢量服务（parks.geojson） ====="
curl -s -X POST "$BASE/api/services" \
  -F "name=测试公园" -F "type=vector" -F "fill=#6496dc" -F "outline=#143c8c" -F "width=2" \
  -F "file=@$P0/parks.geojson" -o /tmp/ms_tmp/p1_vector.json
head -c 300 /tmp/ms_tmp/p1_vector.json; echo
check "矢量服务已发布" grep -q '"status": "active"' /tmp/ms_tmp/p1_vector.json
PARKS_SLUG=$(slug_of /tmp/ms_tmp/p1_vector.json)

echo "===== 3. 发布矢量服务（roads.geojson，线） ====="
curl -s -X POST "$BASE/api/services" \
  -F "name=测试道路" -F "type=vector" -F "fill=#dc6464" -F "outline=#8c1414" -F "width=3" \
  -F "file=@$P0/roads.geojson" -o /tmp/ms_tmp/p1_roads.json
head -c 300 /tmp/ms_tmp/p1_roads.json; echo
check "道路服务已发布" grep -q '"status": "active"' /tmp/ms_tmp/p1_roads.json
ROADS_SLUG=$(slug_of /tmp/ms_tmp/p1_roads.json)

echo "===== 4. 发布切片服务（源=测试影像） ====="
curl -s -X POST "$BASE/api/services" \
  -F "name=测试切片" -F "type=tiles" -F "source_slug=$RASTER_SLUG" -o /tmp/ms_tmp/p1_tiles.json
head -c 300 /tmp/ms_tmp/p1_tiles.json; echo
check "切片服务已发布" grep -q '"status": "active"' /tmp/ms_tmp/p1_tiles.json
TILES_SLUG=$(slug_of /tmp/ms_tmp/p1_tiles.json)

echo "===== 5. 服务列表 ====="
curl -s "$BASE/api/services" -o /tmp/ms_tmp/p1_list.json
check "列表有 4 个服务" bash -c "grep -o '\"slug\"' /tmp/ms_tmp/p1_list.json | wc -l | grep -q 4"

echo "===== 6. WMS 出图（矢量 PostGIS 图层） ====="
MAPQ="map=$HOME/workspace/gis-replicate/phase1/maps/services.map"
curl -s "$BASE/cgi-bin/mapserv?$MAPQ&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=$PARKS_SLUG&STYLES=&CRS=EPSG:4326&BBOX=39.85,116.30,40.00,116.50&WIDTH=800&HEIGHT=600&FORMAT=image/png" -o /tmp/ms_tmp/p1_map.png
check "矢量 GetMap 返回 PNG 800x600" bash -c "file /tmp/ms_tmp/p1_map.png | grep -q 'PNG image data, 800 x 600'"

echo "===== 7. WFS 取要素 ====="
curl -s "$BASE/cgi-bin/mapserv?$MAPQ&SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAME=$PARKS_SLUG&COUNT=10" -o /tmp/ms_tmp/p1_wfs.xml
check "WFS 返回 3 个公园" bash -c "grep -o 'Chaoyang Park\|Olympic Forest Park\|Beihai Park' /tmp/ms_tmp/p1_wfs.xml | wc -l | grep -q 3"

echo "===== 8. WMTS（切片服务） ====="
curl -s "$BASE/cgi-bin/mapcache?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetCapabilities" -o /tmp/ms_tmp/p1_wmts.xml
check "WMTS GetCapabilities 有 tileset" grep -q "$TILES_SLUG" /tmp/ms_tmp/p1_wmts.xml
curl -s "$BASE/cgi-bin/mapcache?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile&LAYER=$TILES_SLUG&STYLE=&FORMAT=image/png&TILEMATRIXSET=wgs84&TILEMATRIX=0&TILEROW=0&TILECOL=0" -o /tmp/ms_tmp/p1_tile.png
check "WMTS GetTile 返回 PNG 256x256" bash -c "file /tmp/ms_tmp/p1_tile.png | grep -q 'PNG image data, 256 x 256'"

echo "===== 9. 下线切片服务 ====="
curl -s -X DELETE "$BASE/api/services/$TILES_SLUG" | grep -q '"ok": true' && echo "PASS: 下线切片" || { echo "FAIL: 下线切片"; fail=1; }
curl -s "$BASE/api/services" | grep -q "$TILES_SLUG" && { echo "FAIL: 列表仍有已下线服务"; fail=1; } || echo "PASS: 列表已无切片服务"

echo "===== 10. 清理：下线其余服务 ====="
for s in "$RASTER_SLUG" "$PARKS_SLUG" "$ROADS_SLUG"; do curl -s -X DELETE "$BASE/api/services/$s" -o /dev/null; done
curl -s "$BASE/api/services" -o /tmp/ms_tmp/p1_list2.json
check "列表已空" bash -c "grep -q '^\[\]$' /tmp/ms_tmp/p1_list2.json"
echo "----"
if [ "$fail" = 0 ]; then echo "Phase 1 全部通过"; else echo "有失败项"; exit 1; fi
