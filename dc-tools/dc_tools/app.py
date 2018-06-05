import click
import psycopg2
from types import SimpleNamespace
import random
import sys
from urllib.parse import urlparse

def random_string(prefix):
    return '{}{:04x}'.format(prefix, random.getrandbits(16))


def mk_grouper():
    dd = {}

    def mk_dataset(uuid, loc_id, t_in, t_out):
        return SimpleNamespace(uuid=uuid, loc_id=loc_id, time=(t_in, t_out))

    def _do_group(uri, lx, ly, t_in, t_out, uuid, loc_id, product):
        uri, *_ = uri.split('#')
        ds = mk_dataset(uuid, loc_id, t_in, t_out)
        f = dd.get(uri)
        if f is None:
            dd[uri] = SimpleNamespace(uri=uri,
                                      cell=(lx, ly),
                                      product=product,
                                      datasets=[ds])
        else:
            assert f.cell == (lx, ly)
            f.datasets.append(ds)

    def proc(*args):
        if len(args) == 0:
            return list(dd.values())
        return _do_group(*args)

    return proc


cli = click.Group(name='dctools', help="")


@cli.command(name="files")
@click.option('-h', '--host',
              type=str,
              default='130.56.244.105',
              help='Database server address')
@click.option('-p', '--port',
              type=int,
              default=6432,
              help='Database server port')
@click.option('--user',
              type=str,
              default=None,
              help='Database user name')
@click.option('--db', 'dbname',
              type=str,
              default='datacube',
              help='Database name')
@click.argument('product')
def files(host, port, user, dbname, product):
    """ List files belonging to a product
    """
    if len(host) == 0:
        host = None
        port = None

    db = psycopg2.connect(host=host, port=port, user=user, dbname=dbname)

    c = db.cursor(random_string('cursor'))

    c.execute('''SELECT
CONCAT(dataset_location.uri_scheme, ':', dataset_location.uri_body) AS uri,
((dataset.metadata #>> '{grid_spatial, projection, geo_ref_points, ll, x}')::float/product.tx)::integer AS llx,
((dataset.metadata #>> '{grid_spatial, projection, geo_ref_points, ll, y}')::float/product.ty)::integer AS lly,
(dataset.metadata #>> '{extent, from_dt}')::timestamp AS from_dt,
(dataset.metadata #>> '{extent, to_dt}')::timestamp AS to_dt,
dataset.id AS uuid,
dataset_location.id as loc_id,
product.name AS product

FROM ((agdc.dataset INNER JOIN
     (SELECT id,
        name,
        (definition #>> '{storage,tile_size,x}')::float AS tx,
        (definition #>> '{storage,tile_size,y}')::float AS ty
        FROM agdc.dataset_type
        WHERE name=%(product)s) AS product
      ON product.id = dataset.dataset_type_ref)
INNER JOIN agdc.dataset_location ON dataset.id=dataset_location.dataset_ref)
WHERE dataset.archived is NULL
AND dataset_location.archived is NULL
;
''', dict(product=product))

    proc = mk_grouper()

    for idx, v in enumerate(c):
        proc(*v)
        if (idx % 10000) == 0:
            sys.stderr.write('.')
            sys.stderr.flush()

    for f in proc():
        uri = urlparse(f.uri)
        if uri.scheme == 'file':
            uri = uri.path
        else:
            uri = f.uri

        print('{f.product:>16s}, {f.cell[0]:3d}, {f.cell[1]:3d}, {n:4d}, {uri}'.format(f=f, uri=uri, n=len(f.datasets)))


####################################################################
# tests
####################################################################
def test_random_string():
    s1 = random_string('kk')
    s2 = random_string('kk')

    assert s1 != s2
    assert s1.startswith('kk')
    assert s2.startswith('kk')
