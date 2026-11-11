#!/usr/bin/env python3
"""Phase 1 发布管理 Web：上传 → 发布 → 列表/预览/下线，外加 mapserv/mapcache 网关。

纯标准库（http.server），无第三方依赖，沙箱与 Docker 用同一份代码。
端口：8090（Phase 0 的网关占 8080）。
"""
import json
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publisher  # noqa: E402
import store  # noqa: E402

BASE = os.environ.get("GIS_BASE") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
PORT = int(os.environ.get("MAP_PORT", "8090"))
BASE_URL = os.environ.get("MAP_BASE_URL", "http://localhost:%d" % PORT)


# ------------------------------------------------------------------ multipart 解析

def parse_multipart(body, content_type):
    """最小 multipart/form-data 解析。返回 (fields, files)。
    fields: {name: str}；files: {name: (filename, bytes)}。"""
    if "boundary=" not in content_type:
        raise ValueError("不是 multipart 请求")
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    sep = ("--" + boundary).encode()
    parts = body.split(sep)
    fields, files = {}, {}
    for part in parts[1:]:
        if part in (b"--\r\n", b"--", b""):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if part.endswith(b"--"):
            part = part[:-2]
        head, _, data = part.partition(b"\r\n\r\n")
        if not head:
            continue
        headers = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        disp = headers.get("content-disposition", "")
        params = {}
        for seg in disp.split(";"):
            seg = seg.strip()
            if "=" in seg:
                k, v = seg.split("=", 1)
                params[k.strip()] = v.strip().strip('"')
        name = params.get("name")
        if not name:
            continue
        filename = params.get("filename")
        if filename:
            files[name] = (filename, data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


# ------------------------------------------------------------------ 端点地址

def endpoints(svc):
    base = BASE_URL
    m = urllib.parse.quote(publisher.MAPFILE)
    out = {
        "wms_caps": "%s/cgi-bin/mapserv?map=%s&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities" % (base, m),
        "wms_map": "%s/cgi-bin/mapserv?map=%s&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=%s&STYLES=&CRS=EPSG:4326&BBOX=-180,-90,180,90&WIDTH=800&HEIGHT=400&FORMAT=image/png" % (base, m, svc["slug"]),
    }
    if svc["type"] == "vector":
        out["wfs"] = "%s/cgi-bin/mapserv?map=%s&SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAME=%s&COUNT=100" % (base, m, svc["slug"])
    if svc["type"] == "tiles":
        out["wmts_caps"] = "%s/cgi-bin/mapcache?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetCapabilities" % base
        out["wmts_tile"] = "%s/cgi-bin/mapcache?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile&LAYER=%s&STYLE=&FORMAT=image/png&TILEMATRIXSET=wgs84&TILEMATRIX=0&TILEROW=0&TILECOL=0" % (base, svc["slug"])
    return out


def public_service(svc):
    d = dict(svc)
    d["endpoints"] = endpoints(svc)
    return d


# ------------------------------------------------------------------ 发布/下线

def publish(fields, files):
    name = (fields.get("name") or "").strip()
    stype = (fields.get("type") or "").strip()
    if not name:
        return 400, {"error": "请填写服务名"}
    if stype not in ("raster", "vector", "tiles"):
        return 400, {"error": "类型只能是 raster / vector / tiles"}
    slug = publisher.slugify(name)
    if store.slug_exists(slug):
        return 409, {"error": "服务名 %s 已存在（slug: %s），换个名字" % (name, slug)}
    style = json.dumps({
        "fill": fields.get("fill") or "#6496dc",
        "outline": fields.get("outline") or "#143c8c",
        "width": int(fields.get("width") or 2),
    })
    row = {"slug": slug, "name": name, "type": stype, "status": "active",
           "style": style, "created_at": publisher.now(),
           "updated_at": publisher.now()}

    if stype in ("raster", "vector"):
        if "file" not in files:
            return 400, {"error": "请上传数据文件"}
        filename, data = files["file"]
        ext = os.path.splitext(filename)[1].lower()
        tmp = os.path.join(publisher.DATA_DIR,
                           ".upload-%s%s" % (slug, ext))
        shp_dir = os.path.join(publisher.DATA_DIR, ".shp-%s" % slug)
        with open(tmp, "wb") as f:
            f.write(data)
        try:
            if stype == "raster":
                ok, info = publisher.inspect_raster(tmp)
                if not ok:
                    return 400, {"error": info}
                ok, rel = publisher.store_raster(tmp, slug)
                if not ok:
                    return 400, {"error": rel}
                row["file_path"] = rel
            else:
                src = tmp
                if ext == ".zip":
                    shp, err = publisher.unpack_shapefile_zip(tmp, shp_dir)
                    if err:
                        return 400, {"error": err}
                    src = shp
                ok, info = publisher.inspect_vector(src)
                if not ok:
                    return 400, {"error": info}
                ok, table = publisher.store_vector(src, slug)
                if not ok:
                    return 400, {"error": table}
                row["table_name"] = table
                row["geom_type"] = info.get("geom_type")
                # 矢量数据以 PostGIS 为准，不保留上传文件
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
            if os.path.isdir(shp_dir):
                import shutil
                shutil.rmtree(shp_dir, ignore_errors=True)
    else:  # tiles
        source_slug = (fields.get("source_slug") or "").strip()
        src = store.get_service(source_slug) if source_slug else None
        if not src or src["type"] not in ("raster", "vector") \
                or src["status"] != "active":
            return 400, {"error": "切片需要选一个已发布的影像或矢量服务作为源"}
        row["source_slug"] = source_slug

    store.insert_service(row)
    try:
        publisher.regenerate(store.list_services(), BASE_URL)
    except Exception as e:  # noqa: BLE001
        store.delete_service(slug)
        return 500, {"error": "生成发布配置失败：%s" % e}
    if stype in ("raster", "vector"):
        ok, err = publisher.verify_layer(slug)
        if not ok:
            store.update_service(slug, status="error", error=err)
            return 500, {"error": err}
    return 201, public_service(store.get_service(slug))


def unpublish(slug):
    svc = store.get_service(slug)
    if not svc:
        return 404, {"error": "服务不存在"}
    if svc["type"] == "vector" and svc.get("table_name"):
        publisher.drop_table(svc["table_name"])
    if svc.get("file_path"):
        for p in (os.path.join(publisher.DATA_DIR, svc["file_path"]),
                  os.path.join(publisher.DATA_DIR, "%s.tif" % slug)):
            if os.path.exists(p):
                os.remove(p)
    if svc["type"] == "tiles":
        cache_dir = os.path.join(publisher.CACHE_DIR, slug)
        if os.path.isdir(cache_dir):
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)
    store.delete_service(slug)
    try:
        publisher.regenerate(store.list_services(), BASE_URL)
    except Exception as e:  # noqa: BLE001
        return 500, {"error": "重新生成配置失败：%s" % e}
    return 200, {"ok": True}


# ------------------------------------------------------------------ 网关（mapserv / mapcache）

def run_gateway(binary, extra_env, query, path_info=None):
    env = dict(os.environ)
    env["REQUEST_METHOD"] = "GET"
    env["QUERY_STRING"] = query
    if path_info is not None:
        env["PATH_INFO"] = path_info
    env.update(extra_env)
    r = subprocess.run([binary], env=env, capture_output=True, timeout=60)
    head, sep, body = r.stdout.partition(b"\r\n\r\n")
    if not sep:
        head, sep, body = r.stdout.partition(b"\n\n")
    if not sep:
        head, body = b"Content-Type: text/plain", r.stdout
    ctype = "application/octet-stream"
    for line in head.decode("utf-8", "replace").splitlines():
        if line.lower().startswith("content-type:"):
            ctype = line.split(":", 1)[1].strip()
    return ctype, body


def wmts_translate(query):
    """MapCache 只认 PATH_INFO（REST），把 WMTS KVP 翻译成 REST 路径。"""
    params = urllib.parse.parse_qs(query)
    svc = (params.get("SERVICE", [""])[0] or "").upper()
    req = (params.get("REQUEST", [""])[0] or "")
    if svc == "WMTS" and req.lower() == "getcapabilities":
        return "/wmts/1.0.0/WMTSCapabilities.xml", ""
    if svc == "WMTS" and req.lower() == "gettile":
        layer = params.get("LAYER", [""])[0]
        style = params.get("STYLE", ["default"])[0] or "default"
        tms = params.get("TILEMATRIXSET", ["wgs84"])[0]
        z = params.get("TILEMATRIX", ["0"])[0]
        row = params.get("TILEROW", ["0"])[0]
        col = params.get("TILECOL", ["0"])[0]
        fmt = params.get("FORMAT", ["image/png"])[0]
        ext = "png" if "png" in fmt else "jpeg"
        return ("/wmts/1.0.0/%s/%s/%s/%s/%s/%s.%s"
                % (layer, style, tms, z, row, col, ext)), ""
    return None, query


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(),
                                         args[0] % args[1:]))

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        fpath = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not fpath.startswith(STATIC_DIR) or not os.path.isfile(fpath):
            self.send_error(404, "not found")
            return
        ctype = {"html": "text/html; charset=utf-8",
                 "js": "application/javascript",
                 "css": "text/css"}.get(
                     os.path.splitext(fpath)[1].lstrip("."), "application/octet-stream")
        data = open(fpath, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/services":
            self._json([public_service(s) for s in store.list_services()])
            return
        if parsed.path.startswith("/api/services/"):
            slug = urllib.parse.unquote(parsed.path[len("/api/services/"):])
            svc = store.get_service(slug)
            if not svc:
                self._json({"error": "服务不存在"}, 404)
                return
            self._json(public_service(svc))
            return
        if parsed.path in ("/cgi-bin/mapserv", "/mapserv"):
            ctype, body = run_gateway(
                publisher.MAPSERV,
                {"MAPSERVER_CONFIG_FILE": publisher.MAPSERVER_CONF},
                parsed.query)
            self._send_gateway(ctype, body)
            return
        if parsed.path in ("/cgi-bin/mapcache", "/mapcache") or \
                parsed.path.startswith("/cgi-bin/mapcache/"):
            rest = parsed.path.split("mapcache", 1)[1] or "/"
            if parsed.query:
                pi, q = wmts_translate(parsed.query)
                if pi is not None:
                    rest, query = pi, q
                else:
                    query = parsed.query
            else:
                query = ""
            ctype, body = run_gateway(
                "/usr/lib/cgi-bin/mapcache",
                {"MAPCACHE_CONFIG_FILE": publisher.MAPCACHE_XML},
                query, path_info=rest)
            self._send_gateway(ctype, body)
            return
        self._static(parsed.path)

    def _send_gateway(self, ctype, body):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/services":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            fields, files = parse_multipart(
                body, self.headers.get("Content-Type") or "")
        except Exception as e:  # noqa: BLE001
            self._json({"error": "解析上传失败：%s" % e}, 400)
            return
        try:
            status, result = publish(fields, files)
        except Exception as e:  # noqa: BLE001
            status, result = 500, {"error": "发布失败：%s" % e}
        self._json(result, status)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/services/"):
            self._json({"error": "not found"}, 404)
            return
        slug = urllib.parse.unquote(parsed.path[len("/api/services/"):])
        try:
            status, result = unpublish(slug)
        except Exception as e:  # noqa: BLE001
            status, result = 500, {"error": "下线失败：%s" % e}
        self._json(result, status)


if __name__ == "__main__":
    publisher.ensure_config()
    if not os.path.exists(publisher.MAPFILE):
        publisher.regenerate(store.list_services(), BASE_URL)
    print("Phase 1 发布台：%s （MapServer/MapCache 网关同端口）" % BASE_URL,
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
