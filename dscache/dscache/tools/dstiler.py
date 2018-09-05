import click
import dscache
from .tiling import bin_dataset_stream, bin_by_native_tile
from datacube.model import GridSpec
import datacube.utils.geometry as geom


GS_ALBERS = GridSpec(crs=geom.CRS('EPSG:3577'),
                     tile_size=(100000.0, 100000.0),
                     resolution=(-25, 25))


@click.command('dstiler')
@click.option('--native', is_flag=True, help='Use Landsat Path/Row as grouping')
@click.argument('dbfile', type=str, nargs=1)
def cli(native, dbfile):
    """Add spatial grouping to file db.

    Default grid is Australian Albers (EPSG:3577) with 100k by 100k tiles. But
    you can also group by Landsat path/row.

    """
    cache = dscache.open_rw(dbfile)
    label = 'Processing {} ({:,d} datasets)'.format(dbfile, cache.count)

    if native:
        gs = None
        group_key_fmt = 'native/{:03d}{:03d}'
    else:
        gs = GS_ALBERS  # TODO: make configurable
        group_key_fmt = 'albers/{:+03d}{:+03d}'

    with click.progressbar(cache.get_all(), length=cache.count, label=label) as dss:
        if native:
            bins = bin_by_native_tile(dss)
        else:
            bins = bin_dataset_stream(gs, dss)

    click.echo('Total bins: {:d}'.format(len(bins)))

    with click.progressbar(bins.values(), length=len(bins), label='Saving') as groups:
        for group in groups:
            k = group_key_fmt.format(*group.idx)
            cache.put_group(k, group.dss)


if __name__ == '__main__':
    cli()
