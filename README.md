# OpenDroneMap changes used by CloudODM

[CloudODM](https://cloudodm.stellaris.cl), by Stellaris, processes drone
photographs with [OpenDroneMap](https://github.com/OpenDroneMap/ODM) (ODM),
which is licensed under the **GNU Affero General Public License v3.0**.
We run ODM through [NodeODM](https://github.com/OpenDroneMap/NodeODM)
(the official `opendronemap/nodeodm` image) with the three modifications below.
The second and third are also applied by ODMDisplay, our desktop application, to the
copy of OpenDroneMap its local-processing add-on installs.
This repository publishes them, as the AGPL asks of software offered over a
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

## 3. Checkpoints

OpenDroneMap fits the model to every point of a ground-control file, so a run
can say how well it honoured its control but not how accurate it is where it
had none. With this change, a point whose name (the seventh column) starts with
`CHK` or `CHECK` is a checkpoint: left out of the adjustment and measured after
it.

```
EPSG:32719
345678.12 6289012.34 512.30 4012.5 2210.0 DJI_0034.JPG GCP1
345702.55 6289120.90 514.02 1508.2 3310.7 DJI_0041.JPG CHK1
```

- `add-checkpoints.py` edits ODM: `opendm/gcp.py` keeps those lines out of the
  adjustment and the georeferencing; `stages/dataset.py` treats a file that
  holds checkpoints only as no control (the photos' own positions georeference
  the run, which is the usual check of an RTK flight); `stages/odm_report.py`
  runs the report. With `--use-exif`, where ODM does not fit to the file at
  all, every point in it is reported as a checkpoint.
- `checkpoint-report.py` locates each checkpoint from its marks with the
  reconstruction's own cameras (the rays through the marked pixels are
  intersected) and compares it with its surveyed position. It writes
  `odm_report/checkpoints.json` and a PDF in English (`checkpoints.pdf`) and
  Spanish (`checkpoints.es.pdf`): RMSE, mean, median and largest error, each
  point's error, and a plan of the errors. It also runs by itself on any
  OpenSfM reconstruction: see its first lines.

A file with no such names behaves exactly as before.

```dockerfile
COPY checkpoint-report.py /code/checkpoint-report.py
COPY add-checkpoints.py /tmp/add-checkpoints.py
RUN python3 /code/checkpoint-report.py --self-test && python3 /tmp/add-checkpoints.py && rm -f /tmp/add-checkpoints.py
```

## Licence

The scripts are released under the GNU Affero General Public License v3.0, the
licence of the code it modifies. See `LICENSE`.

Questions: <https://cloudodm.stellaris.cl/contact>.
