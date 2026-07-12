"""PBR math helpers — VERBATIM EXTRACTION of the 8 import-free, MIT-clean
functions from GI-GS `pbr/shade.py` (github.com/stopaimme/GI-GS, MIT, "Copyright
(c) 2024 stopaimme"). See LICENSE + NOTICE in this directory.

These 8 functions were EXTRACTED (retyped one by one), NOT lifted by copying
shade.py and deleting lines — so no `from .light import CubemapLight`, no
`import nvdiffrast`, and none of the license-restricted `pbr_shading` /
`get_brdf_lut` (NVIDIA `brdf_256_256.bin` LUT) came with them. They depend only
on numpy + torch.

`envBRDF_approx` is the Lazarov (2013) analytic environment-BRDF approximation
("Getting More Physical in Call of Duty: Black Ops II") — it replaces the
restricted NVIDIA `brdf_256_256.bin` split-sum LUT exactly, which is why it is
the one shading helper worth keeping. The rest are the sRGB<->linear transfer
functions and the ACES tone-map.
"""
from typing import Union

import numpy as np
import torch


# Lazarov 2013, "Getting More Physical in Call of Duty: Black Ops II"
# https://www.unrealengine.com/en-US/blog/physically-based-shading-on-mobile
def envBRDF_approx(roughness: torch.Tensor, NoV: torch.Tensor) -> torch.Tensor:
    c0 = torch.tensor([-1.0, -0.0275, -0.572, 0.022], device=roughness.device)
    c1 = torch.tensor([1.0, 0.0425, 1.04, -0.04], device=roughness.device)
    c2 = torch.tensor([-1.04, 1.04], device=roughness.device)
    r = roughness * c0 + c1
    a004 = (
        torch.minimum(torch.pow(r[..., (0,)], 2), torch.exp2(-9.28 * NoV)) * r[..., (0,)]
        + r[..., (1,)]
    )
    AB = (a004 * c2 + r[..., 2:]).clamp(min=0.0, max=1.0)
    return AB


def saturate_dot(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return (a * b).sum(dim=-1, keepdim=True).clamp(min=1e-4, max=1.0)


# Tone Mapping
def aces_film(rgb: Union[np.ndarray, torch.Tensor]) -> Union[np.ndarray, torch.Tensor]:
    EPS = 1e-6
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14
    rgb = (rgb * (a * rgb + b)) / (rgb * (c * rgb + d) + e)
    if isinstance(rgb, np.ndarray):
        return rgb.clip(min=0.0, max=1.0)
    elif isinstance(rgb, torch.Tensor):
        return rgb.clamp(min=0.0, max=1.0)


def linear_to_srgb(linear: Union[np.ndarray, torch.Tensor]) -> Union[np.ndarray, torch.Tensor]:
    if isinstance(linear, torch.Tensor):
        """Assumes `linear` is in [0, 1], see https://en.wikipedia.org/wiki/SRGB."""
        eps = torch.finfo(torch.float32).eps
        srgb0 = 323 / 25 * linear
        srgb1 = (211 * torch.clamp(linear, min=eps) ** (5 / 12) - 11) / 200
        return torch.where(linear <= 0.0031308, srgb0, srgb1)
    elif isinstance(linear, np.ndarray):
        eps = np.finfo(np.float32).eps
        srgb0 = 323 / 25 * linear
        srgb1 = (211 * np.maximum(eps, linear) ** (5 / 12) - 11) / 200
        return np.where(linear <= 0.0031308, srgb0, srgb1)
    else:
        raise NotImplementedError


def _rgb_to_srgb(f: torch.Tensor) -> torch.Tensor:
    return torch.where(
        f <= 0.0031308, f * 12.92, torch.pow(torch.clamp(f, 0.0031308), 1.0 / 2.4) * 1.055 - 0.055
    )


def rgb_to_srgb(f: torch.Tensor) -> torch.Tensor:
    assert f.shape[-1] == 3 or f.shape[-1] == 4
    out = (
        torch.cat((_rgb_to_srgb(f[..., 0:3]), f[..., 3:4]), dim=-1)
        if f.shape[-1] == 4
        else _rgb_to_srgb(f)
    )
    assert out.shape[0] == f.shape[0] and out.shape[1] == f.shape[1] and out.shape[2] == f.shape[2]
    return out


def _srgb_to_rgb(f: torch.Tensor) -> torch.Tensor:
    return torch.where(
        f <= 0.04045, f / 12.92, torch.pow((torch.clamp(f, 0.04045) + 0.055) / 1.055, 2.4)
    )


def srgb_to_rgb(f: torch.Tensor) -> torch.Tensor:
    assert f.shape[-1] == 3 or f.shape[-1] == 4
    out = (
        torch.cat((_srgb_to_rgb(f[..., 0:3]), f[..., 3:4]), dim=-1)
        if f.shape[-1] == 4
        else _srgb_to_rgb(f)
    )
    assert out.shape[0] == f.shape[0] and out.shape[1] == f.shape[1] and out.shape[2] == f.shape[2]
    return out
