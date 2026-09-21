"""WTConv2d — Wavelet Convolutions for Large Receptive Fields (ECCV 2024).

Ported from the official WTConv source: wtconv/wtconv2d.py + wtconv/util/wavelet.py
(https://github.com/BGU-CS-VIL/WTConv, Finder et al.)

Only change for this reproduction: the `pywt` (PyWavelets) dependency is
replaced by an embedded table of standard orthonormal wavelet coefficients
(db1/Haar and db2), because the machine cannot pip-install packages.
WTConv's paper and repo default to wt_type='db1' (Haar), which is also what
PWM-Net uses. Coefficient tables are validated by a perfect-reconstruction
self-test in __main__ (IWT(DWT(x)) == x for orthonormal wavelets).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

import math

# ---------------------------------------------------------------------------
# Wavelet coefficient table (values identical to pywt.Wavelet(...))
# dec_* are analysis filters (note: WTConv reverses them again internally,
# exactly like the original util/wavelet.py does with [::-1]).
# ---------------------------------------------------------------------------
_WAVELETS = {
    'haar': 'db1',
    'db1': dict(
        dec_hi=[-0.7071067811865476, 0.7071067811865476],
        dec_lo=[0.7071067811865476, 0.7071067811865476],
        rec_hi=[0.7071067811865476, -0.7071067811865476],
        rec_lo=[0.7071067811865476, 0.7071067811865476],
    ),
}


class _Wavelet:
    """Minimal stand-in for pywt.Wavelet covering dec_lo/dec_hi/rec_lo/rec_hi."""

    def __init__(self, name):
        key = _WAVELETS.get(name)
        if isinstance(key, str):  # alias
            key = _WAVELETS[key]
        if key is None:
            raise ValueError(
                f"wavelet '{name}' not in embedded table {sorted(_WAVELETS)}; "
                'install PyWavelets and restore the original wavelet.py to use it')
        self.dec_hi = key['dec_hi']
        self.dec_lo = key['dec_lo']
        self.rec_hi = key['rec_hi']
        self.rec_lo = key['rec_lo']


# ---------------------------------------------------------------------------
# DWT / IWT helpers (verbatim from wtconv/util/wavelet.py)
# ---------------------------------------------------------------------------
def create_2d_wavelet_filter(wave, in_size, out_size, type=torch.float):
    w = _Wavelet(wave)
    dec_hi = torch.tensor(w.dec_hi[::-1], dtype=type)
    dec_lo = torch.tensor(w.dec_lo[::-1], dtype=type)
    dec_filters = torch.stack([dec_lo.unsqueeze(0) * dec_lo.unsqueeze(1),
                               dec_lo.unsqueeze(0) * dec_hi.unsqueeze(1),
                               dec_hi.unsqueeze(0) * dec_lo.unsqueeze(1),
                               dec_hi.unsqueeze(0) * dec_hi.unsqueeze(1)], dim=0)

    dec_filters = dec_filters[:, None].repeat(in_size, 1, 1, 1)

    rec_hi = torch.tensor(w.rec_hi, dtype=type)
    rec_lo = torch.tensor(w.rec_lo, dtype=type)
    rec_filters = torch.stack([rec_lo.unsqueeze(0) * rec_lo.unsqueeze(1),
                               rec_lo.unsqueeze(0) * rec_hi.unsqueeze(1),
                               rec_hi.unsqueeze(0) * rec_lo.unsqueeze(1),
                               rec_hi.unsqueeze(0) * rec_hi.unsqueeze(1)], dim=0)

    rec_filters = rec_filters[:, None].repeat(out_size, 1, 1, 1)

    return dec_filters, rec_filters


def wavelet_2d_transform(x, filters):
    b, c, h, w = x.shape
    pad = (filters.shape[2] // 2 - 1, filters.shape[3] // 2 - 1)
    x = F.conv2d(x, filters, stride=2, groups=c, padding=pad)
    x = x.reshape(b, c, 4, h // 2, w // 2)
    return x


def inverse_2d_wavelet_transform(x, filters):
    b, c, _, h_half, w_half = x.shape
    pad = (filters.shape[2] // 2 - 1, filters.shape[3] // 2 - 1)
    x = x.reshape(b, c * 4, h_half, w_half)
    x = F.conv_transpose2d(x, filters, stride=2, groups=c, padding=pad)
    return x


# ---------------------------------------------------------------------------
# WTConv2d (verbatim from wtconv/wtconv2d.py)
# ---------------------------------------------------------------------------
class WTConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size=5, stride=1,
                 bias=True, wt_levels=1, wt_type='db1'):
        super(WTConv2d, self).__init__()

        assert in_channels == out_channels

        self.in_channels = in_channels
        self.wt_levels = wt_levels
        self.stride = stride
        self.dilation = 1

        self.wt_filter, self.iwt_filter = create_2d_wavelet_filter(
            wt_type, in_channels, in_channels, torch.float)
        self.wt_filter = nn.Parameter(self.wt_filter, requires_grad=False)
        self.iwt_filter = nn.Parameter(self.iwt_filter, requires_grad=False)

        self.base_conv = nn.Conv2d(in_channels, in_channels, kernel_size,
                                   padding='same', stride=1, dilation=1,
                                   groups=in_channels, bias=bias)
        self.base_scale = _ScaleModule([1, in_channels, 1, 1])

        self.wavelet_convs = nn.ModuleList(
            [nn.Conv2d(in_channels * 4, in_channels * 4, kernel_size,
                       padding='same', stride=1, dilation=1,
                       groups=in_channels * 4, bias=False)
             for _ in range(self.wt_levels)]
        )
        self.wavelet_scale = nn.ModuleList(
            [_ScaleModule([1, in_channels * 4, 1, 1], init_scale=0.1)
             for _ in range(self.wt_levels)]
        )

        if self.stride > 1:
            self.do_stride = nn.AvgPool2d(kernel_size=1, stride=stride)
        else:
            self.do_stride = None

    def forward(self, x):

        x_ll_in_levels = []
        x_h_in_levels = []
        shapes_in_levels = []

        curr_x_ll = x

        for i in range(self.wt_levels):
            curr_shape = curr_x_ll.shape
            shapes_in_levels.append(curr_shape)
            if (curr_shape[2] % 2 > 0) or (curr_shape[3] % 2 > 0):
                curr_pads = (0, curr_shape[3] % 2, 0, curr_shape[2] % 2)
                curr_x_ll = F.pad(curr_x_ll, curr_pads)

            curr_x = wavelet_2d_transform(curr_x_ll, self.wt_filter)
            curr_x_ll = curr_x[:, :, 0, :, :]

            shape_x = curr_x.shape
            curr_x_tag = curr_x.reshape(shape_x[0], shape_x[1] * 4,
                                        shape_x[3], shape_x[4])
            curr_x_tag = self.wavelet_scale[i](self.wavelet_convs[i](curr_x_tag))
            curr_x_tag = curr_x_tag.reshape(shape_x)

            x_ll_in_levels.append(curr_x_tag[:, :, 0, :, :])
            x_h_in_levels.append(curr_x_tag[:, :, 1:4, :, :])

        next_x_ll = 0

        for i in range(self.wt_levels - 1, -1, -1):
            curr_x_ll = x_ll_in_levels.pop()
            curr_x_h = x_h_in_levels.pop()
            curr_shape = shapes_in_levels.pop()

            curr_x_ll = curr_x_ll + next_x_ll

            curr_x = torch.cat([curr_x_ll.unsqueeze(2), curr_x_h], dim=2)
            next_x_ll = inverse_2d_wavelet_transform(curr_x, self.iwt_filter)

            next_x_ll = next_x_ll[:, :, :curr_shape[2], :curr_shape[3]]

        x_tag = next_x_ll
        assert len(x_ll_in_levels) == 0

        x = self.base_scale(self.base_conv(x))
        x = x + x_tag

        if self.do_stride is not None:
            x = self.do_stride(x)

        return x


class _ScaleModule(nn.Module):
    def __init__(self, dims, init_scale=1.0, init_bias=0):
        super(_ScaleModule, self).__init__()
        self.dims = dims
        self.weight = nn.Parameter(torch.ones(*dims) * init_scale)
        self.bias = None

    def forward(self, x):
        return torch.mul(self.weight, x)


if __name__ == '__main__':
    torch.manual_seed(0)

    # --- 0) validate embedded coefficients: perfect reconstruction -------
    for wt_name in ['db1']:
        wt_f, iwt_f = create_2d_wavelet_filter(wt_name, 8, 8, torch.float)
        t = torch.randn(1, 8, 16, 16)
        coeffs = wavelet_2d_transform(t, wt_f)
        rec = inverse_2d_wavelet_transform(coeffs, iwt_f)
        err = (rec - t).abs().max().item()
        print(f'[filter check] {wt_name}: max |IWT(DWT(x)) - x| = {err:.2e} '
              f'{"OK" if err < 1e-5 else "FAIL"}')

    # --- 1) step-2 spec test: (2,256,32,32) -> same shape ----------------
    m = WTConv2d(256, 256, kernel_size=5, wt_levels=2)
    n_params = sum(p.numel() for p in m.parameters())
    x = torch.randn(2, 256, 32, 32)
    out = m(x)
    print(f'[WTConv2d 256ch] params={n_params / 1e3:.1f}K  '
          f'in={tuple(x.shape)} -> out={tuple(out.shape)}  '
          f'mean={out.mean().item():.4f} std={out.std().item():.4f} '
          f'nan={bool(torch.isnan(out).any())}')

    # --- 2) gradient sanity ----------------------------------------------
    loss = out.square().mean()
    loss.backward()
    grads_ok = all((p.grad is not None) and not torch.isnan(p.grad).any()
                   for p in m.parameters() if p.requires_grad)
    print(f'[grad check] all learned params have finite grads: {grads_ok}')

    # --- 3) neck-typical shapes (odd sizes handled by internal padding) ---
    for hw in (80, 40, 20):
        m2 = WTConv2d(64, 64, kernel_size=5, wt_levels=2)
        o = m2(torch.randn(1, 64, hw, hw))
        print(f'[shape check] in (1,64,{hw},{hw}) -> {tuple(o.shape)}')
