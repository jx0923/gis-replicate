# GIS 复刻 — Phase 0 技术验证（已完成，2026-11-11）

目标：验证“开源 GIS 栈能否跑通原版的核心链路”——MapServer 发布 WMS/WFS、
MapCache 提供 WMTS、PostGIS 存矢量、GDAL 处理影像。全部通过。

## 结论

| 链路 | 结果 |
|---|---|
| WMS GetCapabilities / GetMap（OGR 矢量 + GDAL 影像） | ✅ PNG 800×600，肉眼核对无误 |
| WFS GetFeature（OGR + PostGIS） | ✅ 返回 3 个公园要素 |
| WMTS GetCapabilities / GetTile（MapCache） | ✅ 瓦片 PNG 256×256，磁盘缓存已落盘 |
| PostGIS 入库 + MapServer 直连渲染 | ✅ 蓝色多边形与 OGR 版位置一致 |

验证脚本：`bash test.sh`（7 项全过，见 `out/`）。

## 版本（apt 原版，Ubuntu 24.04）

- MapServer 8.0.1（PROJ 9.4 / GDAL 3.8，WMS/WFS/WCS/OGC API server）
- GDAL 3.8.4（gdalinfo / ogr2ogr / gdal_create）
- PostgreSQL 16.15 + PostGIS 3.4（库 `gisdb`，表 parks/roads，账号 gis/gis，仅本地验证）
- MapCache 1.14.0（mapcache-cgi + mapcache-tools）

## 目录

- `phase0.map` — 地图文件：base_raster（GDAL 影像）+ parks/roads（OGR GeoJSON）+ parks_pg（PostGIS）
- `mapserver.conf` — MapServer 8 配置（MS_MAP_PATTERN 白名单）
- `mapcache.xml` — MapCache 配置（WMS 源 → 本地 MapServer，EPSG:4326 格网，磁盘缓存 `cache/`）
- `data/` — 测试数据（parks.geojson 3 公园、roads.geojson 3 条路、test_raster.tif）
- `server.py` — mapserv/mapcache 的 HTTP 网关（:8080）
- `start.sh` — 一键启动服务
- `test.sh` — 7 项验证
- `setup-postgis.sh` — 启动 PG cluster、建库、PostGIS 入库（跑一次）
- `out/` — 验证产物（test_map.png、tile0.png、test_pg.png 等）
- `cache/` — MapCache 磁盘缓存

## 启动（沙箱重启后）

```bash
cd ~/workspace/gis-replicate/phase0
pg_ctlcluster 16 main start        # PostgreSQL（若没跑）
bash start.sh                      # :8080，首页有 WMS/WMTS/WFS/GetMap 链接
bash test.sh                       # 7 项验证
```

服务只绑 127.0.0.1，沙箱内访问。`http://localhost:8080/` 首页有四个测试链接。

## 踩过的坑（都已解决，写在这里免得再踩）

1. **包里自带的 MapServer 8.6.1 不能直接用**：厂商打过补丁（每请求授权门禁），
   脱离其运行时布局报 `msLoadConfig` 错。Phase 0 用 apt 原版 8.0.1。
2. **MapServer 8 必须有配置文件**：无 `MAPSERVER_CONFIG_FILE` 时报
   `msLoadConfig(): Unable to access file`；配置文件里必须设 `MS_MAP_PATTERN`
  （map 文件路径白名单），否则报 `Required configuration value MS_MAP_PATTERN not set`。
   另注意：`-nh` 命令行模式下，查询串要用 `QUERY_STRING=...` 形式，
   裸 `map=...` 加 `-conf` 会丢查询串。
3. **python `-m http.server --cgi` 不能用**：其 CGI 子进程会 `os.setuid(nobody)`，
   而 workspace 目录是 `2770 root:nogroup`，nobody 进不去，execve 直接 EACCES。
   改用 `server.py`（subprocess 直接调 mapserv/mapcache，不降权）。
4. **Ubuntu 的 mapserv 8.0.1 不认 `SERVICE=WMTS`**：库里没有任何 "wmts" 字串，
   请求会掉进 BROWSE 模式。原版架构里 WMTS 本来就是 MapCache 的活，
   所以 WMTS 走 MapCache 1.14.0。
5. **MapCache CGI 只认 PATH_INFO（REST 风格）**：KVP 的 `SERVICE=WMTS` 会报
   `missing a service`。网关 `server.py` 已把 WMTS KVP 翻译成 REST 路径
   （`/wmts/1.0.0/.../WMTSCapabilities.xml`、`/wmts/1.0.0/{layer}/.../{z}/{row}/{col}.png`）。
6. **apt 很慢**：默认源是双镜像 × 4 套件 × 4 组件，`apt update` 要拉几百 MB。
   已精简为单镜像 azure + noble/noble-updates + main/restricted/universe、无翻译文件，
   7 秒完成。github/nodesource 两个第三方源会把 update 挂死，已挪走（备份在 /root/apt-sources-bak/）。
   另注意：沙箱里有些系统文件属主是 `nobody`（如原 ubuntu.sources），root 也写不了，
   要先 `rm` 再重建。
7. **umask 0007**：exec 会话默认 umask 0007，新建目录是 770、文件是 660，
   postgres 用户会因此读不到 /tmp/ms_tmp 下的文件。入库前记得 `chmod 755` 目录、
   `chmod 644` 数据文件。
8. **PostgreSQL 是 Debian 布局**：数据在 `/var/lib/postgresql/16/main`，
   配置在 `/etc/postgresql/16/main/`，启动用 `pg_ctlcluster 16 main start`，
   不要直接对数据目录跑 `pg_ctl`（会报缺 postgresql.conf）。
9. **WFS 需要 `wfs_onlineresource`**：只设 `wms_onlineresource` 时，
   GetFeature 报 `Server URL not found`。map 文件里已补 `ows_onlineresource` 与 `wfs_onlineresource`。

## 下一步（Phase 1 MVP，待用户确认）

按复刻报告的四阶段：Phase 1 做 Web+Docker 的发布管理 MVP（先 3 种服务类型：
影像/矢量/切片），含服务列表、发布/下线、基础样式。Electron 放 Phase 4。
