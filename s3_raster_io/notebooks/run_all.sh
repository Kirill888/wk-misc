#!/bin/bash

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 20 24 28 32; do
   #python3 ./utils/bench.py s3_tile_-9_-18_zip.txt $i M5XL_ZIP rio
   #python3 ./utils/bench.py s3_tile_-9_-18_lzw.txt $i M5XL_LZW rio
   #python3 ../../runbench.py s3_tile_-9_-18_zip2.txt $i M5XL_ZIP2 s3tif
   python3 ../../runbench.py s3_tile_-9_-18_zip2.txt $i M5XL_ZIP2R rio
done
