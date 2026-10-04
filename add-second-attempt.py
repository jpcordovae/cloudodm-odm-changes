#!/usr/bin/env python3
"""A second attempt when the default solving comes out clearly wrong.

`opendm/second_attempt.py` (copied beside ODM's own modules before this runs)
judges the reconstruction right after `opensfm reconstruct`: a lens calibration
that ran away, or cameras that do not form the shape their own positions
describe. When it is broken and every photo records its camera angles, the
solving is run once more from the recorded positions and angles
(`reconstruction_algorithm: triangulation`), reusing the features and matches,
and the better of the two is kept. See that file for the thresholds and the
evidence behind them.

This script edits two files of ODM:

1. `opendm/osfm.py`: the call, right after the first `reconstruct`. A failure
   inside it is logged and the first result stands.
2. `stages/odm_report.py`: copies the note of what happened
   (`second_attempt.json`) beside the report, where a run's results are
   collected.

Every edit asserts what it expected to find. A patch that silently does nothing
is worse than one that fails.

    add-second-attempt.py [<ODM root, default /code>]
"""
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/code"
OSFM = os.path.join(ROOT, "opendm", "osfm.py")
REPORT = os.path.join(ROOT, "stages", "odm_report.py")
MODULE = os.path.join(ROOT, "opendm", "second_attempt.py")


def edit(path, replacements):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for old, new in replacements:
        if text.count(old) != 1:
            sys.exit(
                "add-second-attempt: expected exactly one occurrence in %s of:\n%s\n"
                "ODM has changed here; read the new code before changing this script." % (path, old)
            )
        text = text.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if not os.path.exists(MODULE):
    sys.exit("add-second-attempt: %s is missing; copy second_attempt.py there before patching." % MODULE)
with open(OSFM, encoding="utf-8") as f:
    if "second_attempt" in f.read():
        sys.exit("add-second-attempt: %s is already patched." % OSFM)

edit(OSFM, [
    (
        "            self.run('reconstruct')\n"
        "            if merge_partial:\n",
        "            self.run('reconstruct')\n"
        "            # A result that is clearly wrong (the lens ran away, or the cameras do not form\n"
        "            # the shape of their own positions) gets one more attempt, from the photos'\n"
        "            # recorded positions and angles: opendm/second_attempt.py. The first result\n"
        "            # stands if anything goes wrong in there.\n"
        "            try:\n"
        "                from opendm import second_attempt\n"
        "                second_attempt.run(self)\n"
        "            except Exception as e:\n"
        "                log.ODM_WARNING(\"The second attempt could not be made: %s\" % str(e))\n"
        "            if merge_partial:\n",
    ),
])

edit(REPORT, [
    (
        "        if not os.path.exists(tree.odm_report): system.mkdir_p(tree.odm_report)\n",
        "        if not os.path.exists(tree.odm_report): system.mkdir_p(tree.odm_report)\n"
        "\n"
        "        # What the solving did on the client's behalf, when it made a second attempt.\n"
        "        try:\n"
        "            from opendm import second_attempt\n"
        "            second_attempt.publish_note(tree.opensfm, tree.odm_report)\n"
        "        except Exception as e:\n"
        "            log.ODM_WARNING(\"The note of the second attempt could not be copied: %s\" % str(e))\n",
    ),
])

print("add-second-attempt: a clearly wrong reconstruction is solved once more from the recorded poses")
