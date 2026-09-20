# PWM-Net 自包含模块集（YOLO11 集成用）。
# 复现来源：
# - PATConv 三变体（PAT_ch/PAT_sp/PAT_sf）：改编自 PartialNet 官方实现
#   github.com/haiduo/PartialNet (arXiv:2502.01303, MIT)，去除 timm/irpe/mmdet 依赖；
#   PAT_sf 的部分自注意力用标准 MSA 替代原版的相对位置编码注意力。
# - WTConv：改编自官方 WTConv github.com/BGU-CS-VIL/WTConv (ECCV 2024, MIT)；
#   db1(Haar) 小波系数为固定常数，硬编码以去除 pywt 依赖。
# - M2S：按 PWM-Net 论文（Xiang et al., 2026）公式 (1)-(4) 与 Algorithm 1 复现：
#   三谱分支（固定归一化 box 滤波的低/中/高频残差）+ GAP/GMP sigmoid 门控，
#   后接三尺度（native/1/2/1/4）交互，残差输出。
# 模块均为通道保持（c_out == c_in），配合 ultralytics parse_model 通用分支。
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

_DB1_DEC_LO = [0.7071067811865476, 0.7071067811865476]
_DB1_DEC_HI = [-0.7071067811865476, 0.7071067811865476]


def _haar_filters(channels: int, device=None, dtype=torch.float):
    lo = torch.tensor(_DB1_DEC_LO, dtype=dtype)
    hi = torch.tensor(_DB1_DEC_HI, dtype=dtype)
    dec = torch.stack(
        [
            lo.unsqueeze(0) * lo.unsqueeze(1),
            lo.unsqueeze(0) * hi.unsqueeze(1),
            hi.unsqueeze(0) * lo.unsqueeze(1),
            hi.unsqueeze(0) * hi.unsqueeze(1),
        ],
        dim=0,
    )[:, None].repeat(channels, 1, 1, 1)
    rec = torch.stack(
        [
            lo.unsqueeze(0) * lo.unsqueeze(1),
            lo.unsqueeze(0) * hi.unsqueeze(1),
            hi.unsqueeze(0) * lo.unsqueeze(1),
            hi.unsqueeze(0) * hi.unsqueeze(1),
        ],
        dim=0,
    )[:, None].repeat(channels, 1, 1, 1)
    if device is not None:
        dec, rec = dec.to(device), rec.to(device)
    return dec, rec


def _wt2d(x: Tensor, filters: Tensor) -> Tensor:
    b, c, h, w = x.shape
    pad = (filters.shape[-1] // 2 - 1, filters.shape[-1] // 2 - 1)
    y = F.conv2d(x, filters, stride=2, groups=c, padding=pad)
    return y.reshape(b, c, 4, h // 2, w // 2)


def _iwt2d(x: Tensor, filters: Tensor, out_h: int, out_w: int) -> Tensor:
    b, c, _, h_half, w_half = x.shape
    pad = (filters.shape[-1] // 2 - 1, filters.shape[-1] // 2 - 1)
    y = x.reshape(b, c * 4, h_half, w_half)
    y = F.conv_transpose2d(y, filters, stride=2, groups=c, padding=pad)
    return y[:, :, :out_h, :out_w]


class WTConvYolo(nn.Module):
    """小波卷积（ECCV 2024 官方实现的通道保持 YOLO 适配版）。

    频域子带深度卷积扩感受野 + 空间域基础深度卷积，二者相加。
    """

    def __init__(self, c1, kernel_size=5, wt_levels=1):
        super().__init__()
        self.c = c1
        self.wt_levels = wt_levels
        wt, iwt = _haar_filters(c1)
        self.wt_filter = nn.Parameter(wt, requires_grad=False)
        self.iwt_filter = nn.Parameter(iwt, requires_grad=False)
        self.base_conv = nn.Conv2d(c1, c1, kernel_size, padding=kernel_size // 2, groups=c1, bias=True)
        self.base_scale = nn.Parameter(torch.ones(1, c1, 1, 1))
        self.wavelet_conv = nn.Conv2d(c1 * 4, c1 * 4, kernel_size, padding=kernel_size // 2, groups=c1 * 4, bias=False)
        self.wavelet_scale = nn.Parameter(torch.full((1, c1 * 4, 1, 1), 0.1))

    def forward(self, x: Tensor) -> Tensor:
        shapes = []
        curr_ll = x
        ll_parts, h_parts = [], []
        for _ in range(self.wt_levels):
            shapes.append(curr_ll.shape)
            if curr_ll.shape[2] % 2 or curr_ll.shape[3] % 2:
                curr_ll = F.pad(curr_ll, (0, curr_ll.shape[3] % 2, 0, curr_ll.shape[2] % 2))
            curr = _wt2d(curr_ll, self.wt_filter)
            curr_ll = curr[:, :, 0]
            tag = self.wavelet_scale * self.wavelet_conv(curr.reshape(curr.shape[0], curr.shape[1] * 4, curr.shape[3], curr.shape[4]))
            tag = tag.reshape(curr.shape)
            ll_parts.append(tag[:, :, 0])
            h_parts.append(tag[:, :, 1:4])
        next_ll = 0
        for i in range(self.wt_levels - 1, -1, -1):
            ll, hh = ll_parts.pop(), h_parts.pop()
            ll = ll + next_ll
            shape = shapes[i]
            next_ll = _iwt2d(torch.cat([ll.unsqueeze(2), hh], dim=2), self.iwt_filter, shape[2], shape[3])
        return self.base_scale * self.base_conv(x) + next_ll


class _SRM(nn.Module):
    """PAT_ch 的通道注意力：mean+std 统计 → 卷积积分 → hardsigmoid 门控（PartialNet 官方实现）。"""

    def __init__(self, channel):
        super().__init__()
        self.cfc1 = nn.Conv2d(channel, channel, kernel_size=(1, 2), bias=False)
        self.bn = nn.BatchNorm2d(channel)
        self.sigmoid = nn.Hardsigmoid()

    def forward(self, x):
        b, c = x.shape[:2]
        mean = x.reshape(b, c, -1).mean(-1).view(b, c, 1, 1)
        std = x.reshape(b, c, -1).std(-1).view(b, c, 1, 1)
        z = self.bn(self.cfc1(torch.cat([mean, std], dim=-1)))
        return x * self.sigmoid(z).reshape(b, c, 1, 1).expand_as(x)


class _PartialSpatialAttn(nn.Module):
    """PAT_sp 的轻量空间注意力（partial_spatial_attn_layer_reverse，PartialNet 官方实现）。"""

    def __init__(self, dim, partial=0.5):
        super().__init__()
        self.dim_conv = int(partial * dim)
        self.dim_rest = dim - self.dim_conv
        self.conv = nn.Conv2d(self.dim_conv, self.dim_conv, 1, bias=False)
        self.conv_attn = nn.Conv2d(self.dim_rest, 1, 1, bias=False)
        self.norm_rest = nn.BatchNorm2d(self.dim_rest)
        self.norm_conv = nn.BatchNorm2d(self.dim_conv)
        self.act = nn.Hardsigmoid()

    def forward(self, x):
        x_rest, x_conv = torch.split(x, [self.dim_rest, self.dim_conv], 1)
        weight = self.act(self.conv_attn(x_rest))
        x_rest = self.norm_rest(x_rest * weight)
        x_conv = self.conv(self.norm_conv(x_conv))
        return torch.cat((x_rest, x_conv), 1)


class _PartialSelfAttn(nn.Module):
    """PAT_sf 的部分自注意力中的注意力半边：标准 MSA（无相对位置编码简化版）。

    partial conv 的那半边由 PATBlock 外层完成，本模块只对 split 后的通道组做自注意力。
    """

    def __init__(self, dim, num_heads=4):
        super().__init__()
        self.dim = dim
        self.num_heads = num_heads
        self.norm = nn.LayerNorm(dim)
        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim, bias=True)

    def forward(self, x):
        b, c, h, w = x.shape
        t = x.flatten(2).transpose(1, 2)  # B, HW, C
        t = self.norm(t)
        qkv = self.qkv(t).reshape(b, -1, 3, self.num_heads, c // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        attn = F.scaled_dot_product_attention(q, k, v)
        t = attn.transpose(1, 2).reshape(b, -1, c)
        return self.proj(t).transpose(1, 2).reshape(b, c, h, w)


class PATBlock(nn.Module):
    """PWM-Net backbone 基础块（通道保持）：partial conv + 变体注意力 + MLP，残差连接。

    variant: 'pat_ch'=通道注意力(浅层) / 'pat_sp'=空间注意力(中层) / 'pat_sf'=部分自注意力(最深层)。
    """

    def __init__(self, c1, variant="pat_ch", n_div=4, mlp_ratio=2.0):
        super().__init__()
        self.dim_conv = c1 // n_div
        self.dim_rest = c1 - self.dim_conv
        self.partial_conv = nn.Conv2d(self.dim_conv, self.dim_conv, 3, padding=1, bias=False)
        self.variant = variant
        if variant == "pat_ch":
            self.attn = _SRM(self.dim_rest)
            self.attn_norm = nn.BatchNorm2d(self.dim_rest)
        elif variant == "pat_sp":
            self.attn = _PartialSpatialAttn(c1)
            self.attn_norm = None
        elif variant == "pat_sf":
            self.attn = _PartialSelfAttn(self.dim_rest)
            self.attn_norm = None
        else:
            raise ValueError(f"未知 PATBlock 变体: {variant}")
        hidden = int(c1 * mlp_ratio)
        self.mlp = nn.Sequential(
            nn.Conv2d(c1, hidden, 1, bias=False),
            nn.BatchNorm2d(hidden),
            nn.GELU(),
            nn.Conv2d(hidden, c1, 1, bias=False),
        )

    def forward(self, x: Tensor) -> Tensor:
        if self.variant == "pat_ch":
            x1, x2 = torch.split(x, [self.dim_conv, self.dim_rest], dim=1)
            x1 = self.partial_conv(x1)
            x2 = self.attn(self.attn_norm(x2))
            x = torch.cat((x1, x2), dim=1)
        elif self.variant == "pat_sf":
            x1, x2 = torch.split(x, [self.dim_conv, self.dim_rest], dim=1)
            x1 = self.partial_conv(x1)
            x = torch.cat((x1, self.attn(x2)), dim=1)
        else:  # pat_sp：部分通道 partial conv 后接空间注意力（切片赋值在 AMP 下破坏 autograd，用 cat）
            x = torch.cat((self.partial_conv(x[:, : self.dim_conv]), x[:, self.dim_conv :]), dim=1)
            x = self.attn(x)
        return x + self.mlp(x)


class M2S(nn.Module):
    """多谱多尺度注意力（PWM-Net 论文 §3.3，公式 (1)-(4) + Algorithm 1）。

    谱分支：固定 depthwise 归一化 box 滤波 S1=B5（低频）、S2=B3-B5（中频）、S3=X-B3（高频残差），
    GAP+GMP 描述子 → σ(W2 δ(W1 z)) sigmoid 门控，reduction=16。
    尺度分支：native/1/2/1/4 三级，stride-2 3×3 conv 下采样、双线性上采样，concat 后 1×1 投影 + 残差。
    """

    def __init__(self, c1, reduction=16):
        super().__init__()
        self.c = c1
        base, extra = c1 // 3, c1 % 3  # YOLO 通道普遍非 3 整除，余量并入最后一组
        self.sizes = [base + (1 if i < extra else 0) for i in range(3)]

        def box(channels: int, k: int) -> nn.Conv2d:
            m = nn.Conv2d(channels, channels, k, padding=k // 2, groups=channels, bias=False)
            m.weight.requires_grad = False
            nn.init.constant_(m.weight, 1.0 / (k * k))
            return m

        # 谱残差所需的原语：S0=B5(g0)、S1=B3(g1)-B5(g1)、S2=g2-B3(g2)
        self.box5_g0 = box(self.sizes[0], 5)
        self.box5_g1 = box(self.sizes[1], 5)
        self.box3_g1 = box(self.sizes[1], 3)
        self.box3_g2 = box(self.sizes[2], 3)
        hidden = max(c1 // reduction, 4)
        # 每分支门控输入 = concat(GAP, GMP) → 2×分支通道
        self.gates = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv2d(2 * sz, hidden, 1), nn.ReLU(inplace=True), nn.Conv2d(hidden, sz, 1)
                )
                for sz in self.sizes
            ]
        )
        self.down2 = nn.Conv2d(c1, c1, 3, stride=2, padding=1)
        self.down4 = nn.Conv2d(c1, c1, 3, stride=2, padding=1)
        self.fuse = nn.Conv2d(c1 * 3, c1, 1)
        self.out_proj = nn.Conv2d(c1, c1, 1)

    @staticmethod
    def _pool_desc(s: Tensor) -> Tensor:
        return torch.cat([F.adaptive_avg_pool2d(s, 1), F.adaptive_max_pool2d(s, 1)], dim=1)

    def forward(self, x: Tensor) -> Tensor:
        g0, g1, g2 = torch.split(x, self.sizes, dim=1)
        spectra = (self.box5_g0(g0), self.box3_g1(g1) - self.box5_g1(g1), g2 - self.box3_g2(g2))
        branches = []
        for i, s in enumerate(spectra):
            gate = torch.sigmoid(self.gates[i](self._pool_desc(s)))
            branches.append(gate * s)
        xs = torch.cat(branches, dim=1)

        l1 = xs
        l2 = self.down2(xs)
        l3 = self.down4(l2)
        up2 = F.interpolate(l2, size=l1.shape[2:], mode="bilinear", align_corners=False)
        up4 = F.interpolate(l3, size=l1.shape[2:], mode="bilinear", align_corners=False)
        return x + self.out_proj(self.fuse(torch.cat([l1, up2, up4], dim=1)))
