import botocore
import botocore.session
from urllib.parse import urlparse
import threading
import math
import zlib
import numpy as np
import sys
from timeit import default_timer as t_now
from types import SimpleNamespace
import re
from . import tifprobe
from .parallel import ParallelStreamProc

_thread_lcl = threading.local()


def get_s3_client(region_name='ap-southeast-2',
                  max_pool_connections=32,
                  use_ssl=True):
    s3 = getattr(_thread_lcl, 's3', None)
    if s3 is None:
        protocol = 'https' if use_ssl else 'http'
        session = botocore.session.get_session()

        s3 = session.create_client('s3',
                                   region_name=region_name,
                                   endpoint_url='{}://s3.{}.amazonaws.com'.format(protocol, region_name),
                                   config=botocore.client.Config(max_pool_connections=max_pool_connections))
        setattr(_thread_lcl, 's3', s3)
    return s3


def s3_ls(url):
    uu = urlparse(url)

    bucket = uu.netloc
    prefix = uu.path.lstrip('/')

    s3 = get_s3_client()
    paginator = s3.get_paginator('list_objects')

    n_skip = len(prefix)
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for o in page['Contents']:
            yield o['Key'][n_skip:]


def s3_fancy_ls(url, sort=True,
                random_prefix_length=None,
                absolute=False,
                predicate=None):
    """
    predicate -- None| str -> Bool | regex string
    random_prefix_length int -- number of characters to skip for sorting: fh4e6_0, ahfe8_1 ... 00aa3_9, if =6
    """
    def get_sorter():
        if random_prefix_length is None:
            return None
        return lambda s: s[random_prefix_length:]

    def normalise_predicate(predicate):
        if predicate is None:
            return None

        if isinstance(predicate, str):
            regex = re.compile(predicate)
            return lambda s: regex.match(s) is not None

        return predicate

    predicate = normalise_predicate(predicate)

    if url[-1] != '/':
        url += '/'

    names = s3_ls(url)

    if predicate:
        names = [n for n in names if predicate(n)]

    if sort:
        names = sorted(names, key=get_sorter())

    if absolute:
        names = [url+name for name in names]

    return names


def get_byte_range(url, start, stop, s3):
    uu = urlparse(url)
    bucket_name = uu.netloc
    path = uu.path.lstrip('/')
    byte_range = 'bytes={:d}-{:d}'.format(start, stop - 1)
    response = s3.get_object(Bucket=bucket_name, Key=path, Range=byte_range)
    return response['Body'].read()


def tif_read_header(url, hdr_max_sz, s3=None):
    if s3 is None:
        s3 = get_s3_client()

    bb = get_byte_range(url, 0, hdr_max_sz, s3=s3)
    return tifprobe.hdr_from_bytes(bb)


def tif_tile_idx(hdr, row, col):
    # TODO: check image has tiling info and tile_idx is valid
    n_tiles_across = math.ceil(hdr.info.ImageWidth/hdr.info.TileWidth)
    return row*n_tiles_across + col


def tif_read_tile(url, tile_idx, hdr_max_sz=4096, s3=None, dtype=None):
    t0 = t_now()
    if s3 is None:
        s3 = get_s3_client()

    hdr = tif_read_header(url, hdr_max_sz, s3=s3)
    t1 = t_now()

    if not isinstance(tile_idx, int):
        tile_idx = tif_tile_idx(hdr, *tile_idx)

    if hdr.info.Compression not in (8, 0x80B2):
        raise ValueError('Only support DEFLATE compression (for now)')
    if hdr.info.Predictor not in (1,):
        raise ValueError('Do not support horizontal differencing predictor (for now)')

    offset = hdr.info.TileOffsets[tile_idx]
    nbytes = hdr.info.TileByteCounts[tile_idx]

    bb = get_byte_range(url, offset, offset + nbytes, s3=s3)
    bb = zlib.decompress(bb)

    if dtype is None:
        return hdr, bb

    im = np.ndarray((hdr.info.TileLength, hdr.info.TileWidth), dtype=dtype, buffer=bb)

    if hdr.byteorder != sys.byteorder:
        im.byteswap(inplace=True)

    t2 = t_now()

    stats = SimpleNamespace(t_open=t1-t0,
                            t_total=t2-t0,
                            chunk_size=nbytes)

    return hdr, im, stats


class S3TiffReader(object):

    @staticmethod
    def header_stream_proc(src_stream, out, hdr_max_sz):
        s3 = get_s3_client()

        for idx, url in src_stream:
            bb = get_byte_range(url, 0, hdr_max_sz, s3)
            hdr = tifprobe.hdr_from_bytes(bb)
            out[idx] = hdr

    @staticmethod
    def tile_stream_proc(src_stream, tile_idx, dst, stats, hdr_max_sz):
        s3 = get_s3_client()

        for idx, url in src_stream:
            _, im, st = tif_read_tile(url, tile_idx, hdr_max_sz=hdr_max_sz, dtype=dst.dtype, s3=s3)
            assert dst.shape[1:] == im.shape
            dst[idx, :, :] = im
            stats[idx] = st

    def __init__(self, nthreads,
                 region_name='ap-southeast-2',
                 use_ssl=True):
        self._region_name = region_name
        self._use_ssl = use_ssl
        self._nthreads = nthreads
        self._pstream = ParallelStreamProc(nthreads)

        self._rdr_header = self._pstream.bind(S3TiffReader.header_stream_proc)
        self._rdr_tile = self._pstream.bind(S3TiffReader.tile_stream_proc)

    def warmup(self):
        self._pstream.broadcast(lambda: get_s3_client(self._region_name, use_ssl=self._use_ssl))

    def read_headers(self, urls, hdr_max_sz=4096):
        out = [None for u in urls]
        self._rdr_header(enumerate(urls), out, hdr_max_sz)
        return out

    def read_chunk(self, urls, tile_idx, dst, hdr_max_sz=4096):
        t0 = t_now()
        stats = [None for _ in urls]

        self._rdr_tile(enumerate(urls), tile_idx, dst, stats, hdr_max_sz=hdr_max_sz)

        t1 = t_now()
        params = SimpleNamespace(band=1,
                                 block_shape=dst.shape[1:],
                                 nthreads=self._nthreads,
                                 hdr_max_sz=hdr_max_sz,
                                 dtype=dst.dtype.name,
                                 block=tile_idx)

        return dst, SimpleNamespace(params=params,
                                    t_total=t1 - t0,
                                    stats=stats)
