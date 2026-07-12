"""Env-SH runtime data gate — the Godot shader's real-SH basis constants and the
9-term band ordering MUST equal precompute/core/sh_env.py (the single source of
truth). The runtime evaluates ambient_sh(N)=sum_lm c_lm Y_lm(N) with these exact
Y_lm constants; a drifted constant or a swapped band silently darkens/tints the
recovered ambient with no other symptom. This dumps the constants from sh_env and
compares them against the literals mirrored into godot/relight/relight.glsl.

This is the "dump-and-compare" half of the data gate; the Godot headless smoke
(relight/tools/relight_smoke.gd) checks that a real sidecar parses to finite coeffs.
"""
import re
from pathlib import Path

import numpy as np
import pytest

from precompute.core import sh_env
from precompute.core.sh_env import _C0, _C1, _C2a, _C2b, _C2c

REPO = Path(__file__).resolve().parents[2]
GLSL = REPO / "godot" / "relight" / "relight.glsl"

# sh_env constant -> the GLSL identifier that mirrors it.
_CONSTS = {
    "SH_C0": _C0,
    "SH_C1": _C1,
    "SH_C2a": _C2a,
    "SH_C2b": _C2b,
    "SH_C2c": _C2c,
}

# Expected band -> basis-constant name, in sh_env's 9-term order (Y00; Y1-1,Y10,Y11;
# Y2-2,Y2-1,Y20,Y21,Y22). Catches a constant assigned to the wrong band.
_EXPECTED_ORDER = ["SH_C0", "SH_C1", "SH_C1", "SH_C1",
                   "SH_C2a", "SH_C2a", "SH_C2b", "SH_C2a", "SH_C2c"]


@pytest.fixture(scope="module")
def glsl_text():
    assert GLSL.is_file(), "missing shader %s" % GLSL
    return GLSL.read_text()


def test_shader_sh_constants_match_sh_env(glsl_text):
    """Each `const float SH_Cx = <literal>;` equals the sh_env value (float32 exact)."""
    for name, want in _CONSTS.items():
        m = re.search(r"const\s+float\s+%s\s*=\s*([0-9.eE+-]+)\s*;" % re.escape(name), glsl_text)
        assert m is not None, "shader missing constant %s" % name
        got = float(m.group(1))
        # Runtime evaluates in float32; require agreement to float32 precision.
        assert np.float32(got) == np.float32(want), \
            "%s: shader=%r sh_env=%r" % (name, got, want)


def test_shader_band_order_matches_sh_env(glsl_text):
    """The `env.env_sh[k].rgb * (SH_C..` lines assign the right basis constant per band."""
    got = {}
    for m in re.finditer(r"env\.env_sh\[(\d)\]\.rgb\s*\*\s*\(?\s*(SH_C\w+)", glsl_text):
        got[int(m.group(1))] = m.group(2)
    assert len(got) == sh_env.N_SH, "expected %d SH band terms, found %s" % (sh_env.N_SH, sorted(got))
    order = [got[k] for k in range(sh_env.N_SH)]
    assert order == _EXPECTED_ORDER, "band->constant order %s != %s" % (order, _EXPECTED_ORDER)


def test_glsl_c0_matches_ply_loader_c0(glsl_text):
    """SH_C0 in the shader must equal the SH_C0 already used by relight_ply_loader.gd."""
    loader = (REPO / "godot" / "relight" / "relight_ply_loader.gd").read_text()
    m = re.search(r"SH_C0\s*:=\s*([0-9.eE+-]+)", loader)
    assert m is not None, "relight_ply_loader.gd missing SH_C0"
    assert np.float32(float(m.group(1))) == np.float32(_C0)
