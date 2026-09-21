"""M2S — Multi-Spectral and Multi-Scale attention (PWM-Net paper, Sec. 3.3).

Rewritten from scratch according to the PWM-Net paper's formal spec
(Eq. 1-4 + Algorithm 1), replacing M2SFormer's DCT decomposition with the
paper's fixed depthwise normalized box filters. M2SFormer (ICCV 2025,
image-forgery localization) only provides the general motivation; its
implementation is a cross-level segmentation module and is not reused here.

Formulas (PWM-Net paper):
    Spectral branch (Eq. 1-3), B_k = fixed depthwise normalized box filter
    (k x k, stride 1, same padding, non-learnable):
        S1(X1) = B5(X1)               low-frequency residual band
        S2(X2) = B3(X2) - B5(X2)      intermediate band
        S3(X3) = X3 - B3(X3)          high-frequency band
        z_i = [GAP(S_i(X_i)); GMP(S_i(X_i))],   a_i = sigmoid(W2(W1 z_i))
        Xs  = Concat_i ( a_i * S_i(X_i) )       reduction ratio = 16

    Scale branch (Eq. 4): Level 1/2/3 at native / 1/2 / 1/4 resolution.
    Stride-2 3x3 convs downsample, bilinear interpolation upsamples, a 1x1
    projection follows concatenation, residual adds the module input:
        Y = X + proj( Concat [L1, U2(L2), U4(L3)] )

Channel handling: the 1x1 projection before splitting maps C to the next
multiple of 3 (W = 3*ceil(C/3)) so the three groups are equal; the final
projection maps W back to C for the residual.

Usage: place one M2S(C) before each detection head (P3/P4/P5).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def _box_filter_kernel(k: int, channels: int) -> torch.Tensor:
    """Normalized box filter bank: (channels, 1, k, k), each value 1/k^2."""
    return torch.full((channels, 1, k, k), 1.0 / (k * k))


class _BoxFilter(nn.Module):
    """Fixed depthwise normalized box filter B_k (stride 1, same padding)."""

    def __init__(self, k: int, channels: int):
        super().__init__()
        self.register_buffer('weight', _box_filter_kernel(k, channels))
        self.padding = k // 2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.conv2d(x, self.weight, stride=1, padding=self.padding,
                        groups=x.shape[1])


class M2S(nn.Module):
    """Multi-Spectral and Multi-Scale attention block.

    Input : (B, C, H, W)
    Output: (B, C, H, W)
    """

    def __init__(self, channels: int, reduction: int = 16):
        super().__init__()
        C = channels
        assert C >= 3
        W = ((C + 2) // 3) * 3        # next multiple of 3 -> equal groups
        g = W // 3                    # channels per group
        self.C, self.W, self.g = C, W, g

        # 1x1 projection then split into three equal channel groups
        self.proj_in = nn.Conv2d(C, W, kernel_size=1, bias=False)

        # fixed box filters for each group
        self.b5_1 = _BoxFilter(5, g)   # applied to X1
        self.b3_2 = _BoxFilter(3, g)   # applied to X2
        self.b5_2 = _BoxFilter(5, g)   # applied to X2
        self.b3_3 = _BoxFilter(3, g)   # applied to X3

        # shared gating MLP (Eq. 2): z_i (2g) -> 2g/r -> g, sigmoid
        hidden = max(2 * g // reduction, 4)
        self.gate = nn.Sequential(
            nn.Conv2d(2 * g, hidden, kernel_size=1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv2d(hidden, g, kernel_size=1, bias=False),
            nn.Sigmoid(),
        )
        self.gap = nn.AdaptiveAvgPool2d(1)
        self.gmp = nn.AdaptiveMaxPool2d(1)

        # multi-scale branch (Eq. 4): native / 1/2 / 1/4 resolutions
        # each level's convolutional transformation outputs g channels; the
        # stride-2 3x3 convs themselves implement the downsampling
        self.level1 = nn.Conv2d(W, g, kernel_size=3, padding=1, bias=False)        # native
        self.level2 = nn.Conv2d(W, g, kernel_size=3, stride=2, padding=1, bias=False)  # 1/2
        self.level3 = nn.Conv2d(g, g, kernel_size=3, stride=2, padding=1, bias=False)  # 1/4

        # 1x1 projection after concatenation, back to C for the residual
        self.proj_out = nn.Conv2d(W, C, kernel_size=1, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, C, H, W = x.shape

        # ---- spectral branch -------------------------------------------------
        # Algorithm 1, steps 1-6
        t = self.proj_in(x)                      # (B, W, H, W)
        x1, x2, x3 = torch.chunk(t, 3, dim=1)    # three equal groups

        s1 = self.b5_1(x1)                       # low-frequency band
        s2 = self.b3_2(x2) - self.b5_2(x2)       # intermediate band
        s3 = x3 - self.b3_3(x3)                  # high-frequency band

        feats = []
        for s in (s1, s2, s3):
            z = torch.cat([self.gap(s), self.gmp(s)], dim=1)   # (B, 2g, 1, 1)
            a = self.gate(z)                                    # (B, g, 1, 1)
            feats.append(a * s)
        xs = torch.cat(feats, dim=1)             # (B, W, H, W)

        # ---- scale branch ----------------------------------------------------
        # Algorithm 1, steps 7-8: build native / 1/2 / 1/4, upsample coarse,
        # concatenate, project, add the residual
        l1 = self.level1(xs)                     # (B, g, H, W)
        l2 = self.level2(xs)                     # (B, g, H/2, W/2)
        l3 = self.level3(l2)                     # (B, g, H/4, W/4)

        u2 = F.interpolate(l2, size=(H, W), mode='bilinear', align_corners=False)
        u4 = F.interpolate(l3, size=(H, W), mode='bilinear', align_corners=False)

        y = x + self.proj_out(torch.cat([l1, u2, u4], dim=1))
        return y


if __name__ == '__main__':
    torch.manual_seed(0)

    for C, HW in [(256, 32), (64, 80), (128, 40)]:
        m = M2S(C)
        n_params = sum(p.numel() for p in m.parameters())
        n_fixed = sum(b.numel() for b in m.buffers())
        x = torch.randn(2, C, HW, HW, requires_grad=True)
        y = m(x)
        assert y.shape == x.shape, f'{y.shape} != {x.shape}'

        # value sanity + gradient check
        loss = y.square().mean()
        loss.backward()
        grad_ok = all(p.grad is not None and torch.isfinite(p.grad).all()
                      for p in m.parameters())
        xg_ok = x.grad is not None and torch.isfinite(x.grad).all()
        print(f'[M2S C={C:3d}] params={n_params / 1e3:6.1f}K fixed={n_fixed}  '
              f'in={tuple(x.shape)} -> out={tuple(y.shape)}  '
              f'mean={y.mean().item():+.4f} std={y.std().item():.4f} '
              f'nan={bool(torch.isnan(y).any())}  grads_ok={grad_ok and xg_ok}')

    # odd spatial size (stride-2 convs + size-based interpolation handle it)
    m = M2S(64)
    y = m(torch.randn(1, 64, 41, 41))
    print(f'[odd size] in (1,64,41,41) -> {tuple(y.shape)}')
