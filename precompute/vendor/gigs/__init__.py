"""Vendored GI-GS MIT Python helpers (see LICENSE + NOTICE in this directory).

ONLY the import-free, MIT-clean PBR math helpers are vendored (pbr_math.py).
Everything else the M2b decompose port needs (the SH environment light, the
deferred SH split-sum shading, the material parameterization, depth->normal,
the losses) is reimplemented from scratch in precompute/ and is NOT part of this
tree. The license-restricted GI-GS submodules (Inria diff-gaussian-rasterization
fork, nvdiffrast, nvdiffrec renderutils, simple-knn) are NEVER vendored.
"""
