#!/usr/bin/env python
"""Generate all offline media assets for module C (original paper-shadow short drama).

Outputs (all self-made, no external material):
  media/scenes/shot-01.svg ... shot-12.svg   960x540 scene cards
  media/characters/yuanshi.svg, yuanting.svg  character portraits
  media/ip-poster.svg                        key art
  media/voice/shot-01.wav ... shot-12.wav    SAPI Huihui zh-CN voice
  media/voice/ip_sample.wav                  timeline master (padded/trimmed to 40.4s)
  media/subtitles/shot-01.srt ... shot-12.srt
  media/subtitles/ip_sample.srt              master SRT
  media/manifest.json                        measured media manifest

Run:
  python scripts/gen_ip_assets.py            # regenerate SVG + SRT + voice + master
  python scripts/gen_ip_assets.py --no-voice # artwork/subtitles only
"""
from __future__ import annotations

import argparse
import html
import json
import math
import random
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "ip_story.json"
MEDIA = ROOT / "media"
FONT = "'Noto Serif SC','Songti SC','SimSun',serif"
MONO = "'Cascadia Mono','Consolas','Courier New',monospace"

INK = "#07211f"
TEAL = "#0f3b3a"
TEAL2 = "#15504b"
TEAL3 = "#1d6259"
CREAM = "#f3ead7"
CREAM2 = "#e8dcc3"
CINNABAR = "#b8452f"
GOLD = "#d9a441"

DEFS = f"""<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#061a19"/><stop offset=".55" stop-color="#0c302e"/><stop offset="1" stop-color="#15504b"/>
</linearGradient>
<radialGradient id="warm" cx=".5" cy=".5" r=".5">
  <stop offset="0" stop-color="#ffe7b8" stop-opacity=".95"/><stop offset=".4" stop-color="#d9a441" stop-opacity=".38"/><stop offset="1" stop-color="#d9a441" stop-opacity="0"/>
</radialGradient>
<radialGradient id="cool" cx=".5" cy=".5" r=".5">
  <stop offset="0" stop-color="#f3ead7" stop-opacity=".30"/><stop offset="1" stop-color="#f3ead7" stop-opacity="0"/>
</radialGradient>
<filter id="blur18"><feGaussianBlur stdDeviation="18"/></filter>
<filter id="blur8"><feGaussianBlur stdDeviation="8"/></filter>
<filter id="grain">
  <feTurbulence type="fractalNoise" baseFrequency="0.82" numOctaves="2" seed="11" stitchTiles="stitch"/>
  <feColorMatrix type="saturate" values="0"/>
</filter>
<pattern id="fiber" width="28" height="28" patternUnits="userSpaceOnUse">
  <path d="M0 28 L28 0" stroke="#f3ead7" stroke-opacity=".05" stroke-width="1"/>
</pattern>
</defs>"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def text(x, y, value, size=18, fill=CREAM, anchor="start", opacity=1.0, weight=400,
         spacing=0, family=FONT, transform=None):
    tr = f' transform="{transform}"' if transform else ""
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{fill}" '
            f'fill-opacity="{opacity}" text-anchor="{anchor}" font-weight="{weight}" '
            f'letter-spacing="{spacing}"{tr}>{esc(value)}</text>')


def stars(seed, count=46, max_y=300):
    rnd = random.Random(seed)
    out = []
    for _ in range(count):
        x = rnd.uniform(20, 940)
        y = rnd.uniform(24, max_y)
        r = rnd.choice([0.8, 1.0, 1.3, 1.7])
        o = rnd.uniform(0.25, 0.85)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{CREAM}" opacity="{o:.2f}"/>')
    return "".join(out)


def moon(cx=770, cy=108, r=52):
    return (f'<circle cx="{cx}" cy="{cy}" r="{r*3.2}" fill="url(#cool)"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{CREAM}" fill-opacity=".92"/>'
            f'<circle cx="{cx-r*0.24}" cy="{cy-r*0.18}" r="{r*0.11}" fill="{TEAL}" opacity=".10"/>'
            f'<circle cx="{cx+r*0.2}" cy="{cy+r*0.22}" r="{r*0.16}" fill="{TEAL}" opacity=".08"/>')


def mountain(y, color, amp, seed, opacity=1.0):
    rnd = random.Random(seed)
    pts = []
    for x in range(0, 981, 48):
        pts.append((x, y + rnd.uniform(-amp, amp * 0.55)))
    d = f"M0 540 L0 {y:.1f} " + " ".join(f"L{x:.1f} {yy:.1f}" for x, yy in pts) + " L960 540 Z"
    return f'<path d="{d}" fill="{color}" opacity="{opacity}"/>'


def fog(cx, cy, rx, ry, opacity=.10):
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{CREAM}" opacity="{opacity}" filter="url(#blur18)"/>'


def sound_arcs(cx, cy, radius, color=GOLD, count=4, opacity=.65, direction=1):
    out = []
    for i in range(count):
        rr = radius + i * 17
        x1 = cx + direction * rr * math.cos(math.radians(46))
        y1 = cy - rr * math.sin(math.radians(46))
        y2 = cy + rr * math.sin(math.radians(46))
        sweep = 1 if direction == 1 else 0
        out.append(f'<path d="M{x1:.1f} {y1:.1f} A{rr:.1f} {rr:.1f} 0 0 {sweep} {x1:.1f} {y2:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="2" stroke-opacity="{opacity - i*0.10:.2f}" stroke-linecap="round"/>')
    return "".join(out)


def lens(cx, cy, r, color=GOLD):
    return (f'<circle cx="{cx}" cy="{cy}" r="{r*1.9}" fill="url(#warm)" opacity=".55"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="3"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r-7}" fill="none" stroke="{CREAM}" stroke-width="1" stroke-opacity=".55"/>'
            f'<path d="M{cx-r*0.62} {cy-r*0.38} A{r*0.75} {r*0.75} 0 0 1 {cx+r*0.15} {cy-r*0.62}" fill="none" stroke="{CREAM}" stroke-width="2" stroke-opacity=".55" stroke-linecap="round"/>')


def yuanshi(x, y, s=1.0, fill=INK, accent=GOLD, flip=False):
    sx = -s if flip else s
    return f"""<g transform="translate({x} {y}) scale({sx} {s})">
<path d="M-35 0 C-41 -28 -30 -55 -25 -80 Q0 -99 25 -80 C30 -55 41 -28 35 0 Z" fill="{fill}"/>
<circle cx="0" cy="-104" r="16.5" fill="{fill}"/>
<path d="M-7 -118 Q-2 -135 13 -130" stroke="{fill}" stroke-width="7" fill="none" stroke-linecap="round"/>
<circle cx="8" cy="-103" r="10.5" fill="none" stroke="{accent}" stroke-width="2.4"/>
<path d="M18 -110 L43 -132" stroke="{accent}" stroke-width="1.6" stroke-opacity=".85"/>
<path d="M-25 -52 Q0 -42 25 -52" stroke="{accent}" stroke-width="2" fill="none" stroke-opacity=".55"/>
</g>"""


def yuanting(x, y, s=1.0, fill=INK, accent=CINNABAR, flip=False):
    sx = -s if flip else s
    return f"""<g transform="translate({x} {y}) scale({sx} {s})">
<path d="M-39 0 C-45 -30 -32 -58 -27 -82 Q0 -101 27 -82 C32 -58 45 -30 39 0 Z" fill="{fill}"/>
<path d="M-24 -78 Q-4 -62 24 -72" stroke="{accent}" stroke-width="5" fill="none" stroke-linecap="round"/>
<circle cx="0" cy="-105" r="16" fill="{fill}"/>
<circle cx="-11" cy="-120" r="7" fill="{fill}"/><circle cx="11" cy="-121" r="7" fill="{fill}"/>
<path d="M-17 -109 q-13 5 -11 15 q2 10 13 7 q-8 -7 0 -13" fill="none" stroke="{accent}" stroke-width="2.3"/>
<path d="M18 -104 q7 -2 9 4" stroke="{accent}" stroke-width="2" fill="none"/>
<path d="M-24 -30 q24 9 48 -2" stroke="{accent}" stroke-width="2" fill="none" stroke-opacity=".45"/>
</g>"""


def paper_bird(x, y, s=1.0, chest=True):
    glow = (f'<circle cx="{x}" cy="{y+4*s}" r="{46*s}" fill="url(#warm)"/>'
            f'<circle cx="{x}" cy="{y+4*s}" r="{8*s}" fill="{GOLD}"/>') if chest else ""
    return f"""<g transform="translate({x} {y}) scale({s})">
<path d="M0 -6 L-70 -42 L-38 2 L-12 0 L-30 34 L0 14 L30 34 L12 0 L38 2 L70 -42 Z"
      fill="{CREAM}" stroke="{TEAL}" stroke-width="1.4" stroke-linejoin="round"/>
<path d="M0 -6 L-38 2 L-30 34 Z" fill="{CREAM2}" opacity=".85"/>
<path d="M0 -6 L38 2 L30 34 Z" fill="#dccdae" opacity=".8"/>
<path d="M0 -6 L0 14" stroke="{TEAL}" stroke-width="1.1" opacity=".55"/>
<path d="M0 14 L22 20 L10 28 Z" fill="{CINNABAR}" opacity=".85"/>
{glow}
</g>"""


def house(cx, ground, s=1.0, lit=True, label=""):
    warm = (f'<circle cx="{cx}" cy="{ground-58*s}" r="{54*s}" fill="url(#warm)"/>'
            f'<rect x="{cx-20*s}" y="{ground-66*s}" width="{40*s}" height="{30*s}" fill="{GOLD}" opacity=".9"/>'
            f'<path d="M{cx-20*s} {ground-58*s} h{40*s} M{cx} {ground-66*s} v{30*s}" stroke="{TEAL}" stroke-width="{2*s}"/>') if lit else ""
    return f"""<g>
<path d="M{cx-78*s} {ground-82*s} L{cx} {ground-140*s} L{cx+78*s} {ground-82*s} Z" fill="#082422" stroke="{CREAM}" stroke-opacity=".12"/>
<rect x="{cx-62*s}" y="{ground-84*s}" width="{124*s}" height="{84*s}" fill="#0a2725" stroke="{CREAM}" stroke-opacity=".12"/>
<rect x="{cx+40*s}" y="{ground-128*s}" width="{12*s}" height="{30*s}" fill="#0a2725"/>
{warm}
<rect x="{cx-52*s}" y="{ground-30*s}" width="{26*s}" height="{30*s}" fill="{INK}" opacity=".8"/>
{text(cx+18*s, ground-36*s, label, size=11*s, fill=CREAM, opacity=.55, anchor="middle", spacing=1) if label else ""}
</g>"""


def sparkles(seed, count=22, x0=60, x1=900, y0=80, y1=460):
    rnd = random.Random(seed)
    out = []
    for _ in range(count):
        x, y, r = rnd.uniform(x0, x1), rnd.uniform(y0, y1), rnd.uniform(1, 3.2)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{GOLD}" opacity="{rnd.uniform(.25,.8):.2f}"/>')
    return "".join(out)


def frame(no, scene_label, aria, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" width="960" height="540" role="img" aria-label="{esc(aria)}">
{DEFS}
<rect width="960" height="540" fill="url(#sky)"/>
{body}
<rect width="960" height="540" fill="url(#fiber)"/>
<rect width="960" height="540" filter="url(#grain)" opacity=".045"/>
<rect x="18" y="18" width="924" height="504" fill="none" stroke="{CREAM}" stroke-opacity=".18"/>
<path d="M18 44 V18 H44 M916 18 H942 V44 M942 496 V522 H916 M44 522 H18 V496" fill="none" stroke="{CREAM}" stroke-opacity=".4" stroke-width="1.4"/>
{text(40, 46, f"SHOT {no:02d} / 12", size=12, fill=CREAM, opacity=.62, family=MONO, spacing=1.6)}
{text(920, 46, scene_label, size=12, fill=CREAM, opacity=.55, anchor="end", spacing=1.2)}
{text(920, 510, "原创纸影 · 合成样例", size=11, fill=CREAM, opacity=.4, anchor="end", family=MONO)}
</svg>"""


def scene_01(no):
    body = stars(1) + moon() + mountain(318, "#0a2a28", 46, 11) + mountain(372, "#0c322f", 34, 12)
    body += fog(300, 340, 360, 48) + fog(650, 390, 420, 42)
    body += house(700, 410, 1.05, True, "回声邮局")
    body += yuanshi(716, 268, .38)
    body += mountain(470, "#082422", 28, 13)
    body += f'<path d="M0 470 Q240 438 480 470 T960 456 L960 540 L0 540 Z" fill="#061b19"/>'
    body += sparkles(101, 16, 80, 880, 120, 330)
    return frame(no, "回声邮局 · 外景 · 夜", "山谷夜景，邮局窗口亮着一线暖光，远视站在屋顶。", body)


def scene_02(no):
    body = stars(2) + moon(150, 92, 36) + mountain(300, "#0a2a28", 40, 21) + fog(470, 360, 380, 44)
    for i in range(7):
        x = 90 + i * 88
        y = 470 - i * 24
        body += f'<path d="M{x} {y} L{x+96} {y} L{x+96} {y+34} L{x} {y+34} Z" fill="{TEAL}" opacity="{0.26+i*0.05:.2f}" stroke="{CREAM}" stroke-opacity=".08"/>'
    # hanging lantern
    body += f'<path d="M180 0 V120" stroke="{CREAM}" stroke-width="1.5" stroke-opacity=".35"/><circle cx="180" cy="145" r="34" fill="url(#warm)"/><rect x="164" y="122" width="32" height="46" rx="6" fill="{GOLD}" opacity=".9"/><path d="M164 132 H196 M164 142 H196 M164 152 H196" stroke="{TEAL}" stroke-width="1" opacity=".5"/>'
    body += yuanshi(430, 455, 1.0) + yuanting(545, 420, 1.0, flip=False)
    body += sound_arcs(566, 300, 26, GOLD, 4, .55)
    body += mountain(500, "#07201e", 22, 23)
    return frame(no, "石阶 · 雾中", "远视与远听踏上雾中的石阶，远听回头，同心声波在雾里扩散。", body)


def scene_03(no):
    body = stars(3, 26, 260) + moon(620, 180, 38)
    body += f'<rect width="960" height="540" fill="#071d1c"/>'
    body += f'<rect x="242" y="78" width="476" height="342" fill="#0a2b29" stroke="{CREAM}" stroke-opacity=".35" stroke-width="3"/>'
    body += f'<rect x="258" y="94" width="444" height="310" fill="url(#sky)"/>'
    body += moon(620, 190, 34) + mountain(300, "#0a2a28", 22, 31)
    for gx in range(310, 650, 96):
        body += f'<path d="M{gx} 94 V404" stroke="{CREAM}" stroke-opacity=".18" stroke-width="2"/>'
    for gy in (194, 300):
        body += f'<path d="M258 {gy} H702" stroke="{CREAM}" stroke-opacity=".18" stroke-width="2"/>'
    body += f'<rect x="214" y="420" width="532" height="22" fill="{CREAM}" opacity=".14"/>'
    body += paper_bird(565, 388, 1.5, True)
    # stone
    body += f'<path d="M392 420 L414 350 Q456 330 486 360 L500 420 Z" fill="{TEAL3}" stroke="{CREAM}" stroke-opacity=".15"/><path d="M430 362 l16 22 l-10 16" stroke="{CINNABAR}" stroke-width="2" fill="none" opacity=".55"/>'
    body += yuanting(772, 505, .9, flip=True)
    body += f'<path d="M214 442 H746" stroke="{CREAM}" stroke-opacity=".22"/>'
    return frame(no, "邮局窗前", "窗台上失声的纸鸟与发纹石，远听俯身查看。", body)


def scene_04(no):
    body = f'<rect width="960" height="540" fill="#082321"/>'
    body += f'<circle cx="230" cy="300" r="250" fill="url(#warm)" opacity=".16"/>'
    # stone
    body += f'<path d="M80 470 L110 250 Q150 180 300 176 Q470 172 548 250 L590 470 Z" fill="{TEAL3}" stroke="{CREAM}" stroke-opacity=".12"/>'
    body += f'<path d="M160 470 L190 300 Q250 246 360 244 Q500 248 540 330 L560 470 Z" fill="#174d48" opacity=".8"/>'
    body += f'<path d="M350 250 q-22 48 8 78 q-18 40 10 72 q-12 34 6 62" stroke="{CINNABAR}" stroke-width="3" fill="none" opacity=".7"/>'
    body += sound_arcs(560, 320, 40, GOLD, 4, .7)
    body += yuanting(800, 505, 1.5, flip=True)
    # music notes
    body += f'<g fill="{GOLD}" opacity=".75"><circle cx="640" cy="236" r="7"/><path d="M647 236 V196 l28 -8 v10 l-20 5" stroke="{GOLD}" stroke-width="3" fill="none"/><circle cx="700" cy="300" r="5"/><path d="M705 300 V270 l20 -5" stroke="{GOLD}" stroke-width="2" fill="none"/></g>'
    body += sparkles(41, 24, 580, 900, 170, 420)
    return frame(no, "石中旧声", "特写：远听贴着石头，声波里浮出未唱完的摇篮曲。", body)


def scene_05(no):
    body = f'<rect width="960" height="540" fill="#0a2b29"/>'
    for i in range(5):
        body += f'<path d="M0 {150+i*48} C240 {120+i*48} 420 {200+i*48} 960 {140+i*48}" stroke="{CREAM}" stroke-width="1" stroke-opacity=".10" fill="none"/>'
    body += f'<path d="M-40 430 C190 330 300 130 500 214 C670 284 710 440 1000 292" stroke="{CINNABAR}" stroke-width="24" stroke-linecap="round" fill="none" opacity=".82"/>'
    body += f'<path d="M-40 430 C190 330 300 130 500 214 C670 284 710 440 1000 292" stroke="{CREAM}" stroke-width="1.4" stroke-linecap="round" fill="none" opacity=".35"/>'
    body += lens(500, 214, 62)
    body += f'<path d="M548 178 L760 64" stroke="{GOLD}" stroke-width="3" opacity=".55"/><path d="M548 178 L760 64" stroke="{GOLD}" stroke-width="12" opacity=".10" filter="url(#blur8)"/>'
    body += yuanshi(210, 510, .8, fill="#051817") + yuanting(770, 505, .8, fill="#051817")
    body += sparkles(51, 34, 100, 900, 80, 440)
    return frame(no, "旧旋律 · 纸带", "朱砂色纸带缠住单圆镜片，光沿纸带找到回家的路。", body)


def scene_06(no):
    body = stars(6, 30, 260) + moon(790, 100, 46)
    body += f'<rect x="0" y="0" width="960" height="540" fill="#082321" opacity=".45"/>'
    body += mountain(380, "#0a2a28", 32, 61) + fog(480, 400, 420, 50)
    body += f'<path d="M790 100 L532 300 L650 420" stroke="{GOLD}" stroke-width="2.4" fill="none" opacity=".65"/>'
    body += f'<path d="M790 100 L532 300 L650 420" stroke="{GOLD}" stroke-width="14" fill="none" opacity=".12" filter="url(#blur8)"/>'
    body += lens(532, 300, 58)
    body += yuanshi(420, 480, 1.15) + yuanting(300, 485, 1.0, flip=False)
    # lamp
    body += f'<circle cx="650" cy="390" r="86" fill="url(#warm)"/><path d="M624 424 h52 l-8 56 h-36 Z" fill="{TEAL}"/><rect x="634" y="358" width="32" height="66" rx="4" fill="{GOLD}" opacity=".9"/><path d="M650 384 q-16 -16 0 -34 q16 18 0 34" fill="{CREAM}"/>'
    body += sparkles(61, 30, 540, 860, 220, 440)
    return frame(no, "折光", "远视举镜折下月光，光落入灯芯，远听在旁打拍子。", body)


def scene_07(no):
    body = f'<rect width="960" height="540" fill="#0b2927"/>'
    for gx in range(120, 900, 120):
        body += f'<path d="M{gx} 0 V540" stroke="{CREAM}" stroke-opacity=".07" stroke-width="18"/>'
    for gy in range(80, 520, 110):
        body += f'<path d="M0 {gy} H960" stroke="{CREAM}" stroke-opacity=".06" stroke-width="12"/>'
    body += f'<circle cx="480" cy="300" r="230" fill="url(#warm)" opacity=".8"/>'
    body += f'<path d="M410 470 h140 l-18 -54 h-104 Z" fill="{TEAL}" stroke="{CREAM}" stroke-opacity=".16"/>'
    body += f'<path d="M430 416 q50 -18 100 0 v-96 q-50 -18 -100 0 Z" fill="{GOLD}" opacity=".18" stroke="{GOLD}" stroke-opacity=".6"/>'
    body += f'<path d="M480 352 q-26 -34 0 -76 q26 42 0 76" fill="{CREAM}"/><circle cx="480" cy="336" r="8" fill="{CINNABAR}"/>'
    body += f'<path d="M480 276 q-26 -34 0 -76 q26 42 0 76" fill="{GOLD}" opacity=".55"/>'
    for i in range(12):
        a = math.radians(i * 30)
        x1, y1 = 480 + math.cos(a) * 92, 316 + math.sin(a) * 92
        x2, y2 = 480 + math.cos(a) * (138 + (i % 3) * 22), 316 + math.sin(a) * (138 + (i % 3) * 22)
        body += f'<path d="M{x1:.1f} {y1:.1f} L{x2:.1f} {y2:.1f}" stroke="{GOLD}" stroke-width="1.3" opacity=".35"/>'
    body += yuanshi(180, 520, .85, fill="#051817") + yuanting(790, 520, .85, fill="#051817")
    body += sparkles(71, 34, 150, 820, 120, 460)
    return frame(no, "灯芯复燃", "微距：灯芯复燃，暖光沿窗棂铺开。", body)


def scene_08(no):
    body = stars(8, 32, 280) + moon(800, 95, 40)
    body += fog(480, 430, 440, 54)
    body += f'<circle cx="480" cy="270" r="210" fill="url(#warm)" opacity=".5"/>'
    body += paper_bird(480, 270, 2.3, True)
    body += sound_arcs(620, 268, 74, GOLD, 4, .55)
    body += yuanting(235, 510, 1.0, flip=False)
    body += f'<path d="M690 200 q40 -30 80 -12 q-38 4 -60 30" fill="{CREAM}" opacity=".35"/>'
    body += sparkles(81, 30, 200, 820, 120, 450)
    return frame(no, "纸鸟振翅", "纸鸟展开折纸翅膀，胸口灯亮，声波从喙尖荡开。", body)


def scene_09(no):
    body = f'<rect width="960" height="540" fill="#071f1d"/>'
    body += stars(9, 70, 330) + moon(790, 92, 42)
    body += mountain(250, "#0a2a28", 36, 91) + mountain(310, "#0c322f", 26, 92)
    # river
    body += f'<path d="M360 540 C390 430 520 420 560 350 C610 260 760 260 800 180" stroke="{CREAM}" stroke-width="26" fill="none" opacity=".08" stroke-linecap="round"/>'
    rnd = random.Random(93)
    houses = [(200, 400), (280, 360), (355, 430), (430, 330), (500, 400), (560, 470), (620, 300), (690, 390), (740, 330), (800, 430), (860, 350), (300, 480)]
    for i, (x, y) in enumerate(houses):
        body += f'<circle cx="{x}" cy="{y-22}" r="14" fill="url(#warm)"/>'
        body += f'<path d="M{x-16} {y} l16 -14 l16 14 v20 h-32 Z" fill="{INK}" stroke="{GOLD}" stroke-opacity=".35"/>'
        body += f'<rect x="{x-4}" y="{y-2}" width="8" height="8" fill="{GOLD}" opacity=".95"/>'
    for i in range(len(houses) - 1):
        x1, y1 = houses[i]
        x2, y2 = houses[i + 1]
        if i % 2 == 0:
            body += f'<path d="M{x1} {y1-22} L{x2} {y2-22}" stroke="{GOLD}" stroke-width="1" stroke-dasharray="3 7" opacity=".28"/>'
    body += text(60, 500, "虚构山谷 · 十二扇窗", size=15, fill=CREAM, opacity=.55, spacing=2)
    body += sparkles(91, 26, 120, 900, 360, 520)
    return frame(no, "山谷亮灯", "俯瞰虚构山谷，一扇扇窗依次亮起，连成星图。", body)


def seated(cx, y, s=1.0, fill=INK, accent=GOLD, lean=0):
    return f"""<g transform="translate({cx} {y}) scale({s}) rotate({lean})">
<path d="M-26 0 C-32 -34 -22 -62 0 -68 C22 -62 32 -34 26 0 Z" fill="{fill}"/>
<circle cx="0" cy="-82" r="14" fill="{fill}"/>
<path d="M-16 0 q-8 30 4 42 M16 0 q8 30 -4 42" stroke="{fill}" stroke-width="9" fill="none" stroke-linecap="round"/>
<path d="M-20 -40 q-20 12 -28 28 M20 -40 q18 10 24 24" stroke="{fill}" stroke-width="7" fill="none" stroke-linecap="round"/>
<path d="M-13 -77 q13 -8 26 0" stroke="{accent}" stroke-width="2" fill="none" opacity=".65"/>
</g>"""


def scene_10(no):
    body = stars(10, 60, 300) + moon(170, 100, 38)
    body += fog(560, 360, 360, 50)
    for i in range(18):
        x = 120 + (i * 83) % 760
        y = 360 + (i * 47) % 120
        body += f'<circle cx="{x}" cy="{y}" r="2.2" fill="{GOLD}" opacity="{0.3 + (i%4)*0.13:.2f}"/>'
    body += f'<path d="M0 430 L310 320 L620 360 L960 300 L960 540 L0 540 Z" fill="#082422"/>'
    body += f'<path d="M0 470 L340 360 L700 410 L960 350" stroke="{CREAM}" stroke-width="2" fill="none" opacity=".15"/>'
    body += seated(390, 400, 1.15, INK, GOLD, 0) + seated(560, 398, 1.1, INK, CINNABAR, 0)
    body += f'<path d="M475 365 V330" stroke="{CREAM}" stroke-width="1.2" opacity=".4"/><circle cx="475" cy="352" r="22" fill="url(#warm)"/><rect x="464" y="334" width="22" height="30" rx="4" fill="{GOLD}" opacity=".9"/>'
    body += sparkles(101, 20, 100, 880, 180, 330)
    return frame(no, "屋顶 · 并肩", "两人并肩坐在屋顶，脚下是灯海，头顶是星群。", body)


def scene_11(no):
    body = f'<rect width="960" height="540" fill="#071f1d"/>'
    body += stars(11, 40, 340) + moon(700, 130, 60)
    body += f'<circle cx="420" cy="250" r="230" fill="url(#cool)" opacity=".6"/>'
    body += f'<path d="M250 540 C260 420 300 330 390 300 C470 274 540 330 560 420 L590 540 Z" fill="{INK}"/>'
    body += f'<circle cx="420" cy="250" r="102" fill="{INK}"/>'
    body += f'<path d="M340 214 Q360 130 448 136 Q520 142 526 222" fill="{INK}"/>'
    body += f'<path d="M500 190 Q560 180 580 220" stroke="{INK}" stroke-width="24" fill="none" stroke-linecap="round"/>'
    body += f'<path d="M300 360 Q380 320 470 350 L500 540 L290 540 Z" fill="{TEAL}"/>'
    body += f'<path d="M330 372 Q400 342 470 366" stroke="{CINNABAR}" stroke-width="3" fill="none" opacity=".6"/>'
    body += lens(478, 250, 54)
    # stars reflected inside lens
    rnd = random.Random(111)
    for _ in range(9):
        a = rnd.uniform(0, math.tau)
        rr = rnd.uniform(8, 44)
        body += f'<circle cx="{478+math.cos(a)*rr:.1f}" cy="{250+math.sin(a)*rr:.1f}" r="1.3" fill="{CREAM}" opacity=".8"/>'
    body += f'<path d="M524 214 L760 90" stroke="{GOLD}" stroke-width="2" opacity=".55"/>'
    body += f'<rect x="742" y="412" width="86" height="86" fill="none" stroke="{CINNABAR}" stroke-width="3" opacity=".75"/><text x="785" y="463" text-anchor="middle" font-family="{FONT}" font-size="28" fill="{CINNABAR}" opacity=".85">回声</text>'
    body += sparkles(112, 22, 80, 880, 80, 440)
    return frame(no, "远视的答案", "近景：远视侧脸，镜片里映出星河，手扶灯罩。", body)


def scene_12(no):
    body = f'<rect width="960" height="540" fill="#071f1d"/>'
    body += f'<circle cx="480" cy="250" r="300" fill="url(#warm)" opacity=".22"/>'
    body += stars(12, 52, 360)
    body += f'<rect x="90" y="66" width="780" height="408" fill="none" stroke="{CREAM}" stroke-opacity=".22"/>'
    body += lens(250, 250, 46) + sound_arcs(710, 250, 30, GOLD, 3, .5, direction=-1)
    body += text(480, 236, "山谷回声", size=76, fill=CREAM, anchor="middle", spacing=10, weight=600)
    body += text(480, 292, "ECHOES OF THE VALLEY", size=14, fill=GOLD, anchor="middle", spacing=5, family=MONO)
    body += text(480, 340, "原创纸影短剧 · 12 格分镜 · 约 40 秒", size=18, fill=CREAM, anchor="middle", opacity=.78, spacing=2)
    body += f'<path d="M250 370 H710" stroke="{CREAM}" stroke-opacity=".2"/>'
    body += text(480, 404, "角色 / 剧本 / 分镜 / 画面 / 配音 / 字幕 均为自制合成样例", size=13, fill=CREAM, anchor="middle", opacity=.55, spacing=1)
    body += text(480, 432, "本地规则引擎 · 无真人出镜 · 无外部素材", size=12, fill=GOLD, anchor="middle", opacity=.65, family=MONO)
    body += f'<rect x="792" y="418" width="58" height="58" fill="{CINNABAR}" opacity=".85"/><text x="821" y="456" text-anchor="middle" font-family="{FONT}" font-size="19" fill="{CREAM}">样片</text>'
    return frame(no, "片尾 · 山谷回声", "片名字卡与制作声明，两枚角色符号与朱砂印章。", body)


SCENES = {1: scene_01, 2: scene_02, 3: scene_03, 4: scene_04, 5: scene_05, 6: scene_06,
          7: scene_07, 8: scene_08, 9: scene_09, 10: scene_10, 11: scene_11, 12: scene_12}


def portrait(kind):
    if kind == "yuanshi":
        name, role, tag, motifs = "远视", "守灯人", "看见还没被说出口的光", ["单圆镜片", "折光纸棱", "深青披风"]
        figure = yuanshi(240, 470, 2.05)
        accent = GOLD
        quote = "别出声，我把月光借过来。"
    else:
        name, role, tag, motifs = "远听", "听潮人", "听见旧物里没说完的话", ["贝壳耳廓", "同心声波", "朱砂披带"]
        figure = yuanting(240, 470, 2.05)
        accent = CINNABAR
        quote = "等等，我听见灯在抖。"
    chips = "".join(
        f'<rect x="{44 + i*128}" y="548" width="116" height="28" rx="14" fill="{CREAM}" opacity=".08"/>' +
        text(102 + i*128, 567, m, size=12, fill=CREAM, anchor="middle", opacity=.72)
        for i, m in enumerate(motifs)
    )
    body = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 620" width="480" height="620" role="img" aria-label="{esc(name)}角色设定卡，合成样例">
{DEFS}
<rect width="480" height="620" fill="url(#sky)"/>
<circle cx="240" cy="250" r="190" fill="url(#cool)" opacity=".55"/>
<circle cx="240" cy="250" r="152" fill="none" stroke="{accent}" stroke-opacity=".28" stroke-dasharray="2 8"/>
<path d="M0 470 Q120 440 240 456 Q360 472 480 448 L480 620 L0 620 Z" fill="#061b19"/>
{figure}
<rect width="480" height="620" fill="url(#fiber)"/>
<rect width="480" height="620" filter="url(#grain)" opacity=".045"/>
<rect x="18" y="18" width="444" height="584" fill="none" stroke="{CREAM}" stroke-opacity=".18"/>
{text(42, 52, "SYNTHETIC CHARACTER / 合成角色", size=11, fill=CREAM, opacity=.5, family=MONO, spacing=1.4)}
{text(42, 510, name, size=54, fill=CREAM, weight=600, spacing=6)}
{text(44, 538, role + " · 回声邮局", size=15, fill=accent, spacing=2)}
{text(240, 600, "“" + quote + "”", size=13, fill=CREAM, anchor="middle", opacity=.62)}
{chips}
{text(438, 52, "C / 1724", size=11, fill=CREAM, opacity=.4, anchor="end", family=MONO)}
</svg>"""
    return body


def poster():
    body = stars(99, 60, 380) + moon(930, 116, 66)
    body += mountain(430, "#0a2a28", 46, 991) + fog(500, 500, 620, 60)
    body += lens(220, 350, 56)
    body += yuanshi(330, 560, 1.7)
    body += yuanting(530, 560, 1.7, flip=True)
    body += sound_arcs(475, 400, 42, GOLD, 3, .5)
    body += text(86, 140, "CraftMesh · 文化 IP 短剧管线", size=15, fill=GOLD, spacing=3, family=MONO)
    body += text(80, 250, "山谷回声", size=102, fill=CREAM, weight=600, spacing=8)
    body += text(86, 306, "ECHOES OF THE VALLEY", size=16, fill=GOLD, spacing=6, family=MONO)
    body += text(86, 360, "原创纸影短剧 · 12 格分镜 · 40.4 秒可播放样片", size=20, fill=CREAM, opacity=.8)
    body += text(86, 398, "双原创角色：远视 / 远听 · 全部资产自制 · 无真人出镜", size=14, fill=CREAM, opacity=.55)
    body += f'<rect x="1020" y="520" width="96" height="96" fill="{CINNABAR}" opacity=".85"/><text x="1068" y="568" text-anchor="middle" font-family="{FONT}" font-size="24" fill="{CREAM}">合成</text><text x="1068" y="596" text-anchor="middle" font-family="{FONT}" font-size="18" fill="{CREAM}">样例</text>'
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630" role="img" aria-label="山谷回声原创纸影短剧合成样例海报">
{DEFS}
<rect width="1200" height="630" fill="url(#sky)"/>
{body}
<rect width="1200" height="630" fill="url(#fiber)"/>
<rect width="1200" height="630" filter="url(#grain)" opacity=".05"/>
<rect x="24" y="24" width="1152" height="582" fill="none" stroke="{CREAM}" stroke-opacity=".2"/>
</svg>"""
    return svg


def wrap_caption(value, width=18):
    if len(value) <= width:
        return value
    lines, current = [], ""
    for ch in value:
        current += ch
        if len(current) >= width and ch in "，。！？；：、":
            lines.append(current)
            current = ""
        elif len(current) >= width + 4:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return "\n".join(lines)


def fmt_srt_time(ms):
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_block(idx, start, end, caption):
    return f"{idx}\n{fmt_srt_time(start)} --> {fmt_srt_time(end)}\n{wrap_caption(caption)}\n"


def write_srt(path, blocks):
    path.write_text("\n".join(blocks).rstrip() + "\n", encoding="utf-8")


def build_srt(cfg):
    shots = cfg["shots"]
    cues = []
    start = 0
    for shot in shots:
        end = start + max(300, shot["durationMs"] - 120)
        cues.append(srt_block(shot["no"], start, end, shot["caption"]))
        start += shot["durationMs"]
    master = "\n".join(cues).rstrip() + "\n"
    (MEDIA / "subtitles").mkdir(parents=True, exist_ok=True)
    (MEDIA / "subtitles" / "ip_sample.srt").write_text(master, encoding="utf-8")
    for i, shot in enumerate(shots):
        write_srt(MEDIA / "subtitles" / f"shot-{shot['no']:02d}.srt",
                  [srt_block(1, 0, max(300, shot["durationMs"] - 120), shot["caption"])])
    return master


def run_voice(cfg):
    jobs = []
    for shot in cfg["shots"]:
        jobs.append({
            "id": shot["id"],
            "text": shot["caption"],
            "rate": int(shot.get("voiceRate", 0)),
            "out": str((MEDIA / "voice" / f"shot-{shot['no']:02d}.wav").resolve()),
        })
    payload = {"voice": cfg["media"]["voiceName"], "items": jobs}
    MEDIA.joinpath("voice").mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="ip_voice_", suffix=".json", dir=str(ROOT / "scripts"))
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "scripts" / "make_voice.ps1"), "-JobFile", tmp_name,
        ]
        proc = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"make_voice.ps1 failed ({proc.returncode}): {proc.stderr or proc.stdout}")
        print(proc.stdout.strip())
    finally:
        Path(tmp_name).unlink(missing_ok=True)


def wav_info(path):
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        return {
            "durationMs": round(frames / rate * 1000) if rate else 0,
            "sampleRate": rate,
            "channels": handle.getnchannels(),
            "sampleWidth": handle.getsampwidth(),
            "frames": frames,
            "bytes": path.stat().st_size,
        }


def build_master(cfg, infos):
    target = MEDIA / "voice" / "ip_sample.wav"
    voice_dir = MEDIA / "voice"
    rate = 22050
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        for shot in cfg["shots"]:
            info = infos[shot["no"]]
            slot_frames = round(shot["durationMs"] / 1000 * rate)
            clip_frames = info["frames"]
            with wave.open(str(voice_dir / f"shot-{shot['no']:02d}.wav"), "rb") as src:
                frames = src.readframes(min(clip_frames, slot_frames))
            out.writeframes(frames)
            out.writeframes(b"\x00" * ((slot_frames - min(clip_frames, slot_frames)) * 2))
    return wav_info(target)


def build_manifest(cfg, infos):
    shots, start = [], 0
    for shot in cfg["shots"]:
        info = infos[shot["no"]]
        svg_path = ROOT / shot["svg"].lstrip("/")
        srt_path = ROOT / shot["srt"].lstrip("/")
        item = {
            "index": shot["no"],
            "no": shot["no"],
            "id": shot["id"],
            "scene": shot["scene"],
            "sceneType": shot["sceneType"],
            "startMs": start,
            "endMs": start + shot["durationMs"],
            "durationMs": shot["durationMs"],
            "caption": shot["caption"],
            "speaker": shot["speaker"],
            "svg": shot["svg"],
            "audio": shot["audio"],
            "srt": shot["srt"],
            "audioDurationMs": info["durationMs"],
            "audioSampleRate": info["sampleRate"],
            "audioChannels": info["channels"],
            "audioBytes": info["bytes"],
            "audioFitsSlot": info["durationMs"] <= shot["durationMs"],
            "svgBytes": svg_path.stat().st_size if svg_path.exists() else 0,
            "srtBytes": srt_path.stat().st_size if srt_path.exists() else 0,
        }
        shots.append(item)
        start += shot["durationMs"]
    master = wav_info(MEDIA / "voice" / "ip_sample.wav")
    manifest = {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "voiceName": cfg["media"]["voiceName"],
        "totalMs": start,
        "shots": shots,
        "master": {
            "audio": "/media/voice/ip_sample.wav",
            "srt": "/media/subtitles/ip_sample.srt",
            "durationMs": master["durationMs"],
            "sampleRate": master["sampleRate"],
            "channels": master["channels"],
            "bytes": master["bytes"],
        },
        "assets": {
            "svg": len(shots),
            "wav": len(shots),
            "srt": len(shots) + 1,
            "characters": 2,
            "poster": 1,
        },
    }
    (MEDIA / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-voice", action="store_true", help="skip SAPI voice generation")
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    total = sum(int(s["durationMs"]) for s in cfg["shots"])
    if not (cfg["media"]["minMs"] <= total <= cfg["media"]["maxMs"]):
        raise SystemExit(f"shot total {total}ms outside {cfg['media']['minMs']}-{cfg['media']['maxMs']}ms")
    for sub in ("characters", "scenes", "voice", "subtitles"):
        (MEDIA / sub).mkdir(parents=True, exist_ok=True)

    for shot in cfg["shots"]:
        svg = SCENES[shot["no"]](shot["no"])
        (ROOT / shot["svg"].lstrip("/")).write_text(svg, encoding="utf-8")
    for key in ("yuanshi", "yuanting"):
        (MEDIA / "characters" / f"{key}.svg").write_text(portrait(key), encoding="utf-8")
    (MEDIA / "ip-poster.svg").write_text(poster(), encoding="utf-8")

    build_srt(cfg)
    if args.no_voice:
        if not all((MEDIA / "voice" / f"shot-{s['no']:02d}.wav").exists() for s in cfg["shots"]):
            raise SystemExit("--no-voice requested but some wav files are missing")
    else:
        run_voice(cfg)

    infos = {s["no"]: wav_info(MEDIA / "voice" / f"shot-{s['no']:02d}.wav") for s in cfg["shots"]}
    master = build_master(cfg, infos)
    manifest = build_manifest(cfg, infos)
    print(json.dumps({
        "totalMs": manifest["totalMs"],
        "masterMs": master["durationMs"],
        "shots": len(manifest["shots"]),
        "audio": {k: v for k, v in infos.items()},
        "voiceName": manifest["voiceName"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
