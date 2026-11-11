# Phase 1 应用镜像：Ubuntu 24.04 + MapServer/GDAL/MapCache + 纯标准库 Python 应用
# 与 Phase 0 沙箱验证用的 apt 包完全一致（见 phase0/README.md）。
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -o Acquire::Languages=none \
 && apt-get install -y --no-install-recommends \
      python3 \
      cgi-mapserver \
      gdal-bin \
      postgresql-client \
      mapcache-cgi \
      mapcache-tools \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY phase1/app /app

# 数据根目录（maps/、data/、cache/、services.db 都在这里，compose 用卷持久化）
ENV GIS_BASE=/data
ENV MAP_PORT=8090
ENV MAP_BASE_URL=http://localhost:8090
ENV PGHOST=db PGPORT=5432 PGDATABASE=gisdb PGUSER=gis PGPASSWORD=gis
EXPOSE 8090
CMD ["python3", "/app/server.py"]
