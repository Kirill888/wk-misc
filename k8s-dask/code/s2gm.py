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
import yaml


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


def to_object(d):
    def _convert(d):
        if isinstance(d, dict):
            return SimpleNamespace(**{k: _convert(v) for k, v in d.items()})
        elif isinstance(d, list):
            return [_convert(v) for v in d]
        else:
            return d

    return _convert(d)


def utm_tile_dss(dss, **extra_keys):
    grid_specs = {}
    dss_by_tile = {}

    for ds in dss:
        epsg = ds.crs.epsg
        if epsg not in grid_specs:
            grid_specs[epsg] = (mk_utm_gs(epsg), {})

        gs, g_cache = grid_specs.get(epsg)

        for tidx, _ in gs.tiles_from_geopolygon(ds.extent, geobox_cache=g_cache):
            k = (epsg, *tidx)
            dss_by_tile.setdefault(k, []).append(ds)

    tasks = [SimpleNamespace(region=k,
                             dss=sorted(dss, key=lambda ds: ds.time),
                             grid_spec=grid_specs[k[0]][0],
                             **extra_keys)
             for k, dss in dss_by_tile.items()]

    tasks = sorted(tasks, key=lambda t: t.region)
    return tasks


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


def _to_yaml(obj):
    return yaml.dump(obj,
                     default_flow_style=False,
                     sort_keys=False,
                     Dumper=getattr(yaml, 'CSafeDumper', yaml.SafeDumper))


def build_yaml_template(cfg):
    measurements = {n: dict(path=f'<<file_prefix>>_{n}.tif')
                    for n in cfg.bands}

    mm_yaml_template = _to_yaml(dict(measurements=measurements))
    mm_yaml_template = mm_yaml_template.replace('<<', '{{').replace('>>', '}}')

    return '''---
# Dataset
$schema: https://schemas.opendatacube.org/dataset
id: {{uuid}}

product:
  name: {{product}}
  href: https://collections.dea.ga.gov.au/product/{{product}}

crs: {{ geobox.crs }}
grids:
  default:
    shape: [{{ geobox.shape[0] }}, {{ geobox.shape[1] }}]
    transform: {{ _self.transform_to_yaml_text(geobox.transform, 1) }}

properties:
  odc:region_code: {{region_code}}
  datetime: {{t_start}}
  dtr:start_datetime: {{t_start}}
  dtr:end_datetime: {{t_end}}
  odc:file_format: GeoTIFF
  odc:processing_datetime: {{processing_datetime}}

measurements:{% for band in bands %}
  {{ band }}:
    path: {{ file_prefix }}_{{ band }}.tif{% endfor %}

lineage:
  inputs: {% for ds in dss %}
  - {{ ds.id }}{% endfor %}
...
'''


def load_config(fname):
    cfg = to_object(toml.load('gmcfg.toml'))

    cfg.s3.creds = ReadOnlyCredentials(cfg.s3.key,
                                       cfg.s3.secret,
                                       None)
    cfg.period = season_range(cfg.year, cfg.season)

    cfg.selected_epsgs = set([utm_zone_to_epsg(z) for z in cfg.utm_zones])
    return cfg


def ds_prefix(task):
    epsg = task.region[0]
    x, y = task.region[1:3]
    utm_code = utm_key(epsg)
    year = task.period[0].year
    month = task.period[0].month

    return f"{utm_code}_{x:02d}_{y:02d}/{year:04d}{month:02d}/"


def transform_to_yaml_text(transform, precision=3):
    fmt = '[{:.{n}f},{:.{n}f},{:.{n}f},  {:.{n}f},{:.{n}f},{:.{n}f},  {:.0f},{:.0f},{:.0f}]'
    return fmt.format(*transform, n=precision)


def f_prefix(task):
    region_code = utm_key(task.region)
    start, end = (t.strftime('%Y%m%d') for t in task.period)

    f_prefix = f'S2_GM-{region_code}-{start}_{end}'
    return f_prefix


def load_task(task, dc, cfg=None):
    if cfg is None:
        cfg = task.cfg

    tidx = task.region[1:]
    geobox = task.grid_spec.tile_geobox(tidx)
    chunks = {'y': cfg.dask.load_chunks[0],
              'x': cfg.dask.load_chunks[1]}

    xx = dc.load(
        like=geobox,
        measurements=cfg.bands + ['fmask'],
        group_by='solar_day',
        datasets=task.dss,
        dask_chunks=chunks)

    xx.attrs['_cfg'] = cfg
    xx.attrs['_task'] = task

    return xx


def mk_geomedian(xx):
    cfg = xx._cfg
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


def render_task_yaml(task, cfg=None, processing_datetime=None):
    if cfg is None:
        cfg = task.cfg

    if processing_datetime is None:
        processing_datetime = datetime.datetime.utcnow()

    if isinstance(processing_datetime, datetime.datetime):
        processing_datetime = processing_datetime.strftime("%Y-%m-%dT%H:%M:%S")

    geobox = task.grid_spec.tile_geobox(task.region[1:])
    ny, nx = geobox.shape
    t_start, t_end = (p.strftime("%Y-%m-%dT%H:%M:%S.%f") for p in cfg.period)

    pp = dict(product="s2_gm_seasonal",
              uuid=task_uuid(task),
              geobox=geobox,
              _self=sys.modules[__name__],
              bands=cfg.bands,
              dss=task.dss,
              file_prefix=f_prefix(task),
              region_code=utm_key(task.region),
              t_start=t_start,
              t_end=t_end,
              processing_datetime=processing_datetime)

    return jinja2.Template(cfg.yaml_template).render(**pp)
