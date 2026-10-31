"""Synthetic thermal frame generator (stands in for the FLAME dataset, which is not reachable offline).

Class 0 = No Fire (warm rooftops / sun-heated ground are hard negatives),
class 1 = Fire (small/medium hotspots), class 2 = Critical (large or many hotspots).
"""
import numpy as np

N = 64
CLASSES = ["No Fire", "Fire", "Critical"]
_yy, _xx = np.mgrid[0:N, 0:N].astype(np.float32)


def _blob(cx, cy, sigma, amp):
    return amp * np.exp(-((_xx - cx) ** 2 + (_yy - cy) ** 2) / (2 * sigma ** 2))


def render(hotspots, rng, warm_distractors=True, noise=0.04):
    """hotspots: list of (x_px, y_px, sigma_px, amplitude). Returns float32 frame in [0, 1]."""
    frame = 0.15 + rng.normal(0, noise, (N, N)).astype(np.float32)
    frame += _blob(rng.uniform(0, N), rng.uniform(0, N), rng.uniform(8, 18), rng.uniform(0.0, 0.12))
    if warm_distractors:
        for _ in range(rng.integers(0, 4)):  # sun-warmed roofs: broad, never as hot as fire
            frame += _blob(rng.uniform(0, N), rng.uniform(0, N), rng.uniform(3, 9), rng.uniform(0.05, 0.32))
    for x, y, s, a in hotspots:
        frame += _blob(x, y, s, a)
    return np.clip(frame, 0, 1).astype(np.float32)


def sample(label: int, rng):
    """Return (frame, hotspots) for a class label."""
    if label == 0:
        return render([], rng), []
    if label == 1:
        spots = [(rng.uniform(8, 56), rng.uniform(8, 56), rng.uniform(1.6, 3.6), rng.uniform(0.6, 0.95))
                 for _ in range(rng.integers(1, 4))]
    else:
        spots = [(rng.uniform(16, 48), rng.uniform(16, 48), rng.uniform(5.5, 10), rng.uniform(0.7, 1.0))
                 for _ in range(rng.integers(1, 3))]
        spots += [(rng.uniform(8, 56), rng.uniform(8, 56), rng.uniform(2, 4), rng.uniform(0.6, 0.9))
                  for _ in range(rng.integers(0, 3))]
    return render(spots, rng), spots


def dataset(n_per_class: int, seed: int):
    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for label in range(3):
        for _ in range(n_per_class):
            xs.append(sample(label, rng)[0])
            ys.append(label)
    xs, ys = np.stack(xs)[:, None], np.array(ys)
    order = rng.permutation(len(ys))
    return xs[order], ys[order]
