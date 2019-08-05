from pathlib import Path
import rasterio
from rasterio.shutil import copy as rio_copy


def write_cog(fname,
              pix,
              overwrite=False,
              blocksize=None,
              overview_resampling=None,
              overview_levels=None,
              **extra_rio_opts):
    """ Write xarray.Array to GeoTiff file.
    """
    if blocksize is None:
        blocksize = 512
    if overview_levels is None:
        overview_levels = [2**i for i in range(1, 6)]

    if overview_resampling is None:
        overview_resampling = 'nearest'

    nodata = pix.attrs.get('nodata', None)
    resampling = rasterio.enums.Resampling[overview_resampling]

    if pix.ndim == 2:
        h, w = pix.shape
        nbands = 1
        band = 1
    elif pix.ndim == 3:
        nbands, h, w = pix.shape
        band = tuple(i for i in range(1, nbands+1))
    else:
        raise ValueError('Need 2d or 3d ndarray on input')

    if not isinstance(fname, Path):
        fname = Path(fname)

    if fname.exists():
        if overwrite:
            fname.unlink()
        else:
            raise IOError("File exists")

    gbox = pix.geobox

    if gbox is None:
        raise ValueError("Not geo-registered: check crs attribute")

    assert gbox.shape == (h, w)

    A = gbox.transform
    crs = str(gbox.crs)

    rio_opts = dict(width=w,
                    height=h,
                    count=nbands,
                    dtype=pix.dtype.name,
                    crs=crs,
                    transform=A,
                    tiled=True,
                    blockxsize=min(blocksize, w),
                    blockysize=min(blocksize, h),
                    zlevel=9,
                    predictor=3 if pix.dtype.kind == 'f' else 2,
                    compress='DEFLATE')

    if nodata is not None:
        rio_opts.update(nodata=nodata)

    rio_opts.update(extra_rio_opts)

    # copy re-compresses anyway so skip compression for temp image
    tmp_opts = rio_opts.copy()
    tmp_opts.pop('compress')
    tmp_opts.pop('predictor')
    tmp_opts.pop('zlevel')

    with rasterio.Env(GDAL_TIFF_OVR_BLOCKSIZE=blocksize):
        with rasterio.MemoryFile() as mem:
            with mem.open(driver='GTiff', **tmp_opts) as tmp:
                tmp.write(pix.values, band)
                tmp.build_overviews(overview_levels, resampling)

                rio_copy(tmp,
                         fname,
                         driver='GTiff',
                         copy_src_overviews=True,
                         **rio_opts)
