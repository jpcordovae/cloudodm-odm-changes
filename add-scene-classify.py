#!/usr/bin/env python3
"""Separates ODM's two classification passes so a client can choose the second.

ODM runs both behind one flag. `--pc-classify` does PDAL's Simple Morphological
Filter, which labels ground, and then OpenPointClass, which labels vegetation,
buildings and vehicles. There is no way to ask for one without the other, so
this platform could not offer the learned pass as something a client decides
about — and it is a decision worth offering, because it costs real minutes on a
large cloud and produces classes that are useful to some surveys and noise to
others.

This adds `--scene-classify`, which gates only the second pass. Asking for it
implies `--pc-classify`, the same way `--dtm` already does, because the learned
classifier is run with `-u -s 2,64`: it only touches points that are still
unclassified and leaves ground alone, so it needs SMRF to have gone first.

Every edit asserts what it expected to find. A patch that silently does nothing
is worse than one that fails: it produces an image that looks correct, accepts
the option, and ignores it.
"""

import sys

CONFIG = "/code/opendm/config.py"
POINT_CLOUD = "/code/opendm/point_cloud.py"


def edit(path: str, find: str, replace: str, why: str) -> None:
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    if src.count(find) != 1:
        sys.exit(
            f"PATCH FAILED in {path}: expected exactly one occurrence of the anchor for {why}, "
            f"found {src.count(find)}. Upstream has changed; re-read it before shipping this image."
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(src.replace(find, replace))


# 1. The option itself, declared beside the one it refines.
edit(
    CONFIG,
    """    parser.add_argument('--pc-classify',""",
    """    parser.add_argument('--scene-classify',
            action=StoreTrue,
            nargs=0,
            default=False,
            help='Classify the scene with OpenPointClass after ground separation, '
            'labelling vegetation, buildings and vehicles. Implies --pc-classify. '
            'Default: '
            '%(default)s')

    parser.add_argument('--pc-classify',""",
    "the --scene-classify option",
)

# 2. Asking for the scene implies asking for the ground, because the learned
#    pass is run with `-s 2,64` and expects ground to be labelled already.
edit(
    CONFIG,
    """    if args.pc_rectify and not args.pc_classify:""",
    """    if args.scene_classify and not args.pc_classify:
      log.ODM_WARNING("--scene-classify is set, but --pc-classify is not. Enabling --pc-classify...")
      args.pc_classify = True

    if args.pc_rectify and not args.pc_classify:""",
    "the implication from scene to ground",
)

# 3. The second pass, now gated.
edit(
    POINT_CLOUD,
    """            log.ODM_INFO("Classifying {} using OpenPointClass (2/2)".format(tree.odm_georeferencing_model_laz))
            classify(tree.odm_georeferencing_model_laz, args.max_concurrency)""",
    """            if getattr(args, 'scene_classify', False):
                log.ODM_INFO("Classifying {} using OpenPointClass (2/2)".format(tree.odm_georeferencing_model_laz))
                classify(tree.odm_georeferencing_model_laz, args.max_concurrency)
            else:
                log.ODM_INFO("Skipping OpenPointClass (2/2): --scene-classify was not requested")""",
    "gating the OpenPointClass pass",
)

# Proof the result still parses and that the option is real, rather than a
# string that happens to be in a file.
sys.path.insert(0, "/code")
import argparse  # noqa: E402

with open(CONFIG, encoding="utf-8") as fh:
    if "--scene-classify" not in fh.read():
        sys.exit("PATCH FAILED: --scene-classify is not in config.py after patching.")

import py_compile  # noqa: E402

for path in (CONFIG, POINT_CLOUD):
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as err:
        sys.exit(f"PATCH FAILED: {path} no longer compiles: {err}")

print("patched: --scene-classify gates OpenPointClass and implies --pc-classify")
del argparse
