"""Phase 1 发布引擎：上传校验 → 入库/落盘 → 生成 services.map 与 mapcache.xml → 验证。"""
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime

BASE = os.environ.get("GIS_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))  # phase1/（Docker 里由 GIS_BASE 指定）
APP_DIR = os.path.join(BASE, "app")
MAPS_DIR = os.path.join(BASE, "maps")
DATA_DIR = os.path.join(BASE, "data")
CACHE_DIR = os.path.join(BASE, "cache")

MAPFILE = os.path.join(MAPS_DIR, "services.map")
MAPCACHE_XML = os.path.join(MAPS_DIR, "mapcache.xml")
MAPSERVER_CONF = os.path.join(MAPS_DIR, "mapserver.conf")

PG = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": os.environ.get("PGPORT", "5432"),
    "dbname": os.environ.get("PGDATABASE", "gisdb"),
    "user": os.environ.get("PGUSER", "gis"),
    "password": os.environ.get("PGPASSWORD", "gis"),
}
MAPSERV = shutil.which("mapserv") or "/usr/bin/mapserv"
GDALINFO = shutil.which("gdalinfo") or "/usr/bin/gdalinfo"
OGRINFO = shutil.which("ogrinfo") or "/usr/bin/ogrinfo"
OGR2OGR = shutil.which("ogr2ogr") or "/usr/bin/ogr2ogr"
GDALWARP = shutil.which("gdalwarp") or "/usr/bin/gdalwarp"


def now():
    return datetime.now().isoformat(timespec="seconds")


def slugify(name):
    """服务 slug：只保留 a-z0-9-（MapServer 图层名、PostGIS 表名、URL 都安全）。
    中文名没有 ASCII 字符时，用 svc-<md5 前 6 位>，确定性生成。"""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        import hashlib
        slug = "svc-" + hashlib.md5(name.encode("utf-8")).hexdigest()[:6]
    return slug


def _run(cmd, **kw):
    binary = kw.pop("binary", False)
    return subprocess.run(cmd, capture_output=True,
                          text=not binary,
                          timeout=kw.pop("timeout", 120), **kw)


def pg_conn_str():
    return ("host=%(host)s port=%(port)s dbname=%(dbname)s "
            "user=%(user)s password=%(password)s" % PG)


def pg_dsn():
    return ("PG:host=%(host)s port=%(port)s dbname=%(dbname)s "
            "user=%(user)s password=%(password)s" % PG)


# ---------------------------------------------------------------- 数据校验与处理

def inspect_raster(path):
    """返回 (ok, info|error)。info 含 width/height/srs。"""
    r = _run([GDALINFO, "-json", path])
    if r.returncode != 0:
        return False, "gdalinfo 失败：%s" % (r.stderr.strip()[:300] or "不是有效影像")
    try:
        info = json.loads(r.stdout)
    except ValueError:
        return False, "gdalinfo 输出无法解析"
    srs = (info.get("coordinateSystem") or {}).get("wkt", "")
    return True, {"width": info.get("size", [0, 0])[0],
                  "height": info.get("size", [0, 0])[1],
                  "has_srs": bool(srs)}


def inspect_vector(path):
    """返回 (ok, info|error)。info 含 layer/geom_type/count。"""
    r = _run([OGRINFO, "-so", "-json", path])
    if r.returncode != 0:
        return False, "ogrinfo 失败：%s" % (r.stderr.strip()[:300] or "不是有效矢量")
    try:
        info = json.loads(r.stdout)
    except ValueError:
        return False, "ogrinfo 输出无法解析"
    layers = info.get("layers", [])
    if not layers:
        return False, "文件里没有图层"
    layer = layers[0]
    return True, {"layer": layer.get("name"),
                  "geom_type": layer.get("geometryFields", [{}])[0].get("type"),
                  "count": layer.get("featureCount")}


def store_raster(src_path, slug):
    """影像落到 data/，统一重投影到 EPSG:4326。返回 (ok, rel_path|error)。"""
    dst = os.path.join(DATA_DIR, "%s.tif" % slug)
    r = _run([GDALWARP, "-t_srs", "EPSG:4326", "-of", "GTiff",
              "-co", "COMPRESS=DEFLATE", src_path, dst])
    if r.returncode != 0:
        return False, "重投影失败：%s" % r.stderr.strip()[:300]
    return True, "%s.tif" % slug


def store_vector(src_path, slug):
    """矢量导进 PostGIS（表 svc_<slug>，统一 EPSG:4326）。返回 (ok, table|error)。"""
    t = slug.replace("-", "_")
    table = t if t.startswith("svc_") else "svc_" + t
    r = _run([OGR2OGR, "-f", "PostgreSQL", pg_dsn(), src_path,
              "-nln", table, "-overwrite", "-t_srs", "EPSG:4326",
              "-lco", "GEOMETRY_NAME=wkb_geometry", "-lco", "FID=ogc_fid"])
    if r.returncode != 0:
        return False, "导入 PostGIS 失败：%s" % (r.stderr.strip()[:500])
    return True, table


def drop_table(table):
    if not table:
        return
    _run(["psql", "-h", PG["host"], "-p", PG["port"], "-U", PG["user"],
          "-d", PG["dbname"], "-c", 'DROP TABLE IF EXISTS "%s";' % table],
         env={**os.environ, "PGPASSWORD": PG["password"]})


def unpack_shapefile_zip(zip_path, dest_dir):
    """解压 shapefile zip，返回 .shp 路径。"""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        shps = [n for n in names if n.lower().endswith(".shp")]
        if not shps:
            return None, "zip 里没有 .shp 文件"
        z.extractall(dest_dir)
    return os.path.join(dest_dir, shps[0]), None


# ---------------------------------------------------------------- mapfile / mapcache 生成

def _color(style, key, default):
    v = (style or {}).get(key, default)
    if isinstance(v, str) and v.startswith("#") and len(v) == 7:
        return "%d %d %d" % (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))
    return default


_GEOM_TO_MS = {
    "polygon": "POLYGON", "multipolygon": "POLYGON",
    "linestring": "LINE", "multilinestring": "LINE",
    "point": "POINT", "multipoint": "POINT",
}


def _ms_type(geom_type):
    return _GEOM_TO_MS.get((geom_type or "polygon").lower(), "POLYGON")


def layer_block(svc):
    style = json.loads(svc.get("style") or "{}")
    width = int(style.get("width", 2))
    if svc["type"] == "raster":
        return """  LAYER
    NAME "%(slug)s"
    TYPE RASTER
    STATUS ON
    DATA "%(file)s"
    PROJECTION "init=epsg:4326" END
    METADATA
      "wms_title" "%(name)s"
      "wms_srs" "EPSG:4326"
    END
  END
""" % {"slug": svc["slug"], "file": svc["file_path"],
       "name": svc["name"]}
    if svc["type"] == "vector":
        geom = _ms_type(svc.get("geom_type"))
        return """  LAYER
    NAME "%(slug)s"
    TYPE %(geom)s
    STATUS ON
    CONNECTIONTYPE POSTGIS
    CONNECTION "%(conn)s"
    DATA "wkb_geometry FROM %(table)s USING UNIQUE ogc_fid USING SRID=4326"
    PROJECTION "init=epsg:4326" END
    METADATA
      "wms_title" "%(name)s"
      "wfs_title" "%(name)s"
      "gml_include_items" "all"
      "wms_include_items" "all"
    END
    CLASS
      NAME "%(name)s"
      STYLE
        COLOR %(fill)s
        OUTLINECOLOR %(outline)s
        WIDTH %(width)d
      END
    END
  END
""" % {"slug": svc["slug"], "geom": geom, "conn": pg_conn_str(),
       "table": svc["table_name"], "name": svc["name"],
       "fill": _color(style, "fill", "100 150 220"),
       "outline": _color(style, "outline", "20 60 140"), "width": width}
    return ""  # tiles 不进 mapfile，进 mapcache.xml


def generate_mapfile(services, base_url):
    layers = "".join(layer_block(s) for s in services
                     if s["type"] in ("raster", "vector")
                     and s["status"] == "active")
    content = """# 自动生成：phase1/app/publisher.py generate_mapfile，切勿手改
MAP
  NAME "services"
  STATUS ON
  SIZE 800 600
  EXTENT -180 -90 180 90
  UNITS DD
  SHAPEPATH "%(data)s"
  PROJECTION "init=epsg:4326" END
  IMAGETYPE PNG
  WEB
    IMAGEPATH "/tmp/ms_tmp/"
    IMAGEURL "/tmp/"
    METADATA
      "wms_title" "Phase1 Services"
      "wms_onlineresource" "%(base)s/cgi-bin/mapserv?map=%(mapfile)s"
      "ows_onlineresource" "%(base)s/cgi-bin/mapserv?map=%(mapfile)s"
      "wfs_onlineresource" "%(base)s/cgi-bin/mapserv?map=%(mapfile)s"
      "wms_srs" "EPSG:4326 EPSG:3857"
      "wms_enable_request" "*"
      "wfs_enable_request" "*"
      "wfs_srs" "EPSG:4326"
    END
  END
%(layers)sEND
""" % {"data": DATA_DIR, "base": base_url, "mapfile": MAPFILE,
       "layers": layers}
    _atomic_write(MAPFILE, content)


def generate_mapcache(services, base_url):
    tiles = [s for s in services if s["type"] == "tiles"
             and s["status"] == "active"]
    tilesets = ""
    for s in tiles:
        tilesets += """  <tileset name="%(slug)s">
    <source>src_%(slug)s</source>
    <cache>disk</cache>
    <grid>wgs84</grid>
    <format>PNG</format>
    <metatile>1 1</metatile>
    <metabuffer>0</metabuffer>
    <expires>3600</expires>
  </tileset>
""" % {"slug": s["slug"]}
    sources = ""
    for s in tiles:
        sources += """  <source name="src_%(slug)s" type="wms">
    <getmap>
      <params>
        <FORMAT>image/png</FORMAT>
        <LAYERS>%(source)s</LAYERS>
        <MAP>%(mapfile)s</MAP>
      </params>
    </getmap>
    <http>
      <url>%(base)s/cgi-bin/mapserv</url>
    </http>
  </source>
""" % {"slug": s["slug"], "source": s["source_slug"],
       "mapfile": MAPFILE, "base": base_url}
    content = """<?xml version="1.0" encoding="UTF-8"?>
<!-- 自动生成：phase1/app/publisher.py generate_mapcache，切勿手改 -->
<mapcache>
  <cache name="disk" type="disk">
    <base>%s</base>
  </cache>
%s%s  <grid name="wgs84">
    <srs>EPSG:4326</srs>
    <units>dd</units>
    <extent>-180 -90 180 90</extent>
    <size>256 256</size>
    <resolutions>0.703125 0.3515625 0.17578125 0.087890625 0.0439453125 0.02197265625 0.01098632812 0.00549316406 0.00274658203 0.00137329101</resolutions>
  </grid>
%s  <service type="wmts" enabled="true"/>
  <service type="tms" enabled="true"/>
  <service type="wms" enabled="true"/>
  <service type="demo" enabled="true"/>
</mapcache>
""" % (CACHE_DIR, sources, tilesets, "")
    _atomic_write(MAPCACHE_XML, content)


def _atomic_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def ensure_config():
    """mapserver.conf（MS_MAP_PATTERN 白名单）与目录。"""
    os.makedirs(MAPS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs("/tmp/ms_tmp", exist_ok=True)
    if not os.path.exists(MAPSERVER_CONF):
        _atomic_write(MAPSERVER_CONF, """CONFIG
  ENV
    MS_MAP_PATTERN "^%s"
    MS_MAPFILE_PATTERN "\\.map$"
    MS_ERRORFILE "/tmp/ms_tmp/ms_error.log"
    MS_DEBUGLEVEL "0"
  END
END
""" % BASE)


# ---------------------------------------------------------------- 验证与回滚

def verify_mapfile():
    """mapserv 命令行跑 GetCapabilities，返回 (ok, error)。"""
    env = dict(os.environ)
    env["MAPSERVER_CONFIG_FILE"] = MAPSERVER_CONF
    r = _run([MAPSERV, "-nh",
              "QUERY_STRING=map=%s&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities"
              % MAPFILE, "-conf", MAPSERVER_CONF], env=env)
    if r.returncode != 0 or b"WMS_Capabilities" not in r.stdout.encode():
        err = (r.stdout + r.stderr)[:400]
        return False, "mapfile 验证失败：%s" % err
    return True, ""


def verify_layer(slug):
    """对指定图层跑一次 GetMap，必须返回 PNG。"""
    env = dict(os.environ)
    env["MAPSERVER_CONFIG_FILE"] = MAPSERVER_CONF
    r = _run([MAPSERV, "-nh",
              "QUERY_STRING=map=%s&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
              "&LAYERS=%s&STYLES=&CRS=EPSG:4326&BBOX=-180,-90,180,90"
              "&WIDTH=256&HEIGHT=128&FORMAT=image/png" % (MAPFILE, slug),
              "-conf", MAPSERVER_CONF], env=env, binary=True)
    out = r.stdout or b""
    if b"PNG" not in out[:200]:
        return False, "图层 %s 出图失败：%s" % (
            slug, (out[:200] + r.stderr[:200]).decode("utf-8", "replace"))
    return True, ""


def regenerate(services, base_url):
    """重生成 mapfile + mapcache.xml 并验证；失败则抛异常（调用方回滚）。"""
    ensure_config()
    backup_map = backup_cache = None
    if os.path.exists(MAPFILE):
        backup_map = open(MAPFILE, encoding="utf-8").read()
    if os.path.exists(MAPCACHE_XML):
        backup_cache = open(MAPCACHE_XML, encoding="utf-8").read()
    try:
        generate_mapfile(services, base_url)
        generate_mapcache(services, base_url)
        ok, err = verify_mapfile()
        if not ok:
            raise RuntimeError(err)
    except Exception:
        if backup_map is not None:
            _atomic_write(MAPFILE, backup_map)
        elif os.path.exists(MAPFILE):
            os.remove(MAPFILE)
        if backup_cache is not None:
            _atomic_write(MAPCACHE_XML, backup_cache)
        elif os.path.exists(MAPCACHE_XML):
            os.remove(MAPCACHE_XML)
        raise
    return True
