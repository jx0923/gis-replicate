# Phase 1 — 发布管理 MVP（已完成，2026-11-11）

Web 发布台：上传数据，一键发布成 OGC 服务；列表管理、预览出图、下线清理。

## 功能

| 能力 | 说明 |
|---|---|
| 发布影像 | 上传 GeoTIFF → gdalwarp 重投影到 EPSG:4326 → MapServer RASTER 图层 → WMS |
| 发布矢量 | 上传 GeoJSON 或 Shapefile zip → ogr2ogr 导进 PostGIS → MapServer POSTGIS 图层 → WMS + WFS；样式（填充/边线/线宽）可配 |
| 发布切片 | 选一个已发布的影像/矢量服务 → MapCache tileset → WMTS / TMS |
| 服务列表 | 名称、类型、状态、端点链接、预览图 |
| 下线 | 删注册表 + 删 PostGIS 表 + 删上传文件 + 清 MapCache 缓存，配置自动重生成 |
| 验证 | 每次发布后跑 mapserv 命令行 GetCapabilities + GetMap 验证，失败自动回滚 |

## 启动

```bash
pg_ctlcluster 16 main start          # PostgreSQL（库 gisdb，账号 gis/gis）
cd phase1/app && python3 server.py   # :8090，打开 http://localhost:8090
bash phase1/test_phase1.sh           # 12 项端到端验证
```

服务只绑 `0.0.0.0:8090`（沙箱里用 localhost 访问；生产请放反代后面）。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端 |
| GET | `/api/services` | 服务列表 |
| GET | `/api/services/{slug}` | 服务详情（含端点） |
| POST | `/api/services` | 发布（multipart：name、type、file 或 source_slug、fill、outline、width） |
| DELETE | `/api/services/{slug}` | 下线 |
| GET | `/cgi-bin/mapserv?...` | MapServer 网关（WMS/WFS） |
| GET | `/cgi-bin/mapcache?...` | MapCache 网关（WMTS/TMS，KVP 会自动转 REST） |

## 实现要点

- **纯标准库**：`http.server` + `sqlite3`，无 Flask、无第三方依赖，
  沙箱与 Docker 用同一份代码。multipart 解析是手写的（不用已废弃的 `cgi` 模块）。
- **单一共享 mapfile**：所有服务共用 `maps/services.map`，
  每次发布/下线后从注册表重生成并验证，失败回滚到上一版。
- **PostGIS 入库**：矢量统一重投影到 EPSG:4326，表名 `svc_<slug>`，
  几何列 `wkb_geometry`，主键 `ogc_fid`。
- **网关**：`server.py` 内含 mapserv/mapcache 网关（subprocess 直调）。
  不用 `python -m http.server --cgi`——它会 `setuid(nobody)`，
  而 workspace 目录是 2770，nobody 进不去会 EACCES（Phase 0 踩过的坑）。
- **MapCache KVP 翻译**：Ubuntu 的 mapcache 只认 PATH_INFO（REST），
  网关把 WMTS KVP（`SERVICE=WMTS&REQUEST=GetTile...`）翻译成 REST 路径。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MAP_PORT` | 8090 | 监听端口 |
| `MAP_BASE_URL` | http://localhost:8090 | 写进 mapfile/mapcache 的对外地址 |
| `GIS_BASE` | phase1/ 目录 | 数据根目录（maps/、data/、cache/、services.db） |
| `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` | 127.0.0.1:5432/gisdb/gis/gis | PostGIS 连接 |

## Docker

见 `docker/`：`Dockerfile.app`（Ubuntu + apt GIS 栈 + 应用），
`docker-compose.yml`（app + postgis/postgis:16-3.4，命名卷持久化）。
沙箱里没有 Docker 守护进程，镜像未在本机构建，仅校验了 compose YAML 语法。

## 已知限制（Phase 2 再做）

- 样式只有填充/边线/线宽，无样式编辑器（GeoStyler 翻译层在 Phase 2）
- 矢量只按几何类型分面/线/点样式，不按属性分级
- 切片是即时生成（未预切）；预切任务队列在 Phase 2
- 单机单进程，无鉴权（本地验证用）
