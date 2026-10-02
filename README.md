# OpenDroneMap changes used by CloudODM

[CloudODM](https://cloudodm.stellaris.cl), by Stellaris, processes drone
photographs with [OpenDroneMap](https://github.com/OpenDroneMap/ODM) (ODM),
which is licensed under the **GNU Affero General Public License v3.0**.
We run ODM through [NodeODM](https://github.com/OpenDroneMap/NodeODM)
(the official `opendronemap/nodeodm` image) with the one modification below.
This repository publishes it, as the AGPL asks of software offered over a
network.

## The modification: `--scene-classify`

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

## Licence

The script is released under the GNU Affero General Public License v3.0, the
licence of the code it modifies. See `LICENSE`.

Questions: <https://cloudodm.stellaris.cl/contact>.
