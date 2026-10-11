"""Original → output time map (PRD §11.3 steps 2–3).

The original timeline minus cuts is split into pieces at every speed/zoom boundary, snapped to the
frame grid. Each piece has a constant speed factor and at most one zoom, so the renderer can encode
it as one segment and the map stays exact (frame-accurate).
"""

from __future__ import annotations

from dataclasses import dataclass

from .plan import merge_ranges


@dataclass
class Piece:
    src_start: float
    src_end: float
    factor: float
    out_start: float
    out_frames: int
    fps: float
    zoom: object | None = None  # ZoomOp

    @property
    def src_dur(self) -> float:
        return self.src_end - self.src_start

    @property
    def out_dur(self) -> float:
        return self.out_frames / self.fps

    @property
    def out_end(self) -> float:
        return self.out_start + self.out_dur


class TimeMap:
    def __init__(self, pieces: list[Piece]):
        self.pieces = pieces

    @property
    def total(self) -> float:
        return self.pieces[-1].out_end if self.pieces else 0.0

    def map_time(self, t: float) -> float | None:
        """Output time for an original time, or None if that moment was cut."""
        for p in self.pieces:
            if p.src_start - 1e-6 <= t <= p.src_end + 1e-6:
                return p.out_start + (t - p.src_start) / p.src_dur * p.out_dur
        return None

    def map_range(self, a: float, b: float) -> list[tuple[float, float]]:
        """Output intervals covering the kept parts of [a, b] (several if a cut lies inside)."""
        out: list[tuple[float, float]] = []
        for p in self.pieces:
            lo, hi = max(a, p.src_start), min(b, p.src_end)
            if hi - lo > 1e-6:
                oa = p.out_start + (lo - p.src_start) / p.src_dur * p.out_dur
                ob = p.out_start + (hi - p.src_start) / p.src_dur * p.out_dur
                if out and abs(out[-1][1] - oa) < 1e-6:
                    out[-1] = (out[-1][0], ob)
                else:
                    out.append((oa, ob))
        return out


def snap(t: float, fps: float) -> float:
    return round(t * fps) / fps


def kept_ranges(duration: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    keep, pos = [], 0.0
    for a, b in merge_ranges(cuts):
        if a > pos:
            keep.append((pos, a))
        pos = max(pos, b)
    if pos < duration:
        keep.append((pos, duration))
    return keep


def build_timemap(duration: float, fps: float, cuts: list[tuple[float, float]], speeds: list, zooms: list) -> TimeMap:
    """speeds/zooms: ops with start/end (non-overlapping within each kind, see plan._dedupe)."""
    frame = 1.0 / fps
    snapped_cuts = [(snap(a, fps), snap(b, fps)) for a, b in cuts]
    total = snap(duration, fps) if snap(duration, fps) <= duration + 1e-6 else duration
    cut_points = set()
    for op in [*speeds, *zooms]:
        cut_points.update((snap(op.start, fps), snap(op.end, fps)))
    pieces: list[Piece] = []
    out_pos = 0.0
    for ka, kb in kept_ranges(total, snapped_cuts):
        bounds = sorted({ka, kb, *(c for c in cut_points if ka < c < kb)})
        for a, b in zip(bounds, bounds[1:]):
            if b - a < frame - 1e-6:
                continue
            mid = (a + b) / 2
            sp = next((s for s in speeds if s.start <= mid <= s.end), None)
            zm = next((z for z in zooms if z.start <= mid <= z.end), None)
            factor = sp.factor if sp else 1.0
            frames = max(1, round((b - a) * fps / factor))
            pieces.append(Piece(a, b, factor, out_pos, frames, fps, zm))
            out_pos += frames / fps
    return TimeMap(pieces)
