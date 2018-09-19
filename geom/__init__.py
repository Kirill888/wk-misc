from affine import Affine


def decompose_rws(A):
    """Compute decomposition Affine matrix sans translation into Rotation Shear and Scale.

    Note: only works for smallish values of shear, separation is almost exact
    when shear is 0. Note that there are ambiguities for negative scales.

    Example: R(90)*S(1,1) == R(-90)*S(-1,-1)

    A = R W S

    Where:

    R [ca -sa]  W [1, w]  S [sx,  0]
      [sa  ca]    [0, 1]    [ 0, sy]

    """
    from numpy import diag, asarray
    from numpy.linalg import svd, det

    if isinstance(A, Affine):
        def to_affine(m, t=(0, 0)):
            a, b, d, e = m.ravel()
            c, f = t
            return Affine(a, b, c,
                          d, e, f)

        (a, b, c,
         d, e, f,
         *_) = A
        R, W, S = decompose_rws(asarray([[a, b],
                                         [d, e]], dtype='float64'))

        return to_affine(R, (c, f)), to_affine(W), to_affine(S)

    assert A.shape == (2, 2)

    u, s, vh = svd(A)

    rr = u @ vh
    if det(rr) < 0:
        rr[:, -1] *= -1

    ss = diag(rr.T @ A)  # got the scale in `ss`

    RW = A @ diag(1.0/ss)  # remove scale from A: `R W S inv(S) = A inv(S)`

    # RW is:
    #         cos(a), w*cos(a) - sin(a)
    #         sin(a), w*sin(a) + cos(a)

    ca, sa = RW[:, 0]

    R = asarray([[ca, -sa],
                 [sa, ca]])

    w = (R.T @ RW)[0, 1]  # R.T R W = W

    W = asarray([[1, w],
                 [0, 1]])
    S = diag(ss)

    return R, W, S


def affine_from_pts(X, Y):
    """ Given points X,Y compute A, such that: Y = A*X.

        Needs at least 3 points.
    """
    from numpy import ones, vstack
    from numpy.linalg import lstsq

    assert len(X) == len(Y)
    assert len(X) >= 3

    n = len(X)

    XX = ones((n, 3), dtype='float64')
    YY = vstack(Y)
    for i, x in enumerate(X):
        XX[i, :2] = x

    mm, *_ = lstsq(XX, YY, rcond=None)
    a, d, b, e, c, f = mm.ravel()

    return Affine(a, b, c,
                  d, e, f)


def test_rsw():
    from math import sqrt

    def mkA(rot=0, scale=(1, 1), shear=0, translation=(0, 0)):
        return Affine.translation(*translation)*Affine.rotation(rot)*Affine.shear(shear)*Affine.scale(*scale)

    def get_diff(A, B):
        return sqrt(sum((a-b)**2 for a, b in zip(A, B)))

    def run_test(a, scale, tol=1e-6):
        A = mkA(a, scale=scale)

        R, W, S = decompose_rws(A)

        assert get_diff(A, R*W*S) < tol
        assert get_diff(S, mkA(0, scale)) < tol
        assert get_diff(R, mkA(a)) < tol

    for a in (0, 12, 45, 33, 67, 89, 90, 120, 170):
        run_test(a, (1, 1))
        run_test(a, (0.5, 2))
        run_test(-a, (0.5, 2))

        run_test(a, (1, 2))
        run_test(-a, (1, 2))

        run_test(a, (2, -1))
        run_test(-a, (2, -1))


def test_fit():
    from random import uniform
    from math import sqrt

    def mkA(rot=0, scale=(1, 1), shear=0, translation=(0, 0)):
        return Affine.translation(*translation)*Affine.rotation(rot)*Affine.shear(shear)*Affine.scale(*scale)

    def get_diff(A, B):
        return sqrt(sum((a-b)**2 for a, b in zip(A, B)))

    def run_test(A, n, tol=1e-5):
        X = [(uniform(0, 1), uniform(0, 1))
             for _ in range(n)]
        Y = [A*x for x in X]
        A_ = affine_from_pts(X, Y)

        assert get_diff(A, A_) < tol

    A = mkA(13, scale=(3, 4), shear=3, translation=(100, -3000))

    run_test(A, 3)
    run_test(A, 10)

    run_test(mkA(), 3)
    run_test(mkA(), 10)
