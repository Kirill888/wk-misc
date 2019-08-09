import xarray as xr
from pathlib import Path
from dask import array as da
from datetime import datetime
from jinja2 import Template

from datacube.storage.masking import make_mask
from datacube import Datacube
from datacube.utils.geometry import CRS
from datacube.model import GridSpec
from datacube.utils.rio import set_default_rio_config
from ._cog import write_cog
from odc.index import odc_uuid

yaml_doc_tpl = Template('''$schema: https://schemas.opendatacube.org/dataset

id: {{uuid}}
product:
  name: ls_usgs_wofs_summary

crs: epsg:{{epsg}}

grids:
  default:
    shape: [{{width}}, {{height}}]
    transform: {{transform}}

measurements:
  count_wet:
    path: WOFS_{{epsg}}_{{tx}}_{{ty}}_{{year}}_summary_count_wet.tif
  count_dry:
    path: WOFS_{{epsg}}_{{tx}}_{{ty}}_{{year}}_summary_count_dry.tif
  frequency:
    path: WOFS_{{epsg}}_{{tx}}_{{ty}}_{{year}}_summary_frequency.tif

properties:
  datetime: {{year}}-01-01T00:00:00.000
  dtr:start_datetime: {{year}}-01-01T00:00:00.000
  dtr:end_datetime: {{year}}-12-31T23:59:59.999
  odc:file_format: GeoTIFF
  odc:region_code: {{ "%+04d"%tx}}{{"%+04d"%ty}}
  odc:processing_datetime: {{processing_datetime}}
''')


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


def gs_uniq_string(gs):
    fmt = ":".join(["{:d}"]*7)
    nn = (gs.crs.epsg,) + gs.resolution + gs.tile_resolution + gs.alignment
    return fmt.format(*nn)


def mk_yaml(tidx, year, grid_spec,
            transform_precision=0,
            processing_datetime=None,
            **tags):
    transform_fmt = '[{:.{n}f},{:.{n}f},{:.{n}f},  {:.{n}f},{:.{n}f},{:.{n}f},  {:.0f},{:.0f},{:.0f}]'
    tx, ty = tidx
    gbox = grid_spec.tile_geobox(tidx)
    height, width = gbox.shape
    epsg = gbox.crs.epsg

    if processing_datetime is None:
        processing_datetime = datetime.utcnow().replace(microsecond=0, second=0)  # minute precision

    if not isinstance(processing_datetime, str):
        processing_datetime = processing_datetime.isoformat()

    _id = odc_uuid('wofs_summary',
                   algorithm_version='1',
                   sources=[],
                   # extra tags
                   period='annual',
                   grid=gs_uniq_string(grid_spec),
                   tx=tx, ty=ty, year=year, **tags)
    transform = transform_fmt.format(*gbox.transform, n=transform_precision)

    return yaml_doc_tpl.render(uuid=str(_id),
                               processing_datetime=processing_datetime,
                               epsg=epsg, year=year, tx=tx, ty=ty,
                               width=width, height=height, transform=transform)


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
                         dc=None,
                         grid=None,
                         zlevel=6,
                         datasets=None):
    fname_fmt = "WOFS_{epsg}_{tx:d}_{ty:d}_{year:d}_summary_{band}.tif"
    yml_fmt = "WOFS_{epsg}_{tx:d}_{ty:d}_{year:d}_summary.yaml"

    if grid is None:
        grid = mk_africa_albers_gs()

    if not isinstance(output_dir, Path):
        output_dir = Path(output_dir)

    if dc is None:
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
                    zlevel=zlevel)

    tx, ty = tidx
    fmt_opts = dict(epsg=geobox.crs.epsg,
                    tx=tx,
                    ty=ty,
                    year=year)

    yml_fname = yml_fmt.format(**fmt_opts)
    with open(output_dir/yml_fname, 'wt') as out:
        out.write(mk_yaml(tidx, year, grid))

    for band in ww.data_vars:
        file_name = fname_fmt.format(**fmt_opts, band=band)

        write_cog(output_dir/file_name,
                  ww[band],
                  **cog_opts)
