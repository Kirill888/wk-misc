import xarray as xr
from pathlib import Path
from dask import array as da

from datacube.storage.masking import make_mask
from datacube import Datacube
from datacube.utils.geometry import CRS
from datacube.model import GridSpec
from datacube.utils.rio import set_default_rio_config
from ._cog import write_cog


def worker_setup():
    # these settings will be applied in every worker thread
    set_default_rio_config(aws={'region_name': 'us-west-2'},
                           cloud_defaults=True)


def start_local_dask(n_workers=1,
                     threads_per_worker=16,
                     **kw):
    from distributed import Client

    mem = kw.pop('memory_limit', None)
    if mem is None:
        from psutil import virtual_memory
        total_bytes = virtual_memory().total
        mem = total_bytes//n_workers

    client = Client(n_workers=n_workers,
                    threads_per_worker=threads_per_worker,
                    memory_limit=mem)

    client.register_worker_callbacks(worker_setup)

    return client


def mk_africa_albers_gs(pixels_per_cell=5000, pix_sz=30):
    return GridSpec(crs=CRS('epsg:102022'),  # really esri:102022
                    resolution=(-pix_sz, pix_sz),
                    tile_size=(pix_sz*pixels_per_cell, pix_sz*pixels_per_cell),
                    origin=(0, 0))


def wofs_stats(xx):
    attrs = {'crs': xx.crs}

    xx_wet = make_mask(xx.water, wet=True).sum(dim='time', dtype='int16')
    xx_dry = make_mask(xx.water, dry=True).sum(dim='time', dtype='int16')
    xx_freq = xx_wet.astype('float32')/(xx_wet + xx_dry)

    out = xr.Dataset({'count_wet': xx_wet,
                      'count_dry': xx_dry,
                      'frequency': xx_freq},
                     attrs=attrs)

    for var in out.data_vars.values():
        var.attrs.update(**attrs)

    return out


def do_annual_wofs_stats(tidx,
                         year,
                         output_dir,
                         env=None,
                         grid=None,
                         datasets=None):
    fname_fmt = "WOFS_{epsg}_{tx:d}_{ty:d}_{year:d}_summary_{band}.tif"

    if grid is None:
        grid = mk_africa_albers_gs()

    if not isinstance(output_dir, Path):
        output_dir = Path(output_dir)

    dc = Datacube(env=env)

    geobox = grid.tile_geobox(tidx)
    query = dict(
        product='ls_usgs_wofs_scene',
        time=str(year),
        geopolygon=geobox.extent)

    xx = dc.load(**query,
                 resolution=geobox.resolution,
                 output_crs=geobox.crs,
                 dask_chunks={'x': 2500, 'y': 2500},
                 group_by='solar_day',
                 datasets=datasets)

    ww_ = wofs_stats(xx)
    ww, = da.compute(ww_)

    cog_opts = dict(overview_resampling='average',
                    overview_levels=[4, 8, 16],
                    predictor=2,  # force it even for float32, seems to work better
                    zlevel=6)

    tx, ty = tidx
    fmt_opts = dict(epsg=geobox.crs.epsg,
                    tx=tx,
                    ty=ty,
                    year=year)

    for band in ww.data_vars:
        file_name = fname_fmt.format(**fmt_opts, band=band)

        write_cog(output_dir/file_name,
                  ww[band],
                  **cog_opts)
