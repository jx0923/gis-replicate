#!/usr/bin/env python3
"""Phase 0 mapserv HTTP 网关（替代 python -m http.server --cgi）。

为什么不用标准 CGI：http.server 的 CGI 子进程会 os.setuid(nobody)，
而本沙箱的 workspace 目录是 2770 root:nogroup，nobody 无法进入，
execve 直接 EACCES。本网关以当前用户（root）直接跑 mapserv，
只做本地验证，不对外暴露。
用法：MAPSERVER_CONFIG_FILE 自动取本目录 mapserver.conf；
      python3 server.py [端口，默认 8080]
"""
import os
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
MAPFILE = os.path.join(BASE, "phase0.map")
CONFIG = os.path.join(BASE, "mapserver.conf")
PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._index()
            return
        if parsed.path not in ("/cgi-bin/mapserv", "/mapserv",
                              "/cgi-bin/mapcache", "/mapcache"):
            self.send_error(404, "only / , /cgi-bin/mapserv and /cgi-bin/mapcache")
            return
        if "mapcache" in parsed.path:
            binary = "/usr/lib/cgi-bin/mapcache"
            extra_env = {"MAPCACHE_CONFIG_FILE": os.path.join(BASE, "mapcache.xml")}
        else:
            binary = "/usr/bin/mapserv"
            extra_env = {"MAPSERVER_CONFIG_FILE": CONFIG}
        qs = parsed.query or (
            "map=%s&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities"
            % urllib.parse.quote(MAPFILE)
        )
        env = dict(os.environ)
        env["REQUEST_METHOD"] = "GET"
        env["QUERY_STRING"] = qs
        # MapCache 本编译版只认 PATH_INFO（REST 风格），KVP 的 SERVICE 参数会被忽略；
        # 这里把 WMTS KVP 请求翻译成 REST 路径再交给 mapcache。
        if "mapcache" in parsed.path:
            params = urllib.parse.parse_qs(qs)
            svc = (params.get("SERVICE", [""])[0] or "").upper()
            req = (params.get("REQUEST", [""])[0] or "")
            if svc == "WMTS" and req.lower() == "getcapabilities":
                env["PATH_INFO"] = "/wmts/1.0.0/WMTSCapabilities.xml"
                env["QUERY_STRING"] = ""
            elif svc == "WMTS" and req.lower() == "gettile":
                layer = params.get("LAYER", ["phase0"])[0]
                style = params.get("STYLE", ["default"])[0] or "default"
                tms = params.get("TILEMATRIXSET", ["wgs84"])[0]
                z = params.get("TILEMATRIX", ["0"])[0]
                row = params.get("TILEROW", ["0"])[0]
                col = params.get("TILECOL", ["0"])[0]
                fmt = params.get("FORMAT", ["image/png"])[0]
                ext = "png" if "png" in fmt else "jpeg"
                env["PATH_INFO"] = "/wmts/1.0.0/%s/%s/%s/%s/%s/%s.%s" % (
                    layer, style, tms, z, row, col, ext)
                env["QUERY_STRING"] = ""
            else:
                # 其余请求（TMS/WMS/demo）直接透传 PATH_INFO
                env["PATH_INFO"] = parsed.path.split("mapcache", 1)[1] or "/"
        env.update(extra_env)
        try:
            r = subprocess.run(
                [binary], env=env, capture_output=True, timeout=60
            )
        except Exception as e:  # noqa: BLE001
            self.send_response(500)
            self.end_headers()
            self.wfile.write(("gateway error: %s" % e).encode())
            return
        head, sep, body = r.stdout.partition(b"\r\n\r\n")
        if not sep:  # 退回 LF 分隔
            head, sep, body = r.stdout.partition(b"\n\n")
        if not sep:  # 没输出头就当纯文本回
            head, body = b"Content-Type: text/plain", r.stdout
        ctype = "application/octet-stream"
        for line in head.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _index(self):
        base = "http://localhost:%d/cgi-bin/mapserv?map=%s" % (
            PORT,
            urllib.parse.quote(MAPFILE),
        )
        html = """<html><body><h1>Phase 0 MapServer</h1><ul>
<li><a href="{b}&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities">WMS GetCapabilities</a></li>
<li><a href="{b}&SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetCapabilities">WMTS GetCapabilities</a></li>
<li><a href="{b}&SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAME=parks">WFS parks</a></li>
<li><a href="{b}&SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=base_raster,parks,roads&STYLES=&CRS=EPSG:4326&BBOX=39.85,116.30,40.00,116.50&WIDTH=800&HEIGHT=600&FORMAT=image/png">GetMap PNG</a></li>
</ul></body></html>""".format(b=base)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, *args):  # 安静
        pass


if __name__ == "__main__":
    print("serving %s on 127.0.0.1:%d" % (BASE, PORT), flush=True)
    print("MAPSERVER_CONFIG_FILE=%s" % CONFIG, flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
