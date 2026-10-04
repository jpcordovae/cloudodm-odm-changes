#!/usr/bin/env python3
"""Corrects the camera orientation ODM derives from a photo's recorded angles.

ODM turns the yaw, pitch and roll written in a photo's metadata into the
omega/phi/kappa angles OpenSfM reads. They decide where each camera starts when
a run uses known poses (`--sfm-algorithm triangulation`) and which ground point
represents an oblique photo when candidate pairs are chosen. Two faults, both
measured on the EuroSDR benchmark (DJI Zenmuse P1, 55 surveyed targets) by
projecting each target through the photo's own position and angles:

    ODM as shipped                                  1% of targets within 500 px
    the frame corrected                            57%
    and the gimbal's angles taken as one rotation 100%

1. **The frame.** The conversion needs the rotation from north/east/down to the
   map's east/north/up. ODM builds it from a difference of ECEF coordinates and
   then uses the ECEF *components* as if they were local, so the heading (kappa)
   is wrong by about the site's longitude + 90 degrees: right only near 90 W,
   88 degrees out in Britain, about 20 in Chile.

2. **A gimbal roll of 180.** Looking straight down, heading and roll turn about
   the same vertical axis, and a DJI gimbal may record the same attitude as
   (yaw, roll 0) or (yaw + 180, roll 180); the P1 alternates between them on
   alternate flight lines. ODM takes the yaw from the aircraft and the roll from
   the gimbal, so photos recorded the second way become cameras rolled over
   onto their backs: half the flight looking at the sky.

For DJI photos the gimbal's own three angles are now composed into one rotation
(camera along the body's forward axis at pitch 0; yaw about down, pitch about
right, roll about forward), which needs no special case for either form. DJI
has not kept the gimbal's yaw consistent across models, which is why ODM read
the aircraft's: so for a photo looking near straight down, where the top of the
image must point along the aircraft's heading, a gimbal that disagrees with the
aircraft by more than 45 degrees is not believed and the aircraft's heading is
used, with a roll of 180 folded back to 0.

Every edit asserts what it expected to find. A patch that silently does nothing
is worse than one that fails.
"""

import sys

PHOTO = sys.argv[1] if len(sys.argv) > 1 else "/code/opendm/photo.py"


def edit(find: str, replace: str, why: str) -> None:
    with open(PHOTO, encoding="utf-8") as fh:
        src = fh.read()
    if src.count(find) != 1:
        sys.exit(
            f"PATCH FAILED in {PHOTO}: expected exactly one occurrence of the anchor for {why}, "
            f"found {src.count(find)}. Upstream has changed; re-read it before shipping this image."
        )
    with open(PHOTO, "w", encoding="utf-8") as fh:
        fh.write(src.replace(find, replace))


# 1. Somewhere to keep the gimbal's own yaw.
edit(
    """        self.roll = None
        self.omega = None
""",
    """        self.roll = None
        self.gimbal_yaw = None
        self.omega = None
""",
    "the gimbal yaw attribute",
)

# 2. Read it, beside the three angles ODM already reads.
edit(
    """                    self.set_attr_from_xmp_tag('roll', xtags, ['@drone-dji:GimbalRollDegree', '@Camera:Roll', 'Camera:Roll'], float)
""",
    """                    self.set_attr_from_xmp_tag('roll', xtags, ['@drone-dji:GimbalRollDegree', '@Camera:Roll', 'Camera:Roll'], float)
                    self.set_attr_from_xmp_tag('gimbal_yaw', xtags, ['@drone-dji:GimbalYawDegree'], float)
""",
    "reading the gimbal yaw",
)

# 3. The angles that go into the conversion: the gimbal's whole rotation when it
#    can be believed, otherwise the aircraft's heading with the roll folded.
edit(
    """            y, p, r = math.radians(self.yaw), math.radians(self.pitch), math.radians(self.roll)
""",
    """            y, p, r = math.radians(self.yaw), math.radians(self.pitch), math.radians(self.roll)
            gimbal = camera_axes_from_dji_gimbal(self)
            if gimbal is None and abs(self.roll) > 90:
                # The same attitude written as (yaw + 180, roll 180): fold it back.
                r = math.radians((self.roll - 180.0 + 180.0) % 360.0 - 180.0)
""",
    "the angles used by compute_opk",
)

# 4. The frame: north/east/down to east/north/up, which is a constant.
edit(
    """            znp = np.array([0, 0, -1]).T
            ynp = np.cross(znp, xnp)

            cen = np.array([xnp, ynp, znp]).T

            # OPK rotation matrix
            ceb = cen.dot(cnb).dot(cbb)
""",
    """            # North/east/down to the map's east/north/up. (ODM built this from
            # xnp, a north vector in ECEF components, which is not a local frame.)
            cen = np.array([[0, 1, 0],
                            [1, 0, 0],
                            [0, 0, -1]])

            # OPK rotation matrix
            ceb = gimbal if gimbal is not None else cen.dot(cnb).dot(cbb)
""",
    "the reference frame of compute_opk",
)

# 5. The gimbal's three angles as one rotation.
edit(
    """class ODM_Photo:
""",
    '''def camera_axes_from_dji_gimbal(photo):
    """The camera's axes (right, up, backward) in east/north/up, as columns, from
    a DJI gimbal's own yaw, pitch and roll composed into one rotation. None when
    the photo is not DJI's, has no gimbal yaw, or the gimbal cannot be believed.
    """
    if photo.gimbal_yaw is None or photo.camera_make is None:
        return None
    if photo.camera_make.lower() not in ['dji', 'hasselblad']:
        return None

    # photo.pitch was normalised to 0 = straight down; the gimbal wrote -90.
    y, p, r = math.radians(photo.gimbal_yaw), math.radians(photo.pitch - 90.0), math.radians(photo.roll)
    rz = np.array([[math.cos(y), -math.sin(y), 0], [math.sin(y), math.cos(y), 0], [0, 0, 1]])
    ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
    rx = np.array([[1, 0, 0], [0, math.cos(r), -math.sin(r)], [0, math.sin(r), math.cos(r)]])
    body = rz.dot(ry).dot(rx)  # columns: forward (the view), right, down; in north/east/down
    ned_to_enu = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]])
    forward, right, down = (ned_to_enu.dot(body[:, i]) for i in range(3))

    if forward[2] < -math.cos(math.radians(30)):
        # Near straight down the top of the image points along the aircraft's
        # heading. A gimbal that says otherwise is one of the models whose yaw
        # is not what it claims to be.
        top = -down
        heading = math.degrees(math.atan2(top[0], top[1]))
        if abs((heading - photo.yaw + 180.0) % 360.0 - 180.0) > 45.0:
            return None

    return np.array([right, -down, -forward]).T


class ODM_Photo:
''',
    "the gimbal rotation helper",
)

print(f"{PHOTO}: DJI orientation angles corrected (frame, and the gimbal's rotation taken whole).")
