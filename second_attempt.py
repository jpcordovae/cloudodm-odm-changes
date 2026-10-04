#!/usr/bin/env python3
"""A second attempt for a reconstruction that came out wrong.

OpenDroneMap's default solving (incremental) ignores the camera angles a photo
records. On most flights that is a strength: recorded angles can be wrong (on
one Phantom 3 sample, 6 of 18 headings were 180 degrees out) and the default
does not care. On some it is not enough: a survey camera with a long lens,
flown level over flat ground, gives the solver too little to hold the shape,
and the model bends by tens of metres while the lens "calibrates" to something
impossible (the EuroSDR benchmark, a DJI Zenmuse P1: 54 m out of shape, focal
length up 61%). The other mode, solving from the recorded positions and angles
(triangulation), gets that flight right to centimetres - and gets the Phantom
flight wrong.

So neither is the default for everything. This module runs after the default
solving and looks at the result:

- **Is it clearly broken?** The lens calibration ran away (focal length moved
  more than 20%, or distortion beyond what a lens has), or the cameras do not
  form the shape their own positions describe (after allowing a constant
  shift, they are out by more than 5 m horizontally or 10 m vertically).
- If so, **and every photo records its angles**, the solving is run once more
  in the other mode, reusing the features and matches already computed.
- The second result is kept only if it is sound by the same test and places at
  least nine tenths as many photos. Otherwise the first one is put back.

What happened is written to `opensfm/second_attempt.json` (and the report's
folder, when there is one) so the run can say so. Set ODM_NO_SECOND_ATTEMPT=1 to
switch this off.

    second_attempt.py --assess <project>/opensfm     prints the judgement
    second_attempt.py --self-test
"""
import json
import math
import os
import shutil
import sys

FOCAL_DRIFT = 0.20          # the solved focal length against the photos' own
K1_LIMIT = 0.5              # radial distortion no lens of this kind has
SHAPE_HORIZONTAL_M = 5.0    # camera positions against their GPS, constant shift removed
SHAPE_VERTICAL_M = 10.0
MIN_PHOTOS = 10             # below this the figures say little
KEEP_SHARE = 0.9            # the second result must place this share of the first's photos


def _rotation(rvec):
    """Rotation matrix of an angle-axis vector, as nested lists (no numpy needed here)."""
    x, y, z = rvec
    t = math.sqrt(x * x + y * y + z * z)
    if t < 1e-12:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    x, y, z = x / t, y / t, z / t
    c, s, v = math.cos(t), math.sin(t), 1 - math.cos(t)
    return [[c + x * x * v, x * y * v - z * s, x * z * v + y * s],
            [y * x * v + z * s, c + y * y * v, y * z * v - x * s],
            [z * x * v - y * s, z * y * v + x * s, c + z * z * v]]


def _centre(shot):
    R, t = _rotation(shot["rotation"]), shot["translation"]
    # -R^T t
    return [-(R[0][i] * t[0] + R[1][i] * t[1] + R[2][i] * t[2]) for i in range(3)]


def _rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def assess_reconstruction(reconstructions, initial_cameras, photos_total):
    """The judgement on a reconstruction (OpenSfM's own structure, already loaded).

    Returns {"broken": bool, "reasons": [...], "photos": n, "pieces": n,
             "focalDrift": x, "shapeHorizontalM": x, "shapeVerticalM": x}.
    """
    out = {"broken": False, "reasons": [], "photos": 0, "pieces": len(reconstructions or []),
           "focalDrift": 0.0, "k1": 0.0, "shapeHorizontalM": 0.0, "shapeVerticalM": 0.0, "photosTotal": photos_total}
    if not reconstructions:
        return out
    rec = max(reconstructions, key=lambda r: len(r.get("shots", {})))
    shots = rec.get("shots", {})
    out["photos"] = len(shots)

    # The lens: what the solving made of it against what the photos say.
    for cid, cam in rec.get("cameras", {}).items():
        first = (initial_cameras or {}).get(cid, {})
        f0 = first.get("focal_x", first.get("focal"))
        f1 = cam.get("focal_x", cam.get("focal"))
        if f0 and f1:
            out["focalDrift"] = max(out["focalDrift"], abs(f1 - f0) / f0)
        out["k1"] = max(out["k1"], abs(cam.get("k1", 0.0) or 0.0))

    # The shape: camera centres against the photos' own positions, allowing a
    # constant shift (ordinary GPS is metres off as a whole, and that is not a
    # fault of the model).
    diffs = []
    for shot in shots.values():
        gps = shot.get("gps_position")
        if not gps or len(gps) != 3:
            continue
        c = _centre(shot)
        diffs.append([c[i] - gps[i] for i in range(3)])
    if len(diffs) >= MIN_PHOTOS:
        mean = [sum(d[i] for d in diffs) / len(diffs) for i in range(3)]
        out["shapeHorizontalM"] = _rms([math.hypot(d[0] - mean[0], d[1] - mean[1]) for d in diffs])
        out["shapeVerticalM"] = _rms([d[2] - mean[2] for d in diffs])

    if out["photos"] >= MIN_PHOTOS:
        if out["focalDrift"] > FOCAL_DRIFT:
            out["reasons"].append("lens: focal length moved %d%%" % round(out["focalDrift"] * 100))
        if out["k1"] > K1_LIMIT:
            out["reasons"].append("lens: distortion %.2f" % out["k1"])
        if out["shapeHorizontalM"] > SHAPE_HORIZONTAL_M or out["shapeVerticalM"] > SHAPE_VERTICAL_M:
            out["reasons"].append("shape: cameras %.1f m horizontally and %.1f m vertically from the shape of their own positions"
                                  % (out["shapeHorizontalM"], out["shapeVerticalM"]))
    out["broken"] = len(out["reasons"]) > 0
    return out


def _load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def assess(opensfm_dir):
    exif_dir = os.path.join(opensfm_dir, "exif")
    total = len([n for n in os.listdir(exif_dir) if n.endswith(".exif")]) if os.path.isdir(exif_dir) else 0
    return assess_reconstruction(_load(os.path.join(opensfm_dir, "reconstruction.json"), []),
                                 _load(os.path.join(opensfm_dir, "camera_models.json"), {}), total)


def photos_record_angles(opensfm_dir):
    exif_dir = os.path.join(opensfm_dir, "exif")
    if not os.path.isdir(exif_dir):
        return False
    names = [n for n in os.listdir(exif_dir) if n.endswith(".exif")]
    if not names:
        return False
    for n in names:
        d = _load(os.path.join(exif_dir, n), {})
        if not d.get("opk") or "gps" not in d:
            return False
    return True


def choose(first, second):
    """Which result to keep, and why."""
    if second["photos"] == 0:
        return "first", "the second attempt produced no model"
    if second["broken"]:
        return "first", "the second attempt is not sound either (%s)" % "; ".join(second["reasons"])
    if second["photos"] < KEEP_SHARE * first["photos"]:
        return "first", "the second attempt placed %d photos, the first %d" % (second["photos"], first["photos"])
    return "second", "the second attempt is sound"


def _set_algorithm(config_path, algorithm):
    with open(config_path) as f:
        lines = f.read().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith("reconstruction_algorithm:"):
            lines[i] = "reconstruction_algorithm: %s" % algorithm
            found = True
    if not found:
        lines.append("reconstruction_algorithm: %s" % algorithm)
    with open(config_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def run(octx):
    """Called by ODM right after `opensfm reconstruct` (see add-second-attempt.py)."""
    from opendm import log
    if os.environ.get("ODM_NO_SECOND_ATTEMPT", "") not in ("", "0"):
        return None
    d = octx.opensfm_project_path
    config = os.path.join(d, "config.yaml")
    with open(config) as f:
        if "reconstruction_algorithm: incremental" not in f.read():
            return None  # already solved from the recorded poses, or something else chosen on purpose
    first = assess(d)
    if not first["broken"]:
        return None
    note = {"version": 1, "first": first, "attempted": False, "kept": "first", "why": ""}
    if not photos_record_angles(d):
        note["why"] = "the photos do not all record a position and camera angles"
        log.ODM_WARNING("The reconstruction looks wrong (%s), and the photos do not all record their angles: it is kept as it is." % "; ".join(first["reasons"]))
        _write_note(d, note)
        return note

    log.ODM_WARNING("The reconstruction looks wrong (%s). Solving once more from the photos' recorded positions and angles." % "; ".join(first["reasons"]))
    rec, kept = os.path.join(d, "reconstruction.json"), os.path.join(d, "reconstruction.first.json")
    shutil.move(rec, kept)
    _set_algorithm(config, "triangulation")
    note["attempted"] = True
    try:
        octx.run("reconstruct")
        second = assess(d)
    except Exception as e:  # a failed second attempt leaves the first result in place
        second = {"broken": True, "reasons": ["it failed: %s" % str(e)[:200]], "photos": 0}
    note["second"] = second
    which, why = choose(first, second)
    note["kept"], note["why"] = which, why
    if which == "second":
        log.ODM_INFO("Second attempt kept: %d photos placed, shape %.2f m horizontally and %.2f m vertically from the photos' positions."
                     % (second["photos"], second["shapeHorizontalM"], second["shapeVerticalM"]))
        os.remove(kept)
    else:
        log.ODM_WARNING("Second attempt not kept (%s). The first result stands." % why)
        if os.path.exists(rec):
            os.remove(rec)
        shutil.move(kept, rec)
        _set_algorithm(config, "incremental")
    _write_note(d, note)
    return note


def _write_note(opensfm_dir, note):
    with open(os.path.join(opensfm_dir, "second_attempt.json"), "w") as f:
        json.dump(note, f, indent=1)


def publish_note(opensfm_dir, report_dir):
    """Copies the note beside the report, where the run's results are collected."""
    src = os.path.join(opensfm_dir, "second_attempt.json")
    if os.path.exists(src) and os.path.isdir(report_dir):
        shutil.copyfile(src, os.path.join(report_dir, "second_attempt.json"))


# ── self-test ───────────────────────────────────────────────────────────────

def _shot(centre, gps):
    # Looking straight down: half a turn about x. translation = -R c.
    rvec = [math.pi, 0.0, 0.0]
    R = _rotation(rvec)
    t = [-(R[i][0] * centre[0] + R[i][1] * centre[1] + R[i][2] * centre[2]) for i in range(3)]
    return {"rotation": rvec, "translation": t, "gps_position": gps, "camera": "c"}


def self_test():
    cam0 = {"c": {"focal": 0.85, "k1": 0.0}}
    grid = [(x * 20.0, y * 20.0, 100.0) for x in range(6) for y in range(6)]

    # Sound: every camera 1.2 m east and 0.7 m low of its GPS (ordinary GPS), lens moved 3%.
    sound = [{"cameras": {"c": {"focal": 0.875, "k1": -0.03}},
              "shots": {"p%d" % i: _shot((g[0] + 1.2, g[1], g[2] - 0.7), list(g)) for i, g in enumerate(grid)}}]
    a = assess_reconstruction(sound, cam0, len(grid))
    assert not a["broken"] and a["photos"] == 36 and a["shapeHorizontalM"] < 1e-6 and a["shapeVerticalM"] < 1e-6, a
    assert _centre(sound[0]["shots"]["p0"])[0] - 1.2 < 1e-9

    # A dome: heights off by the square of the distance from the middle (tens of metres at the edge).
    dome = [{"cameras": {"c": {"focal": 0.87, "k1": 0.0}},
             "shots": {"p%d" % i: _shot((g[0], g[1], g[2] + 0.012 * ((g[0] - 50) ** 2 + (g[1] - 50) ** 2)), list(g))
                       for i, g in enumerate(grid)}}]
    b = assess_reconstruction(dome, cam0, len(grid))
    assert b["broken"] and b["shapeVerticalM"] > SHAPE_VERTICAL_M and any(r.startswith("shape") for r in b["reasons"]), b

    # A lens that ran away, shape otherwise fine.
    lens = [{"cameras": {"c": {"focal": 0.85 * 1.61, "k1": 0.0}}, "shots": sound[0]["shots"]}]
    c = assess_reconstruction(lens, cam0, len(grid))
    assert c["broken"] and any(r.startswith("lens") for r in c["reasons"]), c

    # Too few photos to say anything; nothing at all.
    few = [{"cameras": lens[0]["cameras"], "shots": dict(list(sound[0]["shots"].items())[:5])}]
    assert not assess_reconstruction(few, cam0, 5)["broken"]
    assert not assess_reconstruction([], cam0, 0)["broken"]

    # The largest piece is the one judged.
    assert assess_reconstruction([few[0], sound[0]], cam0, 36)["photos"] == 36

    # Which one is kept.
    assert choose(b, a)[0] == "second"
    assert choose(b, c)[0] == "first"                                   # not sound either
    assert choose(b, dict(a, photos=30))[0] == "first"                  # lost too many photos
    assert choose(b, dict(a, photos=33))[0] == "second"
    assert choose(b, {"broken": True, "reasons": ["it failed"], "photos": 0})[0] == "first"

    # The configuration line is replaced, or added once.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "config.yaml")
        with open(p, "w") as f:
            f.write("processes: 8\nreconstruction_algorithm: incremental\ntriangulation_type: ROBUST\n")
        _set_algorithm(p, "triangulation")
        text = open(p).read()
        assert text.count("reconstruction_algorithm:") == 1 and "reconstruction_algorithm: triangulation\n" in text and "processes: 8" in text
        _set_algorithm(p, "incremental")
        assert "reconstruction_algorithm: incremental\n" in open(p).read()
        # Angles: all photos, or not at all.
        os.makedirs(os.path.join(tmp, "exif"))
        for i in range(3):
            json.dump({"gps": {"latitude": 1}, "opk": {"omega": 0, "phi": 0, "kappa": 0}}, open(os.path.join(tmp, "exif", "a%d.jpg.exif" % i), "w"))
        assert photos_record_angles(tmp)
        json.dump({"gps": {"latitude": 1}}, open(os.path.join(tmp, "exif", "b.jpg.exif"), "w"))
        assert not photos_record_angles(tmp)
    print("self-test ok")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--assess" in sys.argv:
        print(json.dumps(assess(sys.argv[sys.argv.index("--assess") + 1]), indent=1))
    else:
        print(__doc__)
