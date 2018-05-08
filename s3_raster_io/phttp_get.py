from timeit import default_timer as t_now
from queue import Queue
from http.client import HTTPConnection, HTTPSConnection
from .parallel import ParallelStreamProc


class ParallelHTTPGetter(object):
    def __init__(self,
                 host,
                 port=None,
                 ssl=True,
                 nconnections=32,
                 nreader_threads=4,
                 **kwargs):

        self._pstream = ParallelStreamProc(nreader_threads)
        self._connection_pool = Queue(maxsize=nconnections)

        self._qmaxsize = nconnections + nreader_threads

        Conn = HTTPSConnection if ssl else HTTPConnection
        for _ in range(nconnections):
            self._connection_pool.put(Conn(host, port=port, **kwargs))

    def connect(self):
        cc = []
        while self._connection_pool.qsize():
            c = self._connection_pool.get()
            c.connect()
            cc.append(c)

        for c in cc:
            self._connection_pool.put(c)

    def fetch(self, requests, on_data, on_error=None):
        """
        : requests: Stream of (userdata, request) tuples

        : on_data: (bytes, userdata, time=(t0,t1,t2)) => Any(ignored)
                   Called in processing threads (concurrent invocations are possible)
                   Time:
                     - t0 just before making request
                     - t1 after response have been read
                     - t2 after data was fully read

        : on_error: (Exception|Response) => Any(ignored)
                 - Can be called in the main thread if problem sending request is detected
                 - Can be called in the worker thread(s) if Response is not 2XX
        """

        def stage1(ud_reqs, connection_pool):
            for userdata, req in ud_reqs:
                conn = connection_pool.get()
                t0 = t_now()

                try:
                    conn.request(req.method, req.selector, headers=req.headers)
                except IOError as e:
                    # TODO:
                    print(e)
                    if on_error is not None:
                        on_error(e)
                    connection_pool.put(conn)
                    continue

                yield (userdata, req, conn, t0)

        def stage2(stream, connection_pool):
            for userdata, req, conn, t0 in stream:
                try:
                    response = conn.getresponse()
                except IOError as e:
                    # TODO:
                    print(e)
                    if on_error:
                        on_error(e)
                    continue

                t1 = t_now()

                if 200 <= response.code < 300:
                    data = response.read()
                    t2 = t_now()

                    connection_pool.put(conn)  # Return connection to be re-used as early as possible

                    on_data(data, userdata, time=(t0, t1, t2))
                else:
                    connection_pool.put(conn)  # Return connection to be re-used as early as possible

                    if on_error:
                        on_error(response)

        stream = stage1(requests, self._connection_pool)

        _stage2 = self._pstream.bind(stage2, qmaxsize=self._qmaxsize)
        _stage2(stream, self._connection_pool)
