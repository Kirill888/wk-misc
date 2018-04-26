#!/bin/bash

src='tile_-9_-18'
dst='tile_-9_-18_zip'

mkdir -p "${dst}"

find $src -name "*tif" | xargs -P4 -I@ -n 1 ./recompress.sh @ $dst
