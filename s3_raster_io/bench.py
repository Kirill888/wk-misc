from matplotlib import pyplot as plt
import numpy as np


def find_next_available_file(fname_pattern, max_n=1000, start=1):
    """
    :param str fname_pattern: File name pattern using "%d" style formatting e.g. "result-%03d.png"
    :param int max_n: Check at most that many files before giving up and returning None
    :param int start: Where to start counting from, default is 1
    """
    from pathlib import Path

    for i in range(start, max_n):
        fname = fname_pattern % i
        if not Path(fname).exists():
            return fname

    return None


def mk_fname(params, ext='pickle', prefix=None):
    if prefix is None:
        prefix = 'results'

    fmt = '{prefix}_{p.tile[0]:d}_{p.tile[1]:d}b{p.block[0]:d}_{p.block[1]:d}B{p.band}__{p.nthreads:02d}_%03d.{ext}'.format(
        prefix=prefix,
        p=params,
        ext=ext)

    return find_next_available_file(fmt)


def add_hist(data, n, ax=None, n_sigma=None, **kwargs):
    if n_sigma is not None:
        thresh = data.mean() + np.sqrt(data.var())
        data = data[data < thresh]

    if ax is None:
        ax = plt.gca()

    return ax.hist(data, n, **kwargs)


def gen_stats_report(xx):

    chunk_size = np.r_[[r.chunk_size for r in xx.stats]]
    t_open = np.r_[[r.t_open for r in xx.stats]]*1000
    t_total = np.r_[[r.t_total for r in xx.stats]]*1000
    t_read = t_total - t_open
    hdr = '''
Tile: ({pp.tile[0]:d},{pp.tile[1]:d})@{pp.block[0]:d}_{pp.block[1]:d}#{pp.band:d}
   - blocks  : {pp.block_shape[0]:d}x{pp.block_shape[1]:d}@{pp.dtype}
   - nthreads: {pp.nthreads:d}
'''.format(pp=xx.params).strip()

    return '''
-------------------------------------------------------------
{}
-------------------------------------------------------------

Files read             : {:d}
Total data bytes       : {:,d}
  (excluding headers)
Bytes per chunk        : {:.0f} [{:d}..{:d}] bytes

Time:
 per tile:
  - total   {:7.3f} [{:.<6.1f}..{:.>7.1f}] ms
  - open    {:7.3f} [{:.<6.1f}..{:.>7.1f}] ms {:4.1f}%
  - read    {:7.3f} [{:.<6.1f}..{:.>7.1f}] ms {:4.1f}%

 total_cpu: {:.2f} sec
 walltime : {:.2f} sec
-------------------------------------------------------------
'''.format(
    hdr,
    chunk_size.shape[0],
    chunk_size.sum(),
    chunk_size.mean().round(), chunk_size.min(), chunk_size.max(),
    t_total.mean(), t_total.min(), t_total.max(),

    t_open.mean(), t_open.min(), t_open.max(), (t_open/t_total).mean()*100,
    t_read.mean(), t_read.min(), t_read.max(), (t_read/t_total).mean()*100,

    (t_total.sum()*1e-3).round(),
    xx.t_total
).strip()

def plot_results(rr, fig=None):
    chunk_size = np.r_[[r.chunk_size for r in rr]]
    t_open = np.r_[[r.t_open for r in rr]]*1000
    t_total = np.r_[[r.t_total for r in rr]]*1000
    t_read = t_total - t_open

    fig = fig or plt.figure(figsize=(12, 8))

    ax = fig.add_subplot(2, 2, 1)
    ax.plot(chunk_size, '.')
    ax.set_title('Chunk size (bytes)')
    ax.xaxis.set_visible(False)

    ax = fig.add_subplot(2, 2, 2)
    ax.hist(chunk_size, 50, linewidth=0, alpha=0.5, color='b')
    ax.yaxis.set_visible(False)
    ax.set_title('Chunk size (bytes)')

    ax = fig.add_subplot(2, 2, 3)
    plt.scatter(chunk_size, t_total, marker='.', s=3)
    ax.set_title('Chunk Size vs Load Time')

    ax = fig.add_subplot(2, 2, 4)
    add_hist(t_open, 30, n_sigma=1.5, ax=ax, alpha=0.4, color='r', linewidth=0)
    add_hist(t_read, 30, n_sigma=1.5, ax=ax, alpha=0.4, color='g', linewidth=0)
    add_hist(t_total, 30, n_sigma=1.5, ax=ax, alpha=0.2, color='b', linewidth=0)
    ax.legend(['Open', 'Read', 'Total'])
    ax.set_title('Time (ms)')
    ax.yaxis.set_visible(False)

    fig.tight_layout()

    return fig


def plot_stats_results(data, fig):
    n_threads, total_t, total_b = np.r_[[(s.params.nthreads, s.t_total, sum([x.chunk_size for x in s.stats])) for s in data]].T
    best_idx = total_t.argmin()


    ax = fig.add_subplot(2,2,1)
    ax.plot(n_threads, total_t, 'bo-', linewidth=3, alpha=0.7)
    ax.set_xlabel('# Worker Threads')
    ax.set_ylabel('Time (secs)')
    ax.xaxis.set_ticks(n_threads)

    ax.annotate('{s.t_total:.3f} secs using {s.params.nthreads:d} threads'.format(s=data[best_idx]),
            xy=(n_threads[best_idx], total_t[best_idx]),
            xytext=(0.3, 0.5),
            textcoords='axes fraction',
            arrowprops=dict(facecolor='blue',
                            alpha=0.4,
                            shrink=0.05)
           )


    kb_throughput = total_b/total_t/(1<<10)
    ax = fig.add_subplot(2,2,2)
    ax.plot(n_threads, kb_throughput, 'ro-',linewidth=3, alpha=0.7)
    ax.set_xlabel('# Worker Threads')
    ax.set_ylabel('KiB/sec')
    ax.xaxis.set_ticks(n_threads)

    ax.annotate('{kbps:.0f} KiB/s using {s.params.nthreads:d} threads'.format(
        kbps=kb_throughput[best_idx],
        s=data[best_idx]),
                xy=(n_threads[best_idx], kb_throughput[best_idx]),
                xytext=(0.3, 0.5),
                textcoords='axes fraction',
                arrowprops=dict(facecolor='red',
                                alpha=0.4,
                                shrink=0.05)
           )

    fig.tight_layout()
    return best_idx
