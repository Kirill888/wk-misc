import sys
from types import SimpleNamespace
from jinja2 import Template
from odc.index import odc_uuid
import rasterio

tpl = Template(
    """id: {{uuid}}
$schema: 'https://schemas.opendatacube.org/dataset'
product:
  name: {{ cfg.product }}
crs: "epsg:{{epsg}}"
grids:
    default:
       shape: [{{shape[0]}}, {{shape[1]}}]
       transform: [{{transform[0]}}, {{transform[1]}}, {{transform[2]}}, {{transform[3]}}, {{transform[4]}}, {{transform[5]}}, 0, 0, 1]
properties:
   dtr:start_datetime: {{cfg.period[0]}}
   dtr:end_datetime:   {{cfg.period[1]}}
   odc:region_code: {{region_code}}
   odc:product_family: {{cfg.product_family}}
   eo:platform: {{cfg.platform}}
   eo:instrument: {{cfg.instrument}}

measurements:
   {% for band in cfg.bands %}{{band}}:
     path: {{path}}
     band: {{loop.index}}
   {% endfor %}
lineage: {}
"""
)

cfg = SimpleNamespace(
    bands=[
        "s2be_blue",
        "s2be_green",
        "s2be_red",
        "s2be_red_edge_1",
        "s2be_red_edge_2",
        "s2be_red_edge_3",
        "s2be_nir_1",
        "s2be_nir_2",
        "s2be_swir_2",
        "s2be_swir_3",
    ],
    product="s2_barest_earth",
    version="1.0",
    product_family="statistics",  # No idea
    period=["2017-01-01", "2020-09-01"],
    platform="Sentinel-2",  # No idea
    instrument="MSI",
)


def generate_yaml(path_or_url, cfg):
    src = rasterio.open(path_or_url)
    path = path_or_url.split("/")[-1]
    region_code = path.split(".")[0].split("-")[1]

    info = dict(
        uuid=odc_uuid(
            cfg.product,
            cfg.version,
            sources=[],
            period=cfg.period,
            region_code=region_code,
        ),
        epsg=src.meta["crs"].to_epsg(),
        region_code=region_code,
        shape=src.shape,
        transform=src.transform,
        path=path,
    )
    return tpl.render(cfg=cfg, **info)


if __name__ == "__main__":

    for src in sys.argv[1:]:
        dst = src.split('/')[-1].split('.')[0] + '.odc-metadata.yaml'
        print(f"Processing {src}->{dst}")
        txt = generate_yaml(src, cfg)

        with open(dst, "wt") as f:
            f.write(txt)
