#!/bin/bash

recomp_deflate() {
   local src=${1}
   local dst=${2}
   local tsz=256

   gdal_translate \
    -co COMPRESS=DEFLATE \
    -co ZLEVEL=9 \
    -co PREDICTOR=1 \
    -co TILED=YES \
    -co BLOCKXSIZE=${tsz} \
    -co BLOCKYSIZE=${tsz} \
    -co PROFILE=GeoTiff \
    "${src}" "${dst}"
}

proc() {
   local src=${1}
   local dst_folder=${2}
   local dst="${dst_folder}/"$(basename $src)

   echo "$src" "=>" "$dst"
   recomp_deflate "${src}" "${dst}"
}

proc $@
