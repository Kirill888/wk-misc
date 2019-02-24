import click
import psycopg2
from types import SimpleNamespace
import random
import sys
from urllib.parse import urlparse


def random_string(prefix):
    return '{}{:04x}'.format(prefix, random.getrandbits(16))


def get_managed_products(db):
    c = db.cursor()
    c.execute('''SELECT
dataset_type.id AS id,
dataset_type.name AS product,
(dataset_type.definition #>> '{storage,tile_size,x}')::float AS tx,
(dataset_type.definition #>> '{storage,tile_size,y}')::float AS ty

FROM agdc.dataset_type
WHERE
    (dataset_type.definition #>> '{managed}')::bool AND
    (dataset_type.definition -> 'storage' ? 'tile_size');
''')

    products = {}

    for (pid, name, tx, ty) in c.fetchall():
        products[name] = SimpleNamespace(name=name, id=pid, tx=tx, ty=ty)

    c.close()
    return products


def mk_grouper():
    dd = {}

    def mk_dataset(uuid, loc_id, t_in, t_out, uri):
        return SimpleNamespace(uuid=uuid, loc_id=loc_id, time=(t_in, t_out), uri=uri)

    def _do_group(uri, lx, ly, t_in, t_out, uuid, loc_id, product):
        uri_base, *_ = uri.split('#')
        ds = mk_dataset(uuid, loc_id, t_in, t_out, uri)
        f = dd.get(uri_base)
        if f is None:
            dd[uri_base] = SimpleNamespace(uri=uri_base,
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


def mk_location_query(db, p):
    c = db.cursor(random_string('cursor'))

    c.execute('''SELECT
CONCAT( dataset_location.uri_scheme, ':', dataset_location.uri_body) AS uri,
    ((dataset.metadata #>> '{grid_spatial, projection, geo_ref_points, ll, x}')::float/%(tx)s)::integer AS llx,
    ((dataset.metadata #>> '{grid_spatial, projection, geo_ref_points, ll, y}')::float/%(ty)s)::integer AS lly,
    (dataset.metadata #>> '{extent, from_dt}')::timestamp AS from_dt,
    (dataset.metadata #>> '{extent, to_dt}')::timestamp AS to_dt,
    dataset.id AS uuid,
    dataset_location.id as loc_id,
    %(product_name)s AS product

FROM (agdc.dataset INNER JOIN
      agdc.dataset_location ON dataset.id=dataset_location.dataset_ref)
WHERE dataset.archived is NULL
    AND dataset_location.archived is NULL
    AND dataset.dataset_type_ref = %(product_id)s
;
''', dict(tx=p.tx, ty=p.ty, product_name=p.name, product_id=p.id))

    return c


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
@click.option('--stacked-only', is_flag=True, default=False,
              help="Only print files referenced by more than one dataset")
@click.argument('product')
def files(host, port, user, dbname, product, stacked_only):
    """ List files belonging to a product
    """
    if len(host) == 0:
        host = None
        port = None

    def process_one(db, prod):
        c = mk_location_query(db, prod)
        proc = mk_grouper()

        for idx, v in enumerate(c):
            proc(*v)
            if (idx % 10000) == 0:
                sys.stderr.write('.')
                sys.stderr.flush()

        for f in proc():
            if stacked_only and len(f.datasets) < 2:
                continue

            uri = urlparse(f.uri)
            if uri.scheme == 'file':
                uri = uri.path
            else:
                uri = f.uri

            print('{f.product:>16s} {f.cell[0]:3d} {f.cell[1]:3d} {n:4d} {uri}'.format(f=f, uri=uri, n=len(f.datasets)))

    db = psycopg2.connect(host=host, port=port, user=user, dbname=dbname)

    prods = get_managed_products(db)

    if product == '*all*':
        for prod in prods.values():
            sys.stderr.write('\n{}\n'.format(prod.name))
            process_one(db, prod)
            sys.stderr.flush()
    else:
        if product not in prods:
            click.echo('Product {} is not in a database or is not a managed product'.format(product), err=True)
            sys.exit(1)

        process_one(db, prods[product])


####################################################################
# tests
####################################################################
def test_random_string():
    s1 = random_string('kk')
    s2 = random_string('kk')

    assert s1 != s2
    assert s1.startswith('kk')
    assert s2.startswith('kk')


def test_get_managed_product():
    db = psycopg2.connect(dbname='kk2')
    print(get_managed_products(db))


def test_loc_query():
    db = psycopg2.connect(dbname='kk2')
    pp = get_managed_products(db)

    c = mk_location_query(db, pp['ls8_nbar_albers'])
    print(c.query.decode('ascii'))

    for x in c:
        print(x)
