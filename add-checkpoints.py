#!/usr/bin/env python3
"""Checkpoints: surveyed points left out of the adjustment and reported after it.

OpenDroneMap uses every point of a ground-control file to fit the model, so a
run can say how well it honoured its control but not how accurate it is where
there was none. A surveyor answers that with checkpoints: some of the surveyed
points are held back, and the model is measured at them afterwards.

With this change, a point whose name (the seventh column of the ground-control
file) starts with CHK or CHECK is a checkpoint:

    EPSG:32719
    345678.12 6289012.34 512.30 4012.5 2210.0 DJI_0034.JPG GCP1
    345702.55 6289120.90 514.02 1508.2 3310.7 DJI_0041.JPG CHK1

1. `opendm/gcp.py` no longer hands those lines to the adjustment or to the
   georeferencing.
2. `stages/odm_report.py` runs `checkpoint-report.py` (beside ODM) on the finished
   reconstruction, which locates each checkpoint from its marks and writes
   `odm_report/checkpoints.json`, `checkpoints.pdf` and `checkpoints.es.pdf`.
   A failure there is logged and does not fail the run: the report describes
   the result, it is not part of it.

3. A file that holds checkpoints only (the usual check of an RTK flight flown
   without control) has nothing to fit to: `stages/dataset.py` georeferences
   the run from the photos' own positions, as if no file had been given, and
   the checkpoints are still reported.
4. With `--use-exif` ODM ignores the file's points for the fit; then every
   point in it is reported as a checkpoint.

A file with no such names behaves exactly as before.

Every edit asserts what it expected to find. A patch that silently does nothing
is worse than one that fails.

    add-checkpoints.py [<ODM root, default /code>]
"""
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/code"
GCP = os.path.join(ROOT, "opendm", "gcp.py")
REPORT = os.path.join(ROOT, "stages", "odm_report.py")
DATASET = os.path.join(ROOT, "stages", "dataset.py")
MARK = "checkpoint-report.py"


def edit(path, replacements):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for old, new in replacements:
        if text.count(old) != 1:
            sys.exit(
                "add-checkpoints: expected exactly one occurrence in %s of:\n%s\n"
                "ODM has changed here; read the new code before changing this script." % (path, old)
            )
        text = text.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


with open(GCP, encoding="utf-8") as f:
    if "self.checkpoints" in f.read():
        sys.exit("add-checkpoints: %s is already patched." % GCP)

edit(GCP, [
    (
        "        self.entries = []\n"
        "        self.raw_srs = \"\"\n",
        "        self.entries = []\n"
        "        # Lines named as checkpoints (CHK..., CHECK...): surveyed points kept out\n"
        "        # of the adjustment, measured after it by checkpoint-report.py (beside ODM),\n"
        "        # which applies the same rule to the same file.\n"
        "        self.checkpoints = []\n"
        "        self.raw_srs = \"\"\n",
    ),
    (
        "                        if len(parts) >= 6:\n"
        "                            self.entries.append(line)\n",
        "                        if len(parts) >= 7 and parts[6].upper().startswith((\"CHK\", \"CHECK\")):\n"
        "                            self.checkpoints.append(line)\n"
        "                        elif len(parts) >= 6:\n"
        "                            self.entries.append(line)\n",
    ),
    (
        "    def iter_entries(self):\n",
        "        if self.checkpoints:\n"
        "            log.ODM_INFO(\"%s marks of checkpoints in %s are left out of the adjustment and reported after it\" % (len(self.checkpoints), os.path.basename(self.gcp_path)))\n"
        "\n"
        "    def checkpoints_only(self):\n"
        "        return len(self.entries) == 0 and len(self.checkpoints) > 0\n"
        "\n"
        "    def iter_entries(self):\n",
    ),
])

edit(DATASET, [
    (
        "        if tree.odm_georeferencing_gcp and not args.use_exif:\n",
        "        # A ground-control file that holds checkpoints only has nothing to fit to:\n"
        "        # the photos' own positions georeference the run, and the points are reported.\n"
        "        if tree.odm_georeferencing_gcp and not args.use_exif and not types.GCPFile(tree.odm_georeferencing_gcp).checkpoints_only():\n",
    ),
])

edit(REPORT, [
    (
        "        if not os.path.exists(tree.odm_report): system.mkdir_p(tree.odm_report)\n",
        "        if not os.path.exists(tree.odm_report): system.mkdir_p(tree.odm_report)\n"
        "\n"
        "        # The accuracy at surveyed points the adjustment did not use (those named\n"
        "        # CHK... in the ground-control file). The report describes the result and\n"
        "        # is not part of it: a failure here must not fail the run.\n"
        "        gcp_file = tree.odm_georeferencing_gcp\n"
        "        if gcp_file and os.path.exists(gcp_file) and os.path.exists(os.path.join(tree.opensfm, 'reference_lla.json')):\n"
        "            try:\n"
        "                # Beside ODM itself (/code in the image, the add-on's folder on Windows).\n"
        "                script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'checkpoint-report.py')\n"
        "                system.run('\"%s\" \"%s\" --opensfm \"%s\" --gcp \"%s\" --out \"%s\" --lang both%s' %\n"
        "                           (sys.executable, script, tree.opensfm, gcp_file, tree.odm_report, ' --all-check' if args.use_exif else ''))\n"
        "            except Exception as e:\n"
        "                log.ODM_WARNING(\"The checkpoint report could not be made: %s\" % str(e))\n",
    ),
    (
        "import os\nimport json\n",
        "import os\nimport sys\nimport json\n",
    ),
])

if not os.path.exists(os.path.join(ROOT, MARK)):
    sys.exit("add-checkpoints: %s is missing from %s; copy it there before patching." % (MARK, ROOT))
print("add-checkpoints: checkpoints are left out of the adjustment and reported in odm_report/checkpoints.*")
