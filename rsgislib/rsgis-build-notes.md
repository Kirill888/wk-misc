Prepare build environment

1. Install dependencies provided by Ubuntu 20.04

```bash
apt-get install -y \
  cmake \
  cmake-curses-gui \
  patchelf \
  python3-dev \
  python3-pip \
  python3-wheel \
  libcgal-dev \
  libgsl-dev \
  libmuparser-dev \
  libxerces-c-dev \
  libboost-filesystem-dev \
  libboost-date-time-dev \
  libhdf5-dev \

python3 -m pip install --upgrade pip wheel
```

NOTE: `libgeos++-dev` is missing `.inl` files, so needs to be patched from source package.
NOTE: `libgdal-dev` doesn't even ship c++ headers at all

So need to build your own, libgeos < 3.8.0

3. Download and compile compatible libgeos as a static lib

```bash
V_GEOS=3.7.2
curl -s -L https://github.com/libgeos/geos/archive/${V_GEOS}.tar.gz | tar xz
mkdir b-geos
(cd b-geos &&
  cmake ../geos-${V_GEOS} \
 -DCMAKE_BUILD_TYPE=Release \
 -DCMAKE_INSTALL_PREFIX=/usr/local/geos-${V_GEOS} \
 -DGEOS_BUILD_SHARED=OFF \
 -DGEOS_BUILD_STATIC=ON \
 -DGEOS_ENABLE_TESTS=OFF \
 -DCMAKE_POSITION_INDEPENDENT_CODE=ON )

make -C b-geos -j$(nproc) install/strip
```

3. Download source code

```bash
V=4.1.95
URL="https://github.com/remotesensinginfo/rsgislib/archive/refs/tags/${V}.tar.gz"
SRC="rsgislib-${V}"

curl -s -L "$URL" | tar xz
ls $SRC
```

patch CMakeLists.txt to not link to CGAL, and to use static linking for geos

```
diff --git a/CMakeLists.txt b/CMakeLists.txt
index 41d1dd2..2ee7c14 100755
--- a/CMakeLists.txt
+++ b/CMakeLists.txt
@@ -341,7 +341,7 @@ add_definitions(-DGEOS_INLINE)
 if (MSVC)
     set(GEOS_LIBRARIES -LIBPATH:${GEOS_LIB_PATH} geos.lib)
 else()
-    set(GEOS_LIBRARIES -L${GEOS_LIB_PATH} -lgeos)
+    set(GEOS_LIBRARIES -L${GEOS_LIB_PATH} -Wl,-Bstatic -lgeos -Wl,-Bdynamic -lm)
 endif(MSVC)

 include_directories(${GSL_INCLUDE_DIR})
@@ -374,7 +374,7 @@ if (MSVC)
     message(STATUS "Using CGAL lib " ${CGAL_LIB_NAME})
     set(CGAL_LIBRARIES -LIBPATH:${CGAL_LIB_PATH} ${CGAL_LIB_NAME})
 else()
-    set(CGAL_LIBRARIES -L${CGAL_LIB_PATH} -lCGAL)
+       #set(CGAL_LIBRARIES -L${CGAL_LIB_PATH} -lCGAL)
 endif(MSVC)

 include_directories(${HDF5_INCLUDE_DIR})
```

4. Build and install rsgislib
   - Assume that GDAL,KEA are installed in `/usr/local/{lib|include}`
   - Build static libs and python DLLs
   - looks like rsgislib doesn't like geos 3.8 shipped with ubuntu 20.04
   - needs 3.7.* series because of use of C++ interfaces
   - CGAL is header only now, so need to comment out `set(CGAL_LIBRARIES ...)` in cmake


```bash
V_GEOS=3.7.2
V=4.1.95

mkdir b-rsgis
(cd b-rsgis &&
cmake ../rsgislib-${V} \
-DCMAKE_BUILD_TYPE=Release \
-DCMAKE_INSTALL_PREFIX=$(pwd)/rootfs \
-DBUILD_SHARED_LIBS=OFF \
-DCMAKE_POSITION_INDEPENDENT_CODE=ON \
-D_Python_PREFIX=/usr/lib \
-DRSGIS_PYTHON=ON \
-DRSGISLIB_WITH_UTILTIES=OFF \
-DRSGISLIB_WITH_DOCUMENTS=OFF \
-DGEOS_INCLUDE_DIR=/usr/local/geos-${V_GEOS}/include \
-DGEOS_LIB_PATH=/usr/local/geos-${V_GEOS}/lib \
-DGDAL_INCLUDE_DIR=/urs/local/include \
-DGDAL_LIB_PATH=/usr/local/lib \
-DKEA_LIB_PATH=/usr/local/lib \
-DKEA_INCLUDE_DIR=/usr/local/include \
-DHDF5_INCLUDE_DIR=/usr/include/hdf5/serial \
-DHDF5_LIB_PATH=/usr/lib/x86_64-linux-gnu/hdf5/serial
)

make -C b-rsgis install/strip -j$(nproc)
```

5. Package as binary wheel

```bash
V=4.1.95
dst=$(pwd)
cd ./b-rsgis/rootfs/lib/python3/dist-packages

cat > setup.py <<EOF
from setuptools import setup, find_packages
from setuptools.dist import Distribution

class BinaryDistribution(Distribution):
    def is_pure(self):
        return False
    def has_ext_modules(self):
        return True

setup(
    name='rsgislib',
    version='${V}',
    author='Pete Bunting',
    author_email='petebunting@mac.com',
    description='The Remote Sensing and GIS software library (RSGISLib) is a collection of Python modules for processing remote sensing and GIS datasets.',
    long_description='',
    license='GPLv3',
    install_requires=["numpy", "tqdm", "GDAL", "h5py", "rios"],
    packages=find_packages('.'),
    include_package_data=True,
    zip_safe=False,
    distclass=BinaryDistribution
)
EOF
find rsgislib/ -name "_*so" | awk '{print "include " $0}' > MANIFEST.in
python3 setup.py bdist_wheel -d ${dst} -b /tmp
cd $dst
```

## runtime dependencies (ubuntu 20.04)

```
libboost-date-time1.71.0
libboost-filesystem1.71.0
libgmp10
libgsl23
libhdf5-103
libhdf5-cpp-103
libmuparser2v5
libxerces-c3.2
```



# MISC notes

link.txt
```
/usr/bin/c++ -fPIC  -fPIC -Wall -Wpointer-arith -Wcast-align -Wcast-qual -Wredundant-decls -Wno-long-long -std=c++14 -O3 -DNDEBUG  -shared -Wl,-soname,_imagecalc.so -o _imagecalc.so CMakeFiles/_imagecalc.dir/src/imagecalc.cpp.o   \
 -L/root/3p/rsgislib-4.1.95/python/../src  -Wl,-rpath,/root/3p/rsgislib-4.1.95/python/../src:
 /usr/lib/x86_64-linux-gnu/libpython3.8.so
 ../src/librsgis_cmds.a
 ../src/librsgis_calib.a
 ../src/librsgis_classify.a
 ../src/librsgis_filter.a
 ../src/librsgis_modeling.a
 ../src/librsgis_radar.a
 ../src/librsgis_vec.a
 ../src/librsgis_registration.a
 ../src/librsgis_segmentation.a
 ../src/librsgis_rastergis.a
 ../src/librsgis_histocube.a
 ../src/librsgis_img.a
 ../src/librsgis_geom.a
 ../src/librsgis_utils.a
 ../src/librsgis_maths.a
 ../src/librsgis_datastruct.a
 ../src/librsgis_commons.a
 -lxerces-c
 -lboost_filesystem -lboost_system -lboost_date_time
 -L/usr/local/lib
 -lgdal
 -lgsl
 -lgslcblas
 -L/usr/local/geos-3.7.3/lib -Wl,-Bstatic -lgeos -Wl,-Bdynamic
 -lm
 -lmuparser
 -L/usr/lib/x86_64-linux-gnu/hdf5/serial -lhdf5 -lhdf5_hl -lhdf5_cpp
 -lgmp
 -lmpfr
 -lkea


```


### KEA Lib

```
mkdir -p build && cd build
cmake .. \
-DCMAKE_BUILD_TYPE=Release \
-DLIBKEA_WITH_GDAL=OFF \
-DBUILD_SHARED_LIBS=ON \
-DCMAKE_POSITION_INDEPENDENT_CODE=ON \
-DCMAKE_INSTALL_PREFIX="/usr/local"

```

### GEOS lib
