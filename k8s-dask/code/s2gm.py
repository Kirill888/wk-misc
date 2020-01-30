import datetime
from typing import Tuple
from types import SimpleNamespace
from botocore.credentials import ReadOnlyCredentials
import toml
import jinja2
import sys

from datacube.utils.geometry import CRS
from datacube.model import GridSpec
import odc.algo
from odc.index import odc_uuid


def month_range(year: int, month: int, n: int) -> Tuple[datetime.datetime, datetime.datetime]:
    """ Return time range covering n months start from year, month
        month 1..12
        month can also be negative
        2020, -1 === 2019, 12
    """
    if month < 0:
        return month_range(year-1, 12+month+1, n)

    y2 = year
    m2 = month + n
    if m2 > 12:
        m2 -= 12
        y2 += 1
    dt_eps = datetime.timedelta(microseconds=1)

    return (datetime.datetime(year=year, month=month, day=1),
            datetime.datetime(year=y2, month=m2, day=1) - dt_eps)


def season_range(year: int, season: str) -> Tuple[datetime.datetime, datetime.datetime]:
    """ Season is one of djf, mam, jja, son.

        DJF for year X starts in Dec X-1 and ends in Feb X.
    """
    seasons = dict(
        djf=-1,
        mam=2,
        jja=6,
        son=9)

    start_month = seasons.get(season.lower())
    if start_month is None:
        raise ValueError(f"No such season {season}, valid seasons are: djf,mam,jja,son")
    return month_range(year, start_month, 3)


def transform_to_yaml_text(transform, precision=3):
    fmt = '[{:.{n}f},{:.{n}f},{:.{n}f},  {:.{n}f},{:.{n}f},{:.{n}f},  {:.0f},{:.0f},{:.0f}]'
    return fmt.format(*transform, n=precision)


def mk_utm_gs(epsg,
              resolution=10,
              pixels_per_cell=10_000,
              origin=(0, 0)):
    if not isinstance(resolution, tuple):
        resolution = (-resolution, resolution)

    tile_size = tuple([abs(r)*pixels_per_cell for r in resolution])

    return GridSpec(crs=CRS(f'epsg:{epsg}'),
                    resolution=resolution,
                    tile_size=tile_size,
                    origin=origin)


def utm_key(epsg, tidx=None):
    if isinstance(epsg, tuple):
        tidx = epsg[1:]
        epsg = epsg[0]

    if 32601 <= epsg <= 32660:
        zone, code = epsg-32600, 'N'
    elif 32701 <= epsg <= 32760:
        zone, code = epsg - 32700, 'S'
    else:
        raise ValueError(f"Not a utm epsg: {epsg}, valid ranges [32601, 32660] and [32701, 32760]")

    if tidx is None:
        return f'{zone:02d}{code}'

    return f'{zone:02d}{code}_{tidx[0]:02d}_{tidx[1]:02d}'


def utm_zone_to_epsg(zone):
    """
      56S -> 32756
      55N -> 32655
    """
    if len(zone) < 2:
        raise ValueError(f'Not a valid zone: "{zone}", expect <int: 1-60><str:S|N>')

    offset = dict(S=32700,
                  N=32600).get(zone[-1].upper())

    if offset is None:
        raise ValueError(f'Not a valid zone: "{zone}", expect <int: 1-60><str:S|N>')

    try:
        i = int(zone[:-1])
    except ValueError:
        i = None

    if i < 0 or i > 60:
        i = None

    if i is None:
        raise ValueError(f'Not a valid zone: "{zone}", expect <int: 1-60><str:S|N>')

    return offset + i


def to_object(d):
    def _convert(d):
        if isinstance(d, dict):
            return SimpleNamespace(**{k: _convert(v) for k, v in d.items()})
        elif isinstance(d, list):
            return [_convert(v) for v in d]
        else:
            return d

    return _convert(d)


def mk_task(tile, cfg, **extra):
    epsg, x, y = tile.region
    utm_code = utm_key(epsg)
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

        dataset_prefix=f"{utm_code}_{x:02d}_{y:02d}/{year:04d}{month:02d}/",
        file_prefix=f'S2_GM-{utm_code}_{x:02d}_{y:02d}-{start}_{end}',

        **extra
    )


def utm_tile_dss(dss):
    """

    Returns
    =======

    List of Tile objects, each is:
      .region    : (epsg,  tile_idx_x, tile_idx_y)
      .grid_spec : GridSpec
      .geobox    : GeoBox
      .dss       : [Dataset]
    """
    grid_specs = {}
    tiles = {}

    for ds in dss:
        epsg = ds.crs.epsg
        if epsg not in grid_specs:
            grid_specs[epsg] = (mk_utm_gs(epsg), {})

        gs, g_cache = grid_specs.get(epsg)

        for tidx, geobox in gs.tiles_from_geopolygon(ds.extent, geobox_cache=g_cache):
            region = (epsg, *tidx)
            tile = tiles.get(region, None)

            if tile is None:
                tile = SimpleNamespace(
                    region=region,
                    grid_spec=gs,
                    geobox=geobox,
                    dss=[])
                tiles[region] = tile

            tile.dss.append(ds)

    return sorted(tiles.values(), key=lambda t: t.region)


def load_config(fname):
    cfg = to_object(toml.load(fname))

    cfg.s3.creds = ReadOnlyCredentials(cfg.s3.key,
                                       cfg.s3.secret,
                                       None)
    cfg.period = season_range(cfg.year, cfg.season)

    cfg.selected_epsgs = set([utm_zone_to_epsg(z) for z in cfg.utm_zones])
    return cfg


def load_task(task, dc, cfg=None):
    if cfg is None:
        cfg = getattr(task, 'cfg', None)

    if cfg is not None:
        chunks = {'y': cfg.dask.load_chunks[0],
                  'x': cfg.dask.load_chunks[1]}
    else:
        chunks = {}

    xx = dc.load(
        like=task.geobox,
        measurements=task.bands + ['fmask'],
        group_by='solar_day',
        datasets=task.dss,
        dask_chunks=chunks)

    xx.attrs['_task'] = task

    return xx


def mk_geomedian(xx, cfg=None):
    if cfg is None:
        cfg = xx._task.cfg

    chunk_y, chunk_x = cfg.dask.work_chunks

    nocloud = odc.algo.fmask_to_bool(xx.fmask, ('water', 'snow', 'valid'))
    xx_data = xx[cfg.bands]
    xx_clean = odc.algo.keep_good_only(xx_data, where=nocloud)
    xx_clean = xx_clean.chunk(chunks=dict(time=-1, x=chunk_x, y=chunk_y))

    return odc.algo.int_geomedian(xx_clean, scale=1/10_000)


def task_uuid(task, **other_tags):
    sources = [ds.id for ds in task.dss]
    return odc_uuid(algorithm='geomedian',
                    algorithm_version='1.0.0',
                    sources=sources,
                    sensor='S2AB',
                    region=task.region,
                    period=task.period,
                    **other_tags)


def render_task_yaml(task, processing_datetime=None):
    if processing_datetime is None:
        processing_datetime = datetime.datetime.utcnow()

    return _YAML.render(task=task,
                        _self=sys.modules[__name__],
                        processing_datetime=processing_datetime)


_YAML = jinja2.Template('''---
# Dataset
$schema: https://schemas.opendatacube.org/dataset
id: {{ task.uuid}}

product:
  name: {{ task.product }}
  href: https://collections.dea.ga.gov.au/product/{{task.product}}

crs: {{ task.geobox.crs }}
grids:
  default:
    shape: [{{ task.geobox.shape[0] }}, {{ task.geobox.shape[1] }}]
    transform: {{ _self.transform_to_yaml_text(task.geobox.transform, 1) }}

properties:
  odc:region_code: {{ _self.utm_key(task.region) }}
  datetime: {{ task.period[0].strftime("%Y-%m-%dT%H:%M:%S.%f") }}
  dtr:start_datetime: {{ task.period[0].strftime("%Y-%m-%dT%H:%M:%S.%f") }}
  dtr:end_datetime: {{ task.period[1].strftime("%Y-%m-%dT%H:%M:%S.%f") }}
  odc:file_format: GeoTIFF
  odc:processing_datetime: {{ processing_datetime.strftime("%Y-%m-%dT%H:%M:%S") }}

measurements:
{% for band in task.bands %}
  {{ band }}:
    path: {{ task.file_prefix }}_{{ band }}.tif
{% endfor %}

lineage:
  inputs:
  {% for ds in task.dss %}
  - {{ ds.id }}
  {% endfor %}
...
''', trim_blocks=True)
