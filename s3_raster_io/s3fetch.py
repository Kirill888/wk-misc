import botocore
import botocore.session
from urllib.parse import urlparse
import threading
import math
import zlib
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures as fut
import numpy as np
import sys

from . import tifprobe

_thread_lcl = threading.local()


def get_s3_client(region_name='ap-southeast-2', max_pool_connections=32):
    s3 = getattr(_thread_lcl, 's3', None)
    if s3 is None:
        session = botocore.session.get_session()

        s3 = session.create_client('s3',
                                   region_name=region_name,
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
    if s3 is None:
        s3 = get_s3_client()

    hdr = tif_read_header(url, hdr_max_sz, s3=s3)

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

    return hdr, im


class S3TiffReader(object):
    def __init__(self, nthreads, region_name='ap-southeast-2'):
        self._region_name = region_name
        self._nthreads = nthreads
        self._pool = ThreadPoolExecutor(max_workers=nthreads)

    def warmup(self):
        def proc():
            return get_s3_client(self._region_name)

        fut.wait([self._pool.submit(proc) for _ in range(self._nthreads)])

    def read_headers(self, urls, hdr_max_sz=4096):
        out = [None for u in urls]

        def proc(idx, url):
            s3 = get_s3_client()
            bb = get_byte_range(url, 0, hdr_max_sz, s3)
            hdr = tifprobe.hdr_from_bytes(bb)
            out[idx] = hdr
            return idx, True

        futures = [self._pool.submit(proc, idx, url) for idx, url in enumerate(urls)]
        ngood = len(fut.wait(futures).done)
        assert ngood == len(urls)

        return out

    def read_chunk(self, urls, tile_idx, dst, hdr_max_sz=4096, submit_order=None):

        def proc(idx, url):
            _, im = tif_read_tile(url, tile_idx, hdr_max_sz=hdr_max_sz, dtype=dst.dtype)
            assert dst.shape[1:] == im.shape
            dst[idx, :, :] = im

        if submit_order is None:
            submit_order = range(len(urls))

        futures = [self._pool.submit(proc, idx, urls[idx]) for idx in submit_order]
        ngood = len(fut.wait(futures).done)
        assert ngood == len(futures)

        return dst
