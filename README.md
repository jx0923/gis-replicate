# GIS 复刻（clean-room）

用全开源 GIS 栈复刻一个桌面地图服务发布平台：上传影像、矢量、切片数据，
一键发布成标准 OGC 服务（WMS / WMTS / WFS），别人用 QGIS 或网页就能调用。

对标分析对象见 `phase0` 的说明（XSMapServer 2.0.13 的 REA 分析报告不在本仓库，
在 `~/workspace/xsmap-analysis/`）。本仓库只含 clean-room 复刻代码，
不含原版任何代码、配置或数据。

## 进度

- **Phase 0 技术验证**（已完成，2026-11-11）：MapServer + MapCache + PostGIS + GDAL
  全链路跑通，7 项验证全过。见 [phase0/README.md](phase0/README.md)。
- **Phase 1 发布管理 MVP**（已完成，2026-11-11）：Web 发布台——上传数据、
  发布/下线服务、预览出图。见 [phase1/README.md](phase1/README.md)。
- Phase 2（纵深：样式编辑、切片任务队列）、Phase 3（海图/点云/三维/AI/工作流）
  按复刻报告排期，见 phase0 报告里的四阶段规划。

## 快速开始（沙箱已验证）

```bash
# 1. 装 GIS 栈（Ubuntu 24.04，见 phase0/README.md 的精简 apt 源）
sudo apt-get install -y cgi-mapserver gdal-bin postgresql postgresql-16-postgis-3 \
  mapcache-cgi mapcache-tools
pg_ctlcluster 16 main start

# 2. 起 Phase 1 发布台
cd phase1/app && python3 server.py   # :8090
# 打开 http://localhost:8090，上传 GeoTIFF/GeoJSON/Shapefile zip 发布服务

# 3. 验证
bash phase1/test_phase1.sh   # 12 项全过
bash phase0/test.sh          # Phase 0 的 7 项
```

## Docker 部署

```bash
docker compose -f phase1/docker/docker-compose.yml up --build
# 打开 http://localhost:8090
```

两个容器：`app`（发布台 + MapServer/MapCache 网关）、`db`（PostGIS 16）。

## 目录

```
phase0/   技术验证：MapServer/MapCache/PostGIS/GDAL 跑通，测试数据与验证脚本
phase1/   发布管理 MVP：Web 应用 + 发布引擎 + Docker 部署
  app/      server.py（API+网关） publisher.py（发布引擎） store.py（SQLite 注册表）
            static/（前端，无构建步骤）
  maps/     生成的 services.map / mapcache.xml / mapserver.conf（不进仓库）
  data/     上传的数据（不进仓库）
  docker/   Dockerfile.app + docker-compose.yml
  test_phase1.sh  端到端验证（12 项）
```

## 技术栈

- MapServer 8.0.1（WMS/WFS）+ MapCache 1.14.0（WMTS/TMS）+ GDAL 3.8
- PostgreSQL 16 + PostGIS 3.4（矢量入库）
- 发布台：纯 Python 标准库（无第三方依赖），SQLite 注册表，vanilla JS 前端
