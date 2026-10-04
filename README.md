# OpenDroneMap changes used by CloudODM

[CloudODM](https://cloudodm.stellaris.cl), by Stellaris, processes drone
photographs with [OpenDroneMap](https://github.com/OpenDroneMap/ODM) (ODM),
which is licensed under the **GNU Affero General Public License v3.0**.
We run ODM through [NodeODM](https://github.com/OpenDroneMap/NodeODM)
(the official `opendronemap/nodeodm` image) with the two modifications below.
The second is also applied by ODMDisplay, our desktop application, to the
copy of OpenDroneMap its local-processing add-on installs.
This repository publishes it, as the AGPL asks of software offered over a
network.

## 1. `--scene-classify`

ODM's `--pc-classify` runs two classification passes together: PDAL's Simple
Morphological Filter (ground) and then OpenPointClass (vegetation, buildings,
vehicles). `add-scene-classify.py` separates them:

- it adds the option `--scene-classify`, which turns on the second pass;
- `--scene-classify` implies `--pc-classify`, because the second pass needs
  ground labelled first;
- `--pc-classify` alone now runs only the ground pass.

The script edits `opendm/config.py` and `opendm/point_cloud.py` inside the
image (`/code`) and refuses to run if the code it expects has changed upstream.

```dockerfile
FROM opendronemap/nodeodm
COPY add-scene-classify.py /tmp/add-scene-classify.py
RUN python3 /tmp/add-scene-classify.py && rm -f /tmp/add-scene-classify.py
```

We also place OpenPointClass's published model (`vehicles-vegetation-buildings`,
v1.0.0, from [uav4geo/OpenPointClass](https://github.com/uav4geo/OpenPointClass/releases))
where ODM looks for it, unmodified, so processing machines need no download.

## 2. Camera orientation from DJI photos

ODM turns the yaw, pitch and roll recorded in a photo into the omega, phi and
kappa angles its reconstruction reads (`opendm/photo.py`, `compute_opk`). They
set where each camera starts when a run uses known poses
(`--sfm-algorithm triangulation`) and which ground point stands for an oblique
photo when candidate pairs are chosen. `fix-dji-angles.py` corrects two faults:

- **The reference frame.** The "north" axis is built from a difference of ECEF
  coordinates and its ECEF components are then used as if they were local
  east/north/up. The heading (kappa) comes out wrong by about the site's
  longitude plus 90 degrees: right only near 90 degrees west.
- **A gimbal roll of 180 degrees.** Looking straight down, a DJI gimbal may
  record the same attitude as (yaw, roll 0) or (yaw + 180, roll 180); the
  Zenmuse P1 alternates between them on alternate flight lines. ODM takes the
  yaw from the aircraft and the roll from the gimbal, so photos recorded the
  second way become cameras pointing at the sky.

For DJI photos the gimbal's own three angles are composed into one rotation,
which needs no special case. Where a gimbal's heading disagrees with the
aircraft's by more than 45 degrees on a photo looking near straight down, the
aircraft's heading is used instead, with a roll of 180 folded back to 0.

Measured on the EuroSDR / Newcastle University RPAS benchmark (DJI Zenmuse P1,
surveyed targets), by projecting each target through the photo's own position
and angles: 1% of targets fall within 500 pixels of where they are seen with
ODM as shipped, 100% with this change.

```dockerfile
COPY fix-dji-angles.py /tmp/fix-dji-angles.py
RUN python3 /tmp/fix-dji-angles.py && rm -f /tmp/fix-dji-angles.py
```

Like the first script, it refuses to run if the code it expects has changed
upstream. It takes the path of `photo.py` as an optional argument.

## Licence

The scripts are released under the GNU Affero General Public License v3.0, the
licence of the code it modifies. See `LICENSE`.

Questions: <https://cloudodm.stellaris.cl/contact>.
