import os
from types import SimpleNamespace
from botocore.credentials import ReadOnlyCredentials
import toml

from datacube import Datacube
import odc.algo
from odc.index import (
    odc_uuid,
    utm_region_code,
    utm_zone_to_epsg,
    season_range,
    utm_tile_dss,
    render_eo3_yaml,
)

from datacube.utils.cog import to_cog
from datacube.utils.dask import save_blob_to_s3


def to_object(d, with_env=True):
    def _convert(d):
        if isinstance(d, dict):
            return SimpleNamespace(**{k: _convert(v) for k, v in d.items()})
        elif isinstance(d, list):
            return [_convert(v) for v in d]
        elif isinstance(d, str) and with_env:
            if d.startswith('env/'):
                return os.environ.get(d[4:], None)
            else:
                return d
        else:
            return d

    return _convert(d)


def task_uuid(task, **other_tags):
    sources = [ds.id for ds in task.dss]
    return odc_uuid(algorithm='geomedian',
                    algorithm_version='1.0.0',
                    sources=sources,
                    sensor='S2AB',
                    region=task.region,
                    period=task.period,
                    **other_tags)


def mk_task(tile, cfg, **extra):
    epsg, x, y = tile.region
    utm_code = utm_region_code(epsg)
    period = cfg.period
    year = period[0].year
    month = period[0].month
    start, end = (t.strftime('%Y%m%d') for t in period)

    sensor = extra.pop('sensor', 'S2')
    uuid_extra = extra.pop('uuid_extra', {})

    uuid = odc_uuid(algorithm='geomedian',
                    algorithm_version='1.0.0',
                    sources=[ds.id for ds in tile.dss],
                    sensor=sensor,
                    region=tile.region,
                    period=period,
                    **uuid_extra)

    return SimpleNamespace(
        uuid=uuid,
        region=tile.region,
        dss=sorted(tile.dss, key=lambda ds: ds.time),
        period=period,
        geobox=tile.geobox,
        bands=cfg.bands,
        product=cfg.output_product,
        region_code=utm_region_code(tile.region),

        input_bands=cfg.input_bands,

        dataset_prefix=f"{utm_code}_{x:02d}_{y:02d}/{year:04d}{month:02d}/",
        file_prefix=f'S2_GM-{utm_code}_{x:02d}_{y:02d}-{start}_{end}',

        **extra
    )


def dss_to_tasks(dss, cfg):
    if cfg.selected_epsgs:
        dss = (ds for ds in dss if ds.crs.epsg in cfg.selected_epsgs)

    return [mk_task(t, cfg) for t in utm_tile_dss(dss)]


def load_config(fname):
    cfg = to_object(toml.load(fname))

    cfg.s3.creds = ReadOnlyCredentials(cfg.s3.key,
                                       cfg.s3.secret,
                                       None)
    cfg.period = season_range(cfg.year, cfg.season)

    cfg.selected_epsgs = set([utm_zone_to_epsg(z) for z in cfg.utm_zones])
    cfg.input_bands = cfg.bands + ['fmask']

    return cfg


def load_task_input(task, cfg=None, group_by='solar_day', **kw):
    if cfg is None:
        cfg = getattr(task, 'cfg', None)

    if cfg is not None:
        chunks = {'y': cfg.dask.load_chunks[0],
                  'x': cfg.dask.load_chunks[1]}
    else:
        chunks = kw.pop('dask_chunks', {})

    if len(task.dss) == 0:
        return None

    product = task.dss[0].type
    measurements = product.lookup_measurements(task.input_bands)

    xx = Datacube.load_data(
        Datacube.group_datasets(task.dss, group_by),
        task.geobox,
        measurements=measurements,
        dask_chunks=chunks,
        **kw)

    return xx


def mk_fmask_geomedian(xx, cfg, pix_scale=1/10_000):
    chunk_y, chunk_x = cfg.dask.work_chunks

    nocloud = odc.algo.fmask_to_bool(xx.fmask, ('water', 'snow', 'valid'))
    xx_data = xx[cfg.bands]
    xx_clean = odc.algo.keep_good_only(xx_data, where=nocloud)
    xx_clean = xx_clean.chunk(chunks=dict(time=-1, x=chunk_x, y=chunk_y))

    return odc.algo.int_geomedian(xx_clean, scale=pix_scale)


def process_task(task, cfg):
    output_prefix = cfg.s3.prefix + task.dataset_prefix + task.file_prefix
    creds = cfg.s3.creds

    xx = load_task_input(task, cfg)
    gm = mk_fmask_geomedian(xx, cfg)

    cog_params = cfg.cog.__dict__
    transform_precision = 0  # TODO: config or auto-sense

    cogs = [save_blob_to_s3(to_cog(x, **cog_params),
                            f'{output_prefix}_{n}.tif',
                            creds=creds,
                            ContentType="image/tiff")
            for n, x in gm.data_vars.items()]

    yaml_txt = render_eo3_yaml(task,
                               transform_precision=transform_precision)  # note: bakes in processing_time

    return save_blob_to_s3(yaml_txt.encode('utf-8'),
                           f'{output_prefix}.yaml',
                           creds=creds,
                           with_deps=cogs,             # this ensures that yaml is written after COGs
                           ContentType="text/x-yaml")
