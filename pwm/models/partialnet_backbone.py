"""PartialNet backbone ported for PWM-Net (UAV forest-fire detection).

Ported from the official PartialNet source (arXiv:2502.01303,
"Partial Channel Network: Compute fewer, perform better"):
    models/partialnet.py  (classification network, timm-style)

Changes made for this reproduction (PWM-Net paper, Sec. 3.1):
    1. timm dependency removed (timm is not installed on this machine):
       - DropPath / LayerNorm2d re-implemented locally with identical semantics
       - trunc_normal_ taken from torch.nn.init (same function timm re-exports)
    2. mmdet dependency removed; `fork_feat=True` detection mode is the default.
    3. DGConv2d (auto_div=True, dynamic partial conv) is NOT ported --
       PWM-Net uses the published static PartialNet backbone.
    4. iRPE (image relative position encoding, needed by PAT_sf) lives in
       partialnet_irpe.py with an EasyDict shim instead of the easydict package.

Paper mapping (PWM-Net Sec. 3.1 / Fig. 2):
    PAT_ch -> SRM           (channel attn from mean+std statistics, stages 0-2,
                              `channel_type='se'` in source)
    PAT_sp -> partial_spatial_attn_layer_reverse (lightweight spatial attn in MLP)
    PAT_sf -> RPEAttention  (partial self-attention with iRPE, deepest stage,
                              `channel_type='self'` in source)

Usage:
    backbone = PartialNetBackbone('t0')
    feats = backbone(torch.randn(2, 3, 640, 640))   # [S8, S16, S32]
"""
from functools import partial
from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from torch.nn.init import trunc_normal_

try:  # package import (python -m models.partialnet_backbone)
    from .partialnet_irpe import build_rpe, get_rpe_config
except ImportError:  # script import (python models/partialnet_backbone.py)
    from partialnet_irpe import build_rpe, get_rpe_config


# ---------------------------------------------------------------------------
# Local replacements for timm layers (identical semantics)
# ---------------------------------------------------------------------------
class DropPath(nn.Module):
    """Per-sample stochastic depth (timm.layers.DropPath)."""

    def __init__(self, drop_prob: float = 0.):
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, x: Tensor) -> Tensor:
        if self.drop_prob == 0. or not self.training:
            return x
        keep_prob = 1 - self.drop_prob
        shape = (x.shape[0],) + (1,) * (x.ndim - 1)
        random_tensor = keep_prob + torch.rand(shape, dtype=x.dtype, device=x.device)
        random_tensor.floor_()
        return x.div(keep_prob) * random_tensor


class LayerNorm2d(nn.Module):
    """Channel-dim LayerNorm over BCHW (timm.layers.LayerNorm2d)."""

    def __init__(self, num_channels: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(num_channels))
        self.bias = nn.Parameter(torch.zeros(num_channels))
        self.eps = eps

    def forward(self, x: Tensor) -> Tensor:
        u = x.mean(1, keepdim=True)
        s = (x - u).pow(2).mean(1, keepdim=True)
        x = (x - u) / torch.sqrt(s + self.eps)
        return self.weight[:, None, None] * x + self.bias[:, None, None]


# ---------------------------------------------------------------------------
# PartialNet core (faithful port of models/partialnet.py)
# ---------------------------------------------------------------------------
class RPEAttention(nn.Module):
    """Attention with image relative position encoding (= PAT_sf core)."""

    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None,
                 attn_drop=0.0, proj_drop=0.0, rpe_config=None):
        super().__init__()
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = qk_scale or head_dim ** -0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

        # image relative position encoding
        self.rpe_q, self.rpe_k, self.rpe_v = build_rpe(
            rpe_config, head_dim=head_dim, num_heads=num_heads)

    def forward(self, x):
        B, C, h, w = x.shape
        x = x.view(B, C, h * w).transpose(1, 2)
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads,
                                  C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]

        q *= self.scale
        attn = (q @ k.transpose(-2, -1))

        if self.rpe_k is not None:
            attn += self.rpe_k(q, h, w)
        if self.rpe_q is not None:
            attn += self.rpe_q(k * self.scale).transpose(2, 3)

        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)

        out = attn @ v
        if self.rpe_v is not None:
            out += self.rpe_v(attn)

        x = out.transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        x = x.transpose(1, 2).view(B, C, h, w)
        return x


class SRM(nn.Module):
    """Style-based channel attention from mean+std statistics (= PAT_ch core)."""

    def __init__(self, channel):
        super().__init__()
        self.cfc1 = nn.Conv2d(channel, channel, kernel_size=(1, 2), bias=False)
        self.bn = nn.BatchNorm2d(channel)
        self.sigmoid = nn.Hardsigmoid()

    def forward(self, x):
        b, c, h, w = x.shape
        # style pooling
        mean = x.reshape(b, c, -1).mean(-1).view(b, c, 1, 1)
        std = x.reshape(b, c, -1).std(-1).view(b, c, 1, 1)
        u = torch.cat([mean, std], dim=-1)
        # style integration
        z = self.cfc1(u)
        z = self.bn(z)
        g = self.sigmoid(z)
        g = g.reshape(b, c, 1, 1)
        return x * g.expand_as(x)


class Partial_conv3(nn.Module):
    """PATConv: 3x3 conv on a channel subset, attention on the rest."""

    def __init__(self, dim, n_div, forward_type, use_attn='', channel_type='',
                 patnet_t0=False):
        super().__init__()
        self.dim_conv3 = dim // n_div
        self.dim = dim
        self.n_div = n_div
        self.dim_untouched = dim - self.dim_conv3
        self.partial_conv3 = nn.Conv2d(self.dim_conv3, self.dim_conv3,
                                       3, 1, 1, bias=False)
        self.use_attn = use_attn
        self.channel_type = channel_type

        if use_attn:
            if channel_type == 'self':
                rpe_config = get_rpe_config(
                    ratio=20,
                    method="euc",
                    mode='bias',
                    shared_head=False,
                    skip=0,
                    rpe_on='k',
                )
                num_heads = 4 if patnet_t0 else 6
                self.attn = RPEAttention(self.dim_untouched, num_heads=num_heads,
                                         attn_drop=0.1, proj_drop=0.1,
                                         rpe_config=rpe_config)
                self.norm = LayerNorm2d(self.dim_untouched)
                self.forward = self.forward_atten
            elif channel_type == 'se':
                self.attn = SRM(self.dim_untouched)
                self.norm = nn.BatchNorm2d(self.dim_untouched)
                self.forward = self.forward_atten
        else:
            if forward_type == 'slicing':
                self.forward = self.forward_slicing
            elif forward_type == 'split_cat':
                self.forward = self.forward_split_cat
            else:
                raise NotImplementedError

    def forward_atten(self, x: Tensor) -> Tensor:
        if self.channel_type == 'se':
            x1, x2 = torch.split(x, [self.dim_conv3, self.dim_untouched], dim=1)
            x1 = self.partial_conv3(x1)
            x2 = self.attn(x2)
            x2 = self.norm(x2)
            x = torch.cat((x1, x2), 1)
        else:  # 'self'
            x1, x2 = torch.split(x, [self.dim_conv3, self.dim_untouched], dim=1)
            x1 = self.partial_conv3(x1)
            x2 = self.norm(x2)
            x2 = self.attn(x2)
            x = torch.cat((x1, x2), 1)
        return x

    def forward_slicing(self, x: Tensor) -> Tensor:
        x1 = x.clone()   # keep the original input intact for the residual
        x1[:, :self.dim_conv3, :, :] = self.partial_conv3(x1[:, :self.dim_conv3, :, :])
        return x1

    def forward_split_cat(self, x: Tensor) -> Tensor:
        x1, x2 = torch.split(x, [self.dim_conv3, self.dim_untouched], dim=1)
        x1 = self.partial_conv3(x1)
        x = torch.cat((x1, x2), 1)
        return x


class partial_spatial_attn_layer_reverse(nn.Module):
    """Lightweight partial spatial attention (= PAT_sp core)."""

    def __init__(self, dim, n_head, partial=0.5):
        super().__init__()
        self.dim = dim
        self.dim_conv = int(partial * dim)
        self.dim_untouched = dim - self.dim_conv
        self.nhead = n_head
        self.conv = nn.Conv2d(self.dim_conv, self.dim_conv, 1, bias=False)
        self.conv_attn = nn.Conv2d(self.dim_untouched, n_head, 1, bias=False)
        self.norm = nn.BatchNorm2d(self.dim_untouched)
        self.norm2 = nn.BatchNorm2d(self.dim_conv)
        self.act = nn.Hardsigmoid()

    def forward(self, x):
        x1, x2 = torch.split(x, [self.dim_untouched, self.dim_conv], 1)
        weight = self.act(self.conv_attn(x1))
        x1 = x1 * weight
        x1 = self.norm(x1)
        x2 = self.norm2(x2)
        x2 = self.conv(x2)
        x = torch.cat((x1, x2), 1)
        return x


class MLPBlock(nn.Module):
    def __init__(self,
                 dim,
                 n_div,
                 mlp_ratio,
                 drop_path,
                 layer_scale_init_value,
                 act_layer,
                 norm_layer,
                 pconv_fw_type,
                 use_channel,
                 use_spatial,
                 channel_type,
                 patnet_t0=True):
        super().__init__()
        self.dim = dim
        self.mlp_ratio = mlp_ratio
        self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()
        self.split_shortcut = True if channel_type == "self" else False

        self.spatial_mixing = Partial_conv3(
            dim,
            n_div,
            pconv_fw_type,
            use_channel,
            channel_type,
            patnet_t0,
        )

        mlp_hidden_dim = int(dim * mlp_ratio)
        if use_spatial:
            mlp_layer: List[nn.Module] = [
                nn.Conv2d(dim, mlp_hidden_dim, 1, bias=False),
                norm_layer(mlp_hidden_dim),
                act_layer(),
                nn.Conv2d(mlp_hidden_dim, dim, 1, bias=False),
                partial_spatial_attn_layer_reverse(dim, 1)]
        else:
            mlp_layer: List[nn.Module] = [
                nn.Conv2d(dim, mlp_hidden_dim, 1, bias=False),
                norm_layer(mlp_hidden_dim),
                act_layer(),
                nn.Conv2d(mlp_hidden_dim, dim, 1, bias=False)]

        self.mlp = nn.Sequential(*mlp_layer)

        if layer_scale_init_value > 0:
            self.layer_scale = nn.Parameter(
                layer_scale_init_value * torch.ones((dim)), requires_grad=True)
            self.forward = self.forward_layer_scale

    def forward(self, x: Tensor) -> Tensor:
        if self.split_shortcut:
            x = x + self.spatial_mixing(x)
            x = x + self.drop_path(self.mlp(x))
        else:
            shortcut = x
            x = self.spatial_mixing(x)
            x = shortcut + self.drop_path(self.mlp(x))
        return x

    def forward_layer_scale(self, x: Tensor) -> Tensor:
        if self.split_shortcut:
            x = x + self.spatial_mixing(x)
            x = x + self.drop_path(self.layer_scale.unsqueeze(-1).unsqueeze(-1) * self.mlp(x))
        else:
            shortcut = x
            x = self.spatial_mixing(x)
            x = shortcut + self.drop_path(self.layer_scale.unsqueeze(-1).unsqueeze(-1) * self.mlp(x))
        return x


class BasicStage(nn.Module):
    def __init__(self,
                 dim,
                 depth,
                 n_div,
                 mlp_ratio,
                 drop_path,
                 layer_scale_init_value,
                 norm_layer,
                 act_layer,
                 pconv_fw_type,
                 use_channel,
                 use_spatial,
                 channel_type='',
                 patnet_t0=True):
        super().__init__()

        blocks_list = [
            MLPBlock(
                dim=dim,
                n_div=n_div,
                mlp_ratio=mlp_ratio,
                drop_path=drop_path[i],
                layer_scale_init_value=layer_scale_init_value,
                norm_layer=norm_layer,
                act_layer=act_layer,
                pconv_fw_type=pconv_fw_type,
                use_channel=use_channel,
                use_spatial=use_spatial,
                channel_type=channel_type,
                patnet_t0=patnet_t0,
            )
            for i in range(depth)
        ]

        self.blocks = nn.Sequential(*blocks_list)

    def forward(self, x: Tensor) -> Tensor:
        return self.blocks(x)


class PatchEmbed(nn.Module):
    def __init__(self, patch_size, patch_stride, in_chans, embed_dim, norm_layer):
        super().__init__()
        self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=patch_size,
                              stride=patch_stride, bias=False)
        if norm_layer is not None:
            self.norm = norm_layer(embed_dim)
        else:
            self.norm = nn.Identity()

    def forward(self, x: Tensor) -> Tensor:
        return self.norm(self.proj(x))


class PatchMerging(nn.Module):
    def __init__(self, patch_size2, patch_stride2, dim, norm_layer):
        super().__init__()
        self.reduction = nn.Conv2d(dim, 2 * dim, kernel_size=patch_size2,
                                   stride=patch_stride2, bias=False)
        if norm_layer is not None:
            self.norm = norm_layer(2 * dim)
        else:
            self.norm = nn.Identity()

    def forward(self, x: Tensor) -> Tensor:
        return self.norm(self.reduction(x))


class PartialNet(nn.Module):
    """PartialNet in dense-prediction mode (fork_feat=True): outputs one
    feature map per stage, each followed by a BN norm layer."""

    def __init__(self,
                 in_chans=3,
                 embed_dim=96,
                 depths=(1, 2, 8, 2),
                 mlp_ratio=2.,
                 n_div=4,
                 patch_size=4,
                 patch_stride=4,
                 patch_size2=2,   # for subsequent layers
                 patch_stride2=2,
                 patch_norm=True,
                 drop_path_rate=0.1,
                 layer_scale_init_value=0,
                 norm_layer='BN',
                 act_layer='GELU',
                 pconv_fw_type='split_cat',
                 use_channel_attn=True,
                 use_spatial_attn=True,
                 patnet_t0=True,
                 **kwargs):
        super().__init__()

        if norm_layer == 'BN':
            norm_layer = nn.BatchNorm2d
        else:
            raise NotImplementedError

        if act_layer == 'GELU':
            act_layer = nn.GELU
        elif act_layer == 'RELU':
            act_layer = partial(nn.ReLU, inplace=True)
        else:
            raise NotImplementedError

        self.num_stages = len(depths)
        self.embed_dim = embed_dim
        self.depths = depths

        # split image into non-overlapping patches
        self.patch_embed = PatchEmbed(
            patch_size=patch_size,
            patch_stride=patch_stride,
            in_chans=in_chans,
            embed_dim=embed_dim,
            norm_layer=norm_layer if patch_norm else None
        )

        # stochastic depth decay rule
        dpr = [x.item() for x in torch.linspace(0, drop_path_rate, sum(depths))]

        # build stages (alternating BasicStage / PatchMerging)
        stages_list = []
        for i_stage in range(self.num_stages):
            stage = BasicStage(dim=int(embed_dim * 2 ** i_stage),
                               n_div=n_div,
                               depth=depths[i_stage],
                               mlp_ratio=mlp_ratio,
                               drop_path=dpr[sum(depths[:i_stage]):sum(depths[:i_stage + 1])],
                               layer_scale_init_value=layer_scale_init_value,
                               norm_layer=norm_layer,
                               act_layer=act_layer,
                               pconv_fw_type=pconv_fw_type,
                               use_channel=use_channel_attn,
                               use_spatial=use_spatial_attn,
                               channel_type='se' if i_stage <= 2 else 'self',
                               patnet_t0=patnet_t0)
            stages_list.append(stage)

            if i_stage < self.num_stages - 1:
                stages_list.append(PatchMerging(
                    patch_size2=patch_size2,
                    patch_stride2=patch_stride2,
                    dim=int(embed_dim * 2 ** i_stage),
                    norm_layer=norm_layer))

        self.stages = nn.Sequential(*stages_list)

        # a norm layer for each stage output (detection mode)
        self.out_indices = [0, 2, 4, 6]
        for i_emb, i_layer in enumerate(self.out_indices):
            self.add_module(f'norm{i_layer}',
                            norm_layer(int(embed_dim * 2 ** i_emb)))

        self.apply(self._init_weights)

    def _init_weights(self, m):
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=.02)
            if m.bias is not None:
                nn.init.constant_(m.bias, 0)
        elif isinstance(m, (nn.Conv1d, nn.Conv2d)):
            trunc_normal_(m.weight, std=.02)
            if m.bias is not None:
                nn.init.constant_(m.bias, 0)
        elif isinstance(m, (nn.LayerNorm, nn.GroupNorm)):
            nn.init.constant_(m.bias, 0)
            nn.init.constant_(m.weight, 1.0)

    def forward(self, x: Tensor) -> List[Tensor]:
        """Returns one feature map per stage: strides 4/8/16/32."""
        x = self.patch_embed(x)
        outs = []
        for idx, stage in enumerate(self.stages):
            x = stage(x)
            if idx in self.out_indices:
                norm_layer = getattr(self, f'norm{idx}')
                outs.append(norm_layer(x))
        return outs


# ---------------------------------------------------------------------------
# PWM-Net wrapper: select S8/S16/S32 features for the detection neck
# ---------------------------------------------------------------------------
# Official configs (cfg/*.yaml and detection/backbones/partialnet.py).
# `spatial` = use_spatial_attn in the official yaml (PAT_sp on/off).
PARTIALNET_VARIANTS = {
    't0': dict(embed_dim=32,  depths=(1, 2, 8, 2),  drop_path_rate=0.0,  act_layer='GELU', spatial=False),
    't1': dict(embed_dim=48,  depths=(1, 2, 8, 2),  drop_path_rate=0.02, act_layer='GELU', spatial=True),
    't2': dict(embed_dim=64,  depths=(2, 2, 6, 4),  drop_path_rate=0.05, act_layer='RELU', spatial=False),
    's':  dict(embed_dim=128, depths=(1, 2, 13, 2), drop_path_rate=0.15, act_layer='RELU', spatial=False),
    'm':  dict(embed_dim=144, depths=(3, 4, 18, 3), drop_path_rate=0.2,  act_layer='RELU', spatial=False),
    'l':  dict(embed_dim=192, depths=(3, 4, 18, 3), drop_path_rate=0.3,  act_layer='RELU', spatial=False),
}

_STAGE_STRIDES = (4, 8, 16, 32)  # stage i runs at stride 4 * 2^i


class PartialNetBackbone(nn.Module):
    """PartialNet backbone for PWM-Net.

    Input : (B, 3, H, W) RGB images
    Output: list of feature maps at the requested strides (default S8/S16/S32,
            i.e. YOLO P3/P4/P5), channel counts in `self.out_channels`.

    The original classification head (AdaptiveAvgPool + 1x1 conv + Linear,
    `avgpool_pre_head` / `head` in the source) is dropped entirely; stage
    outputs are returned instead (the source's `fork_feat=True` mode).
    """

    def __init__(self,
                 variant: str = 't0',
                 use_channel_attn: bool = True,
                 use_spatial_attn: bool = None,
                 out_strides: tuple = (8, 16, 32),
                 pretrained: str = None):
        super().__init__()
        cfg = dict(PARTIALNET_VARIANTS[variant])
        spatial = cfg.pop('spatial')
        if use_spatial_attn is None:
            use_spatial_attn = spatial  # official-yaml default per variant

        self.net = PartialNet(
            embed_dim=cfg['embed_dim'],
            depths=cfg['depths'],
            drop_path_rate=cfg['drop_path_rate'],
            act_layer=cfg['act_layer'],
            use_channel_attn=use_channel_attn,
            use_spatial_attn=use_spatial_attn,
        )

        self.out_strides = tuple(out_strides)
        self.stage_ids = [i for i, s in enumerate(_STAGE_STRIDES)
                          if s in self.out_strides]
        assert len(self.stage_ids) == len(self.out_strides)
        self.out_channels = [int(cfg['embed_dim'] * 2 ** i) for i in self.stage_ids]

        if pretrained:
            self.load_pretrained(pretrained)

    def load_pretrained(self, path: str):
        """Load official classification weights (state_dict / model / raw)."""
        ckpt = torch.load(path, map_location='cpu', weights_only=True)
        state_dict = ckpt.get('state_dict') or ckpt.get('model') or ckpt
        missing, unexpected = self.net.load_state_dict(state_dict, strict=False)
        print(f'[PartialNetBackbone] loaded {path}: '
              f'{len(missing)} missing, {len(unexpected)} unexpected keys')

    def forward(self, x: Tensor) -> List[Tensor]:
        outs = self.net(x)
        return [outs[i] for i in self.stage_ids]


if __name__ == '__main__':
    torch.manual_seed(0)
    x = torch.randn(2, 3, 640, 640)

    for name, kw in [('t0 (PAT_sp off, official yaml)', dict(variant='t0')),
                     ('t0 (PAT_sp on, paper-faithful)', dict(variant='t0', use_spatial_attn=True)),
                     ('t1 (PAT_sp on, official yaml)', dict(variant='t1'))]:
        m = PartialNetBackbone(**kw)
        n_params = sum(p.numel() for p in m.parameters())
        m.eval()
        with torch.no_grad():
            feats = m(x)
        desc = ', '.join(
            f'S{s}: {tuple(t.shape)} (C={c})'
            for s, t, c in zip(m.out_strides, feats, m.out_channels))
        stat = ', '.join(f'{t.std().item():.4f}' for t in feats)
        print(f'[{name}] params={n_params / 1e6:.2f}M -> {desc} | std=({stat})')
