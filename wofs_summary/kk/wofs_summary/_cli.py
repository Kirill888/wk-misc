import click
from datacube import Datacube

from ._wofs_stats import (
    do_annual_wofs_stats,
    start_local_dask,
    mk_africa_albers_gs,
)


@click.command('wws')
@click.option('--env', '-E', type=str, help='Datacube environment name')
@click.option('-z', 'zlevel', type=int, default=6, help='Compression setting for deflate 1-fast, 9+ good but slow')
@click.option('--nthreads', type=int, default=16,
              help='Number of threads per worker')
@click.option('--nprocs', type=int, default=1,
              help='Number of worker processes')
@click.argument('year', type=int, nargs=1)
@click.argument('output', type=str, nargs=1)
def cli(env, year, output, zlevel, nthreads, nprocs):
    client = start_local_dask()
    dc = Datacube(env=env)
    # TODO #
    pass


if __name__ == '__main__':
    cli()
