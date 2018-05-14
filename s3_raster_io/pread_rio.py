from timeit import default_timer as t_now
import rasterio
from types import SimpleNamespace
import threading
from .s3tools import auto_find_region, get_boto3_session
from .parallel import ParallelStreamProc

__all__ = ["PReadRIO", "PReadRIO_bench"]

_thread_lcl = threading.local()


def _session(region_name=None):
    return get_boto3_session(region_name, cache=_thread_lcl)


class PReadRIO(object):
    """This class will process a bunch of files in parallel. You provide a
    generator of (userdata, url) tuples and a callback that takes opened
    rasterio file handle and userdata. This class deals with launching threads
    and re-using them between calls and with setting up `rasterio.Env`
    appropriate for S3 access. Callback will be called concurrently from many
    threads, it should do it's own synchronization.

    This class is roughly equivalent to this serial code:

    ```
    with rasterio.Env(**cfg):
      for userdata, url in srcs:
         with rasterio.open(url,'r') as f:
            cbk(f, userdata)
    ```

    You should create one instance of this class per app and re-use it as much
    as practical. There is a significant setup cost, and it increases almost
    linearly with more worker threads. There is large latency for processing
    first file in the worker thread, some gdal per-thread setup, so it's
    important to re-use an instance of this class rather than creating a new
    one for each request.
    """
    @staticmethod
    def _process_file_stream(src_stream,
                             on_file_cbk,
                             gdal_opts=None,
                             region_name=None,
                             timer=None):
        session = _session(region_name)

        if timer is not None:
            def proc(url, userdata):
                t0 = timer()
                with rasterio.open(url, 'r') as f:
                    on_file_cbk(f, userdata, t0=t0)
        else:
            def proc(url, userdata):
                with rasterio.open(url, 'r') as f:
                    on_file_cbk(f, userdata)

        with rasterio.Env(session=session, **gdal_opts):
            for userdata, url in src_stream:
                proc(url, userdata)

    def __init__(self, nthreads,
                 region_name=None):
        if region_name is None:
            region_name = auto_find_region()  # Will throw on error

        self._nthreads = nthreads
        self._pstream = ParallelStreamProc(nthreads)
        self._process_files = self._pstream.bind(PReadRIO._process_file_stream)
        self._region_name = region_name

        self._gdal_opts = dict(VSI_CACHE=True,
                               CPL_VSIL_CURL_ALLOWED_EXTENSIONS='tif',
                               GDAL_DISABLE_READDIR_ON_OPEN=True)

    def warmup(self, action=None):
        """Mostly needed for benchmarking needs. Ensures that worker threads are
        started and have S3 credentials pre-loaded.

        If you need to setup some thread-local state you can supply action
        callback that will be called once in every worker thread.
        """
        def _warmup():
            session = _session(region_name=self._region_name)
            with rasterio.Env(session=session, **self._gdal_opts):
                if action:
                    action()
            return session.get_credentials()

        return self._pstream.broadcast(_warmup)

    def process(self, stream, cbk, timer=None):
        """
        stream: (userdata, url)...
        cbk:
           file_handle, userdata -> None (ignored)|
           file_handle, userdata, t0 -> None (ignored) -- when timer is supplied

        timer: None| ()-> TimeValue

        Equivalent to this serial code, but with many concurrent threads and
        with appropriate `rasterio.Env` wrapper for S3 access

        ```
        for userdata, url in stream:
            with rasterio.open(url,'r') as f:
               cbk(f, userdata)
        ```

        if timer is set:
        ```
        for userdata, url in stream:
            t0 = timer()
            with rasterio.open(url, 'r') as f:
               cbk(f, userdata, t0=t0)
        ```
        """
        self._process_files(stream, cbk,
                            self._gdal_opts,
                            region_name=self._region_name,
                            timer=timer)


class PReadRIO_bench(object):
    def __init__(self, nthreads,
                 region_name=None,
                 use_ssl=True):
        self._nthreads = nthreads
        self._use_ssl = use_ssl  # At least for now we ignore this param
        self._proc = PReadRIO(nthreads, region_name=region_name)

    def warmup(self):
        return self._proc.warmup()

    def read_blocks(self,
                    urls,
                    block_idx,
                    dst,
                    band=1):
        t0 = t_now()
        stats = [None for _ in urls]

        def extract_block(f, idx, t0=0):
            dst_slice = dst[idx, :, :]
            win = f.block_window(band, *block_idx)
            t1 = t_now()
            f.read(band, window=win, out=dst_slice)
            t2 = t_now()
            chunk_size = f.block_size(band, *block_idx)

            stats[idx] = SimpleNamespace(t_open=t1-t0,
                                         t_total=t2-t0,
                                         t0=t0,
                                         chunk_size=chunk_size)

        self._proc.process(enumerate(urls), extract_block, timer=t_now)

        t_total = t_now() - t0
        params = SimpleNamespace(nthreads=self._nthreads,
                                 band=band,
                                 block_shape=dst.shape[1:],
                                 dtype=dst.dtype.name,
                                 block=block_idx)

        return dst, SimpleNamespace(stats=stats,
                                    params=params,
                                    t0=t0,
                                    t_total=t_total)
