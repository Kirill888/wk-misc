#!/bin/bash

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 20 24 28 32; do
   #python3 ./utils/bench.py s3_tile_zip_-9_-18.txt $i M5XL_ZIP
   python3 ./utils/bench.py s3_tile_lzw_-9_-18.txt $i M5XL_LZW
done
