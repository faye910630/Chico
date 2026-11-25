"""
Chico 點陣桌寵（以「朵莉姆桌寵」l2d_pet.pyw 為底改編）

- 角色：preview/ 的 PSD（洋裝／水手服各 8 視角）點陣化成 75×75，顯示為 130×130 px（sprites.py）
- 以類 Live2D 參數做整數像素變形：呼吸、頭部擺動、身體傾斜、頭髮／裙擺物理、腿部擺動
- 視線：眼睛跟著滑鼠移動、會眨眼；滑鼠很遠時轉向斜側
- 玩具：小狸貓（抱抱、拋高高、可以用滑鼠丟）；邊走邊扔零食（棒棒糖、餅乾、蛋糕、甜甜圈）

執行：pythonw chico_pet.pyw
預覽：python chico_pet.pyw --demo out.gif   （不開視窗，輸出示範動畫）
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

FROZEN = getattr(sys, "frozen", False)  # PyInstaller 打包後的 exe
# 打包後：素材（點陣圖、字型、圖示）在 exe 內部（_MEIPASS）；Unity 小遊戲放在 exe 旁邊
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) if FROZEN else Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else ROOT
sys.path.insert(0, str(ROOT))
import sprites as S  # noqa: E402  Chico 的點陣素材

# yaw：0 = 正面，往畫面右轉為正。(key, True) 原本是鏡像；Chico 有真正的右前／右後視角（見 CHICO_VIEW）
YAW_VIEWS = [
    ("front", False),  # 0
    ("fl", True),  # 45  右前
    ("right", False),  # 90
    ("bl", True),  # 135 右後
    ("back", False),  # 180
    ("bl", False),  # 225 左後
    ("left", False),  # 270
    ("fl", False),  # 315 左前
]
# Rig 的視圖 key → Chico 的 PSD 視角
CHICO_VIEW = {("front", False): "front", ("fl", False): "fl", ("fl", True): "fr", ("left", False): "left",
              ("right", False): "right", ("bl", False): "bl", ("bl", True): "br", ("back", False): "back",
              ("top", False): "front", ("bottom", False): "back"}
# 前空翻：pitch 0/90/180/270 → (視圖, 額外平面旋轉)
FLIP_VIEWS = [(("front", False), 0), (("top", False), 0), (("back", False), 180), (("bottom", False), 0)]

# 顯示倍率（角色本體 75×75 點陣 → 螢幕 130×130 px）
SCALE = S.SCALE  # 130/75
SNACK_DISPLAY = 20  # 地上／丟出的零食：最長邊 20px
BUBBLE_SCALE = 1  # 說話泡泡：11px 點陣字原生大小（1 倍，不放大才不會太大）

SHOULDER_ROW = 38  # 側面圖（75 格）肩膀所在列
NECK_ROW = 37  # 頭／身體的分界列
ARM_SWING = 40.0  # 走路時手臂擺動角度（Chico 的袖子畫在身體圖裡，不另外畫手臂）
HAS_WINGS = False  # Chico 沒有翅膀
DEFORM = False  # 分區塊變形（呼吸、頭擺、頭髮裙擺物理）：會讓點陣圖一直抖、容易破圖，所以關掉
BLINK_MIN_S, BLINK_MAX_S = 2.2, 5.5
WALK_SPEED = 0.26  # 走路速度（角色高度／秒）
WALK_STEP_HZ = 1.3  # 每秒步伐循環數
WALK_STRIDE = 4.0  # 跨步（點陣格）
TRIP_CHANCE = 0.08  # 每次走路跌倒的機率
FOLLOW_START = 1.1  # 滑鼠離她超過幾個角色寬就跟過去（角色高度單位）
FOLLOW_STOP = 0.45  # 走到離滑鼠這麼近就停
FOLLOW_IDLE_S = 2.5  # 滑鼠停止移動多久後就不跟了
FOLLOW_SPEED = 0.4  # 跟著滑鼠走時的速度（比散步快一點）
FOLLOW_STEP_HZ = 2.0
CLIMB_SPEED = 0.45  # 爬視窗速度（角色高度／秒）
ARM_PATTERN = [  # 她不會露出手：袖子一路蓋到底，袖口是深色荷葉邊
    "..ooo..",
    ".o###o.",
    ".o###o.",
    ".o####o",
    "o#####o",
    "o#####o",
    "o#####o",
    "o#####o",
    "o#####o",
    "oFFFFFo",
    "oF.F.Fo",
    ".o.o.o.",
]
N = S.N  # 角色點陣尺寸（75）
PAD = 10  # 變形用留白
CANVAS = N + 2 * PAD + 1  # 偶數寬，旋轉中心落在整數格上，靜止時不會半格抖動
WIN_N = 134  # 原生視窗尺寸（容納旋轉／壓扁）
OUTLINE = S.OUTLINE

# 「原圖座標」直接用 75 格點陣本身（Chico 的點陣圖由 sprites.py 從 PSD 產生）
SRC = N
SRC_Y0, SRC_Y1 = 0, N
KN = 1.0  # 每個原圖像素對應的點陣像素
CROP_HALF = N / 2
CENTER_Y = 38  # 身體中心列（旋轉中心）
FEET_Y = S.FEET_Y + 1  # 腳底
HEAD_Y = 2  # 頭頂


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ease(p):
    return p * p * (3 - 2 * p)


def rot2(x, y, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return x * c - y * s, x * s + y * c


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


# ------------------------------------------------------------------ rig
def _lum(c):
    return c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114


_OUTFIT_CACHE: dict = {}


def load_outfit(name: str) -> "S.Outfit":
    """讀取一套 Chico 的衣服（8 視角圖層，點陣化在需要時才做、做過就快取）。"""
    key = OUTFITS[name]
    if key not in _OUTFIT_CACHE:
        _OUTFIT_CACHE[key] = S.Outfit(key, S.export_layers())
    return _OUTFIT_CACHE[key]


def build_pixel_sprites(name=None) -> dict[str, Image.Image]:
    """目前這套衣服的 75×75 點陣圖（給小遊戲、匯出用）。"""
    o = load_outfit(name or DEFAULT_OUTFIT)
    return {k: Image.fromarray(o.full(v)) for k, v in
            (("front", "front"), ("fl", "fl"), ("fr", "fr"), ("left", "left"), ("right", "right"),
             ("bl", "bl"), ("br", "br"), ("back", "back"))}


# ------------------------------------------------------------------ 月光花（點陣）
FLOWER_W, FLOWER_H = 23, 42
FLOWER_STAGES = [(0, "種子"), (15, "發芽"), (45, "藤葉"), (90, "花苞"), (150, "開花")]  # 種下後秒數
PLANT_CHANCE = 0.4  # （山谷裝飾用的月光花）
MAX_FLOWERS = 15
SNACK_CHANCE = 0.55  # 每次走路扔零食的機率
MAX_SNACKS = 15
SNACK_LIFE_S = 600.0  # 零食放在地上多久會消失

_C = {
    "o": OUTLINE,
    "L": (36, 62, 42, 255),  # 葉外框
    "G": (98, 150, 84, 255),  # 葉
    "g": (146, 192, 118, 255),  # 葉亮部
    "S": (84, 122, 66, 255),  # 莖
    "W": (246, 246, 238, 255),  # 花瓣
    "w": (222, 228, 216, 255),  # 花瓣陰影
    "y": (206, 226, 168, 255),  # 星形花脈（淡綠）
    "c": (222, 228, 130, 255),  # 花心
    "D": (92, 70, 58, 255),  # 土
    "d": (122, 96, 76, 255),  # 土亮部
}
_LEAF = [
    ".LL.LL.",
    "LGgLGGL",
    "LGgGGGL",
    ".LGGGL.",
    "..LGL..",
    "...L...",
]
_SPROUT = [
    "LL...LL",
    "LgL.LGL",
    ".LGSGL.",
    "...S...",
]
_BUD = [
    ".o.",
    "oWo",
    "owo",
    "oyo",
    "oGo",
    ".L.",
]


def _stamp(arr, pattern, x0, y0, flip=False):
    for j, row in enumerate(pattern):
        if flip:
            row = row[::-1]
        for i, ch in enumerate(row):
            if ch != ".":
                x, y = x0 + i, y0 + j
                if 0 <= x < arr.shape[1] and 0 <= y < arr.shape[0]:
                    arr[y, x] = _C[ch]


def _bloom(arr, cx, cy, open_frac=1.0):
    """正面的月光花：白色圓形花瓣＋五道淡綠星紋＋花心。"""
    R = 6.2 * open_frac
    mask = np.zeros(arr.shape[:2], bool)
    rays = [math.radians(-90 + 72 * k) for k in range(5)]
    for y in range(arr.shape[0]):
        for x in range(arr.shape[1]):
            dx, dy = x - cx, y - cy
            r = math.hypot(dx, dy)
            th = math.atan2(dy, dx)
            if r <= R * (0.93 + 0.07 * math.cos(5 * (th + math.pi / 2))):
                mask[y, x] = True
                col = _C["W"] if dy < 2.5 else _C["w"]
                for a in rays:
                    if r > 0.5 and abs(math.sin(th - a)) * r < 0.55 and math.cos(th - a) > 0:
                        col = _C["y"]
                if r < 1.3:
                    col = _C["c"]
                arr[y, x] = col
    nb = np.zeros_like(mask)
    nb[1:] |= mask[:-1]
    nb[:-1] |= mask[1:]
    nb[:, 1:] |= mask[:, :-1]
    nb[:, :-1] |= mask[:, 1:]
    arr[nb & ~mask] = _C["o"]


def draw_moonflower(stage: int, sway: int = 0, glow: float = 0.0) -> Image.Image:
    """回傳 FLOWER_W×FLOWER_H 的點陣圖。stage 0~4，sway 為頂端左右 1 格擺動，glow 0~1 夜光。"""
    W, H = FLOWER_W, FLOWER_H
    arr = np.zeros((H, W, 4), np.uint8)
    cx = W // 2
    base = H - 1
    # 土堆
    _stamp(arr, ["..DDD..", ".DdddD.", "DDDDDDD"], cx - 3, base - 2)
    if stage == 0:
        arr[base - 3, cx] = _C["d"]
        return Image.fromarray(arr)
    if stage == 1:
        _stamp(arr, _SPROUT, cx - 3, base - 6)
        return Image.fromarray(arr)
    stem_h = {2: 14, 3: 21, 4: 22}[stage]
    top = base - 2 - stem_h
    # 微彎的藤蔓莖
    for y in range(top, base - 2):
        f = (base - 2 - y) / stem_h
        x = cx + int(round(math.sin(f * 3.2) * 1.2 + sway * f * f))
        arr[y, x] = _C["S"]
    leaf_rows = {2: [6, 11], 3: [6, 12, 17], 4: [6, 12, 17]}[stage]
    for k, h in enumerate(leaf_rows):
        y = base - 2 - h
        f = h / stem_h
        x = cx + int(round(math.sin(f * 3.2) * 1.2 + sway * f * f))
        if k % 2 == 0:
            _stamp(arr, _LEAF, x + 1, y - 2)
        else:
            _stamp(arr, _LEAF, x - 7, y - 2, flip=True)
    tx = cx + int(round(math.sin(3.2) * 1.2 + sway))
    if stage == 3:
        _stamp(arr, _BUD, tx - 1, top - 6)
    elif stage == 4:
        fy = top - 6
        if glow > 0:
            g = np.zeros_like(arr)
            for y in range(H):
                for x in range(W):
                    r = math.hypot(x - tx, y - fy)
                    if 6.8 < r <= 9.6:
                        a = int((80 if r <= 8.2 else 34) * glow)
                        g[y, x] = (236, 248, 255, a)
            under = arr[..., 3] == 0
            arr[under] = g[under]
        _bloom(arr, tx, fy)
    return Image.fromarray(arr)


def moonflower_icon(size=32) -> Image.Image:
    """（舊）月光花圖示；保留給匯出素材用。"""
    arr = np.zeros((16, 16, 4), np.uint8)
    _bloom(arr, 7.5, 7.5)
    return Image.fromarray(arr).resize((size, size), Image.NEAREST)


def tanuki_icon(size=32) -> Image.Image:
    """視窗／程式圖示：正面小狸貓點陣，置中後以最近鄰放大。"""
    src = Image.fromarray(S.tanuki("front", 28))
    box = src.getbbox() or (0, 0, src.width, src.height)
    crop = src.crop(box)
    side = max(crop.width, crop.height) + 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2), crop)
    return canvas.resize((size, size), Image.NEAREST)


def write_tanuki_ico(path: Path | None = None) -> Path:
    """把多尺寸狸貓圖示寫成 .ico（給捷徑／工作列用）。"""
    import io
    import struct

    path = path or (ROOT / "assets" / "icons" / "tanuki.ico")
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [tanuki_icon(n).convert("RGBA") for n in sizes]
    entries, blobs, offset = [], [], 6 + 16 * len(sizes)
    for im, size in zip(imgs, sizes):
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        data = buf.getvalue()
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries.append(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset))
        blobs.append(data)
        offset += len(data)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(blobs))
    tanuki_icon(32).save(path.with_name("tanuki_32.png"))
    tanuki_icon(64).save(path.with_name("tanuki_64.png"))
    return path


def flower_stage(age_s: float) -> int:
    st = 0
    for i, (t, _) in enumerate(FLOWER_STAGES):
        if age_s >= t:
            st = i
    return st


def is_night() -> bool:
    h = time.localtime().tm_hour
    return h >= 18 or h < 6


# ------------------------------------------------------------------ 道具／粒子（點陣）
def _pix(rows, cols):
    h, w = len(rows), max(len(r) for r in rows)
    a = np.zeros((h, w, 4), np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                a[y, x] = cols[ch]
    return Image.fromarray(a)


_PC = {
    "o": OUTLINE,
    "p": (250, 190, 206, 255),  # 粉色糰子
    "P": (255, 222, 230, 255),
    "w": (246, 244, 238, 255),  # 白色糰子
    "W": (255, 255, 255, 255),
    "g": (166, 210, 144, 255),  # 綠色糰子
    "G": (198, 232, 176, 255),
    "k": (150, 112, 78, 255),  # 竹籤
    "c": (232, 230, 244, 255),  # 枕頭
    "C": (200, 196, 222, 255),
    "f": (250, 252, 255, 255),  # 泡沫
    "F": (214, 228, 246, 255),
    "b": (176, 214, 244, 255),  # 泡泡框
    "i": (214, 236, 255, 110),  # 泡泡內
    "z": (226, 226, 255, 255),
    "h": (255, 150, 182, 255),
    "s": (255, 248, 206, 255),
    "d": (150, 200, 255, 255),
    "u": (178, 172, 168, 255),
    "r": (206, 164, 116, 255),
}


_CANDY = dict(_PC, W=(255, 255, 255, 255), w=(232, 234, 246, 255), S=(255, 252, 226, 255),
              o=(150, 148, 186, 255), g=(196, 222, 160, 255), c=(222, 228, 130, 255))
STAR_CANDY = [  # 白色星星糖果（中間是一朵月光花）：一口比一口小
    _pix([
        "....o....",
        "...oWo...",
        "...ogo...",
        "ooooWoooo",
        "oWWgcgWWo",
        ".oWWgWwo.",
        "..ogWgo..",
        ".oWwowWo.",
        ".oWo.owo.",
        ".oo...oo.",
    ], _CANDY),
    _pix([
        "...o...",
        "..ogo..",
        "ooWgWoo",
        "oWgcgwo",
        ".oWgwo.",
        "oWwowWo",
        "oo...oo",
    ], _CANDY),
    _pix([
        "..o..",
        ".ogo.",
        "ogcgo",
        ".owo.",
        "o...o",
    ], _CANDY),
]
HOLD_PATTERN = [  # 用大袖子捧著糖果（手藏在袖子裡，不露出來）
    "o###o...o###o",
    "o###o...o###o",
    "o###o...o###o",
    "oFFFo...oFFFo",
    ".o.o.....o.o.",
]
MOUTH_ROW = 28  # 正面圖（75 格）嘴巴所在列



BED_LIFT = 10  # 床墊離地高度（點陣格）；躺著時床墊以下的身體不畫（像蓋在被子裡）


def make_moonflower_bed(glow=0.0):
    """小狸貓湖水綠小床：湖水綠的床架、床頭是小狸貓的臉（耳朵、眼罩、頭上的葉子），床尾是狸貓尾巴的條紋，
    床架上有往上飄的小泡泡。側面視角，頭在左邊。
    回傳 (後層：床架／床墊／床頭, 前層：枕頭＋床尾，會蓋住她的身體)。兩層同尺寸、底部對齊地面。"""
    W, H = 78, 30
    floor = H - 1
    mat_top = floor - BED_LIFT  # 床墊上緣（她躺在這裡）
    frame = (168, 230, 216, 255)
    frame_d = (112, 196, 182, 255)
    line = (34, 92, 96, 255)
    sheet = (246, 252, 250, 255)
    sheet_d = (214, 238, 232, 255)
    fur = (186, 140, 100, 255)
    fur_d = (110, 70, 56, 255)
    fur_l = (222, 186, 150, 255)
    leaf = (70, 150, 92, 255)
    bubble = (214, 252, 244, 255)

    back = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    front = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    db, df_ = ImageDraw.Draw(back), ImageDraw.Draw(front)

    # 床腳（小狸貓的腳掌）與床架側板
    for x0 in (3, W - 8):
        db.rounded_rectangle((x0, floor - 3, x0 + 4, floor), radius=1, fill=fur, outline=fur_d)
    db.rectangle((2, mat_top + 3, W - 3, floor - 3), fill=frame, outline=line)
    db.line((3, mat_top + 5, W - 4, mat_top + 5), fill=frame_d)
    # 床墊與床單
    db.rectangle((5, mat_top - 1, W - 6, mat_top + 3), fill=sheet, outline=line)
    db.line((6, mat_top + 2, W - 7, mat_top + 2), fill=sheet_d)
    # 床頭（左，高）：柱子＋頂端的小狸貓臉
    db.rectangle((1, 9, 7, floor - 3), fill=frame, outline=line)
    db.line((4, 13, 4, floor - 4), fill=frame_d)
    db.polygon([(0, 3), (2, 0), (4, 3)], fill=fur, outline=fur_d)  # 耳朵
    db.polygon([(6, 3), (8, 0), (10, 3)], fill=fur, outline=fur_d)
    db.ellipse((-1, 2, 11, 12), fill=fur, outline=fur_d)  # 臉
    db.rectangle((1, 6, 9, 8), fill=fur_d)  # 眼罩
    for ex in (3, 7):
        db.point((ex, 7), fill=(250, 250, 250, 255))
    db.point((5, 9), fill=(60, 40, 36, 255))  # 鼻子
    db.ellipse((3, 9, 7, 11), outline=fur_l)
    db.polygon([(3, 2), (6, -1), (8, 1), (5, 3)], fill=leaf)  # 頭上的葉子
    # 枕頭（前層、矮矮的：她的頭枕在上面）—湖水綠點點
    df_.rounded_rectangle((6, mat_top - 4, 25, mat_top + 1), radius=2, fill=sheet, outline=line)
    for x in range(9, 24, 4):
        df_.point((x, mat_top - 2), fill=frame_d)
    # 床尾（右，矮）：小狸貓尾巴的條紋—畫在前層，蓋住她的腳尖
    df_.rounded_rectangle((W - 7, mat_top - 8, W - 1, floor - 3), radius=3, fill=fur, outline=fur_d)
    for y in range(mat_top - 6, floor - 3, 3):
        df_.line((W - 6, y, W - 2, y), fill=fur_d)
    df_.point((W - 4, mat_top - 7), fill=fur_l)

    # 床架上往上飄的小泡泡
    def put(img, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            img.putpixel((x, y), c)

    for i, x in enumerate(range(12, W - 10, 9)):
        y = mat_top + 6 + (1 if i % 2 else 0)
        r = 1 + (i % 2)
        db.ellipse((x - r, y - r, x + r, y + r), outline=bubble)
        put(back, x - (1 if r > 1 else 0), y - (1 if r > 1 else 0), (255, 255, 255, 255))
    # 床架上的小葉子（跟狸貓頭上的一樣）
    for x in (20, 44, 64):
        for dx, dy in ((0, 0), (1, 0), (1, -1), (2, -1)):
            put(back, x + dx, floor - 5 + dy, leaf)

    # 夜裡：床頭和床尾發出湖水綠的光
    arr_b = np.array(back)
    arr_f = np.array(front)
    if glow > 0:
        yy, xx = np.mgrid[0:H, 0:W]
        for arr, (cx, cy, rr) in ((arr_b, (5, 7, 8.5)), (arr_f, (W - 4, mat_top - 6, 6.0))):
            r = np.hypot(xx - cx, yy - cy)
            halo = np.zeros_like(arr)
            halo[(r <= rr) & (r > rr - 2.2)] = (200, 255, 240, int(90 * glow))
            e = arr[..., 3] == 0
            arr[e] = halo[e]
    return Image.fromarray(arr_b), Image.fromarray(arr_f)


SLEEP_MIN_S = 90.0  # 至少睡這麼久（體力回滿也不會馬上起來）
SLEEP_MAX_S = 180.0


PILLOW = _pix([
    "..oooooooooooooooooo..",
    ".occccccccccccccccccco.",
    "occccccccccccccccccccco",
    "oCcccccccccccccccccCCCo",
    ".oCCCCCCCCCCCCCCCCCCCo.",
    "..ooooooooooooooooooo..",
], _PC)

FOAM = _pix([
    "......oWo.......",
    ".....oWsWo......",
    "......oWo.......",
    "....ff...ff.....",
    "..ffffff.fffff..",
    ".ffffffffffffff.",
    "fffFfffffffFffff",
    ".FFffffFFfffFFf.",
    "..FF.FFF..FFF...",
], _PC)

PARTICLES = {
    "bubble": _pix([".bbb.", "bWiib", "biiib", "biiib", ".bbb."], dict(_PC, W=(255, 255, 255, 230))),
    "z": _pix(["zzzz", "..z.", ".z..", "zzzz"], _PC),
    "crumb": _pix(["r"], _PC),
    "drop": _pix(["d", "d"], _PC),
    "spark": _pix([".s.", "sss", ".s."], _PC),
    "dust": _pix(["uu", "uu"], _PC),
    "heart": _pix([".h.h.", "hhhhh", ".hhh.", "..h.."], _PC),
}

# ------------------------------------------------------------------ 台詞
# 個性：開朗、元氣、愛笑。她的元素是「甜點」：最愛馬卡龍、蛋糕、餅乾、糖果，說話三句不離點心，
# 常用「～」「！」。住在夢幻甜點屋（檸檬起司＋藍綠糖霜小屋），最好的朋友是小狸貓。
PET_NAME = "Chico"
PERSONA = "Chico：薄荷綠頭髮、開朗愛笑、超愛甜點的女孩，住在藍綠黃的夢幻甜點屋，最好的朋友是小狸貓"
CHATTER_CHANCE = 0.3  # 發呆時自言自語的機率（愛講話）
LINES = {
    "idle": ["今天的點心要吃什麼呢～", "好想吃檸檬起司蛋糕！", "馬卡龍要配什麼顏色好呢？", "啦啦啦～甜甜的一天♪",
             "聞到餅乾烤好的香味了！", "小狸貓也想吃點心嗎？", "棉花糖軟綿綿～", "薄荷巧克力最棒了！",
             "嘿嘿，偷偷藏了一顆糖果～"],
    "night": ["睡前來一杯熱可可～", "晚上吃甜點…只吃一個就好！", "甜點屋的燈好像檸檬糖色～"],
    "click": ["嗨嗨！要吃糖嗎？", "嘻嘻，好癢！", "找我嗎～有點心嗎？", "嘿！", "被發現在偷吃了～", "請你吃一顆糖！"],
    "eat": ["好好吃！", "嗯～甜甜的！", "還想再吃一個！", "幸福的味道～", "這個最好吃了！"],
    "hungry": ["肚子咕嚕咕嚕叫了～", "想吃馬卡龍！", "點心時間到了嗎？"],
    "dirty": ["身上都是糖霜了～想洗澡！"],
    "sleepy": ["呼啊～吃飽飽想睡覺了…"],
    "trip": ["哎呀！", "嘿嘿，跌倒了～還好點心沒掉！", "沒事沒事！"],
    "chat": ["嗯嗯！", "真的嗎？好厲害！", "原來如此～", "那要不要一起吃點心？", "嘿嘿～", "再多說一點嘛！",
             "Chico 有在聽喔！"],
    "follow": ["等等我～", "你要去買點心嗎？", "跟上跟上！"],
    "wish": ["希望每天都有吃不完的蛋糕！", "希望馬卡龍山出現～", "流星流星～給我糖果雨！", "希望大家都甜甜的！"],
}

CHAT_RULES = [
    (("巧克力",), None, "薄荷巧克力！跟我的頭髮一樣顏色～"),
    (("布丁",), None, "布丁搖搖晃晃的好可愛～"),
    (("冰淇淋",), None, "冰淇淋！我要三球！"),
    (("馬卡龍",), "eat", "馬卡龍！最愛了～"),
    (("蛋糕",), "eat", "蛋糕！要草莓的那種～"),
    (("餅乾",), "eat", "剛烤好的餅乾最香了！"),
    (("吃", "餓", "糖", "點心", "飯", "甜"), "eat", "點心時間～開動囉！"),
    (("洗", "澡", "髒"), "bath", "泡泡澡時間～把糖霜洗掉！"),
    (("醒", "起床"), "wake", "早安！早餐要吃鬆餅！"),
    (("睡", "累", "晚安", "休息"), "sleep", "晚安～夢裡也要吃蛋糕！"),
    (("爬", "窗"), "climb", "看我爬上去！"),
    (("下來",), "jump_down", "跳囉～！"),
    (("跳舞", "舞"), "dance", "一起跳舞吧～♪"),
    (("跳",), "bounce", "蹦蹦跳跳～像果凍一樣！"),
    (("翻",), "frontflip", "看我翻一圈！"),
    (("轉",), "spin", "轉圈圈～像棒棒糖！"),
    (("零食", "扔", "丟"), "plant", "請你吃點心！"),
    (("吊",), "hang", "倒過來看世界～"),
    (("拋", "高高"), "toss", "小狸貓飛高高～"),
    (("狸貓", "玩偶", "娃娃", "抱"), "plush", "小狸貓抱抱！"),
    (("星星", "接"), "stars", "一起接點心！"),
    (("願", "許願", "流星", "祈禱"), "wish", "我要許願！"),
    (("換裝", "衣服", "穿"), "outfit", "換衣服囉～"),
    (("泡泡", "射擊", "遊戲", "玩"), "game", "來射泡泡吧！"),
    (("走", "散步"), "walk", "去散步～順便找點心！"),
    (("跌", "摔"), "trip", "才、才不會跌倒呢！"),
    (("早安", "你好", "嗨", "哈囉", "hi", "hello"), None, "嗨嗨～你好呀！要吃糖嗎？"),
    (("喜歡", "愛"), None, "我也最喜歡你了！跟喜歡蛋糕一樣喜歡！"),
    (("名字", "你是誰", "叫什麼"), None, "我是 Chico！最喜歡甜點了～"),
    (("Chico", "chico"), None, "有！叫我嗎？有點心嗎？"),
    (("謝謝",), None, "不客氣～請你吃顆糖！"),
    (("甜點屋", "小屋", "家"), None, "我家是檸檬起司做的喔～屋頂是藍綠糖霜！"),
]


def respond(text: str):
    t = text.lower()
    for keys, act, reply in CHAT_RULES:
        if any(k in t for k in keys):
            return reply, act
    return random.choice(LINES["chat"]), None


DREAM_TALK = [
    "我最喜歡的是檸檬起司蛋糕！上面的檸檬皮要留到最後吃～",
    "馬卡龍我最愛薄荷口味！跟我的頭髮一樣顏色喔～",
    "小狸貓最喜歡餅乾，每次都偷偷吃掉我的那一塊！",
    "甜點屋的屋頂是藍綠糖霜，太陽一晒會閃閃發亮～",
    "昨天夢到下了一場甜甜圈雨！好想再夢一次～",
    "下次來我家，我烤一整盤餅乾請你吃！",
    "門口的台階是馬卡龍喔！踩上去軟軟的～",
]


# ------------------------------------------------------------------ 照顧數值
CARE_KEYS = ("hunger", "clean", "mood", "energy")
CARE_NAMES = {"hunger": "飽食", "clean": "清潔", "mood": "心情", "energy": "體力"}
CARE_DECAY = {"hunger": 10.0, "clean": 6.0, "mood": 5.0, "energy": 8.0}  # 每小時下降
SLEEP_ENERGY_PER_S = 0.9  # 睡覺時每秒回復體力（睡久一點）


class Care:
    def __init__(self, path: Path | None):
        self.path = path
        self.v = {k: 80.0 for k in CARE_KEYS}
        self.save_t = 0.0
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            self.v.update({k: float(d["v"][k]) for k in CARE_KEYS})
            self.decay(min(max(time.time() - float(d["t"]), 0), 48 * 3600), False)
        except Exception:
            pass

    def decay(self, sec, sleeping):
        h = sec / 3600
        for k in CARE_KEYS:
            if k == "energy" and sleeping:
                continue
            self.v[k] -= CARE_DECAY[k] * h
        low = sum(1 for k in ("hunger", "clean", "energy") if self.v[k] < 25)
        self.v["mood"] -= low * 3 * h
        if sleeping:
            self.v["energy"] += SLEEP_ENERGY_PER_S * sec
        for k in CARE_KEYS:
            self.v[k] = max(0.0, min(100.0, self.v[k]))

    def tick(self, dt, sleeping):
        self.decay(dt, sleeping)
        self.save_t += dt
        if self.save_t > 30:
            self.save()

    def add(self, k, n):
        self.v[k] = max(0.0, min(100.0, self.v[k] + n))

    def save(self):
        self.save_t = 0.0
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"v": self.v, "t": time.time()}), encoding="utf-8")
        except Exception:
            pass


# ------------------------------------------------------------------ 說話泡泡（Cubic 11 點陣字）
FONT_PATH = ROOT / "fonts" / "Cubic_11.ttf"
_font_cache = {}


def pixel_font(size=11):
    if size not in _font_cache:
        try:
            from PIL import ImageFont

            _font_cache[size] = ImageFont.truetype(str(FONT_PATH), size)
        except Exception:
            from PIL import ImageFont

            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def _wrap(text, n=10):
    out, line = [], ""
    for ch in text:
        line += ch
        if len(line) >= n:
            out.append(line)
            line = ""
    if line:
        out.append(line)
    return out or [""]


BUBBLE_FONT_PX = 11  # Cubic 11 的原生大小（點陣字要用原生大小才不會糊）


def render_bubble(text: str, size: int = BUBBLE_FONT_PX) -> Image.Image:
    """原生解析度的說話泡泡（白底、深色外框、下方小尾巴）。"""
    font = pixel_font(size)
    lines = _wrap(text, 14)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = max(int(tmp.textlength(ln, font=font)) for ln in lines)
    lh = size + 2
    w, h = tw + 8, lh * len(lines) + 5
    img = Image.new("RGBA", (w, h + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    d.rectangle((1, 0, w - 2, h - 1), fill=(250, 250, 252, 255))
    d.rectangle((0, 1, w - 1, h - 2), fill=(250, 250, 252, 255))
    o = OUTLINE
    d.line((2, 0, w - 3, 0), fill=o)
    d.line((2, h - 1, w - 3, h - 1), fill=o)
    d.line((0, 2, 0, h - 3), fill=o)
    d.line((w - 1, 2, w - 1, h - 3), fill=o)
    for x, y in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
        img.putpixel((x, y), o)
    cx = w // 2
    for i, (a, b) in enumerate(((-2, 2), (-1, 1), (0, 0))):
        y = h - 1 + i
        d.line((cx + a, y, cx + b, y), fill=(250, 250, 252, 255))
        img.putpixel((cx + a - 1, y), o)
        img.putpixel((cx + b + 1, y), o)
    img.putpixel((cx, h + 2), o)
    for i, ln in enumerate(lines):
        d.text((4, 2 + i * lh), ln, font=font, fill=(52, 46, 64, 255))
    return img


# ------------------------------------------------------------------ 背景：永夜的月光花黑色山谷
_BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16.0


def _dither_gradient(h, w, c0, c1, steps=6):
    t = np.linspace(0, 1, h)[:, None] * np.ones((1, w))
    q = np.floor(t * steps + _BAYER[np.arange(h)[:, None] % 4, np.arange(w)[None, :] % 4]) / steps
    q = np.clip(q, 0, 1)[..., None]
    return (np.array(c0) * (1 - q) + np.array(c1) * q).astype(np.uint8)


def draw_valley(t: float, w=200, h=125) -> Image.Image:
    """黑色山谷：永遠的黑夜、滿谷月光花、飄著螢光花粉。"""
    sky = _dither_gradient(h, w, (4, 4, 12), (20, 16, 38), 7)
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = sky
    img[..., 3] = 255
    rng = np.random.default_rng(7)
    # 星星
    for i in range(70):
        x, y = rng.integers(0, w), rng.integers(0, int(h * 0.55))
        tw = 0.5 + 0.5 * math.sin(t * rng.uniform(1, 3) + i)
        if tw > 0.35:
            v = int(150 + 100 * tw)
            img[y, x, :3] = (v, v, min(255, v + 20))
    # 月亮（滿月＋光暈）
    mx, my, mr = int(w * 0.72), int(h * 0.2), 9
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.hypot(xx - mx, yy - my)
    halo = (rr < mr + 7) & (rr >= mr)
    dith = _BAYER[yy % 4, xx % 4]
    img[halo & (dith < 0.5 - (rr - mr) / 16), :3] = (40, 42, 70)
    moon = rr < mr
    img[moon, :3] = (226, 228, 214)
    img[moon & (np.hypot(xx - mx - 3, yy - my + 2) < 2.5), :3] = (204, 206, 194)
    img[moon & (np.hypot(xx - mx + 3, yy - my - 3) < 1.8), :3] = (208, 210, 198)
    # 遠山（深紫灰）與近山（純黑）：中間低的 V 形山谷
    xs = np.arange(w)
    far = h * 0.52 + 10 * np.cos(xs / w * math.pi * 2) + 3 * np.sin(xs * 0.31) + 2 * np.sin(xs * 0.83)
    near_l = h * 0.38 + xs * 0.55 + 2 * np.sin(xs * 0.5)
    near_r = h * 0.38 + (w - xs) * 0.55 + 2 * np.sin(xs * 0.45 + 1)
    near = np.minimum(near_l, near_r)
    for x in range(w):
        img[int(far[x]):, x, :3] = (22, 19, 34)
        img[int(far[x]), x, :3] = (40, 36, 60)  # 遠山稜線
        ny = max(int(near[x]), 0)
        img[ny:, x, :3] = (8, 8, 12)
        if ny < h:
            img[ny, x, :3] = (52, 50, 78)  # 近山被月光照亮的稜線
            if ny + 1 < h and x % 3:
                img[ny + 1, x, :3] = (26, 26, 40)
    # 山谷底（黑色草地）
    floor_y = int(h * 0.74)
    img[floor_y:, :, :3] = (6, 6, 10)
    for x in range(0, w, 2):
        gh = rng.integers(1, 3)
        img[floor_y - gh:floor_y, x, :3] = (12, 14, 18)
    # 薄霧
    mist = (yy > floor_y - 6) & (yy < floor_y + 2) & (dith < 0.18 + 0.08 * math.sin(t * 0.7))
    img[mist, :3] = np.minimum(img[mist, :3].astype(int) + 22, 255).astype(np.uint8)
    # 月光花：遠處小點、山坡上小花、近處大花
    def flower_dot(x, y, size, glow):
        g = int(150 + 105 * glow)
        if size == 1:
            if 0 <= y < h and 0 <= x < w:
                img[y, x, :3] = (g, g, min(255, g + 10))
        else:
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                X, Y = x + dx, y + dy
                if 0 <= X < w and 0 <= Y < h:
                    img[Y, X, :3] = (238, 240, 232) if (dx, dy) != (0, 0) else (214, 226, 150)

    frng = np.random.default_rng(11)
    for i in range(160):  # 山坡與谷底的小花
        x = int(frng.integers(0, w))
        top = int(min(near[x], h - 1)) + 2
        if top >= h - 1:
            continue
        y = int(frng.integers(top, h))
        size = 1 if y < floor_y else 3
        flower_dot(x, y, size, 0.5 + 0.5 * math.sin(t * 1.5 + i))
    # 螢光花粉
    for i in range(18):
        px = (frng.uniform(0, w) + t * frng.uniform(1, 4)) % w
        py = floor_y - 4 - ((t * frng.uniform(2, 5) + i * 7) % 30)
        if 0 <= int(py) < h and (int(t * 3 + i) % 4):
            img[int(py), int(px), :3] = (230, 255, 220)
    out = Image.fromarray(img)
    # 近景大朵月光花（會發光）
    for i, fx in enumerate((12, 40, w - 40, w - 12)):
        fl = draw_moonflower(4, int(round(math.sin(t * 1.2 + i) * 1.2)), 0.75 + 0.25 * math.sin(t * 2 + i))
        out.alpha_composite(fl, (fx - FLOWER_W // 2, h - FLOWER_H + 6))
    return out


# ------------------------------------------------------------------ 背景：夢幻甜點屋
def draw_sweets(t: float, w=240, h=150) -> Image.Image:
    """夢幻甜點屋：藍綠天空＋檸檬黃雲與糖粒；黃沙草地＋藍綠糖霜；
    檸檬起司小屋（藍綠糖霜屋頂、檸檬頂飾、藍黃拐杖糖煙囪、發光圓窗、藍綠門）。"""
    yy, xx = np.mgrid[0:h, 0:w]
    dith = _BAYER[yy % 4, xx % 4]
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = _dither_gradient(h, w, (96, 196, 196), (255, 236, 150), 8)  # 上藍綠、下檸檬黃
    img[..., 3] = 255
    floor_y = int(h * 0.8)
    line = (28, 92, 96)

    def put(x, y, c):
        if 0 <= x < w and 0 <= y < h:
            img[int(y), int(x), :3] = c

    # 閃閃的小星星（偏黃白）
    rng = np.random.default_rng(21)
    for i in range(40):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, floor_y - 20))
        if (math.sin(t * rng.uniform(1, 3) + i)) > 0.2:
            put(x, y, (255, 250, 210) if i % 3 else (255, 255, 255))
    # 地面：檸檬沙＋藍綠糖霜往下滴＋深色糖豆
    img[floor_y:, :, :3] = (236, 196, 110)
    img[(yy >= floor_y) & (dith < 0.2), :3] = (214, 170, 86)
    for x in range(w):
        drip = 3 + int(2 + 2 * math.sin(x * 0.45) + (3 if (x * 7) % 23 < 4 else 0))
        img[floor_y - 1:floor_y + drip, x, :3] = (96, 210, 196)
        img[floor_y + drip, x, :3] = (52, 168, 160)
        img[floor_y - 1, x, :3] = (186, 246, 232)
    for _ in range(30):
        x, y = int(rng.integers(0, w)), int(rng.integers(floor_y + 8, h))
        put(x, y, (70, 120, 110))
        put(x + 1, y, (70, 120, 110))
    out = Image.fromarray(img)
    d = ImageDraw.Draw(out)
    # 檸檬棉花糖雲（白＋淡黃）
    for i, (cx, cy) in enumerate(((30, 22), (110, 14), (200, 30), (160, 52))):
        cx = (cx + t * (2 + i)) % (w + 40) - 20
        for k, (dx, dy, r) in enumerate(((-9, 2, 6), (0, 0, 8), (9, 2, 6), (4, 4, 5))):
            col = (255, 255, 250, 255) if k != 3 else (255, 246, 190, 255)
            d.ellipse((cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r), fill=col)
    # 遠景的薄荷奶油山丘
    for x in range(w):
        hy = floor_y - 10 - 6 * math.sin(x / w * math.pi * 2 + 1) - 3 * math.sin(x * 0.11)
        d.line([(x, hy), (x, floor_y - 2)], fill=(186, 236, 220, 255))
        d.point((x, hy), fill=(230, 252, 240, 255))
    # ---- 檸檬起司小屋（右邊）
    hx, hw = int(w * 0.58), 70
    hb = floor_y + 2
    ht = hb - 40
    layers = [(255, 236, 150), (255, 250, 220), (255, 226, 120), (255, 250, 220), (255, 236, 150)]
    lh = (hb - ht) // len(layers)
    for i, c in enumerate(layers):
        d.rectangle((hx, ht + i * lh, hx + hw - 1, ht + (i + 1) * lh), fill=c + (255,))
    d.rectangle((hx, ht, hx + hw - 1, hb), outline=line + (255,))
    for x in range(hx + 2, hx + hw - 2, 6):  # 檸檬皮孔
        d.point((x, ht + lh // 2), fill=(210, 180, 70, 255))
        d.point((x + 3, ht + lh * 2 + lh // 2), fill=(210, 180, 70, 255))
    # 屋頂：藍綠糖霜（往下滴）＋鮮奶油＋檸檬
    rt = ht - 20
    d.polygon([(hx - 8, ht + 1), (hx + hw // 2, rt), (hx + hw + 7, ht + 1)], fill=(52, 170, 160, 255), outline=line + (255,))
    for x in range(hx - 6, hx + hw + 6):
        drip = 2 + int(2 + 2 * math.sin(x * 0.7))
        d.line([(x, ht), (x, ht + drip)], fill=(52, 170, 160, 255))
    for k in range(6):  # 屋簷的鮮奶油球
        cx_ = hx - 4 + k * (hw + 8) // 5
        d.ellipse((cx_ - 3, ht - 3, cx_ + 3, ht + 2), fill=(255, 252, 236, 255), outline=(210, 200, 150, 255))
    for k, (cx_, cy_) in enumerate(((hx + hw // 2, rt - 2), (hx + hw // 2 - 12, rt + 8), (hx + hw // 2 + 12, rt + 8))):
        d.ellipse((cx_ - 3, cy_ - 3, cx_ + 3, cy_ + 3), fill=(255, 226, 90, 255), outline=line + (255,))
        d.point((cx_ - 1, cy_ - 1), fill=(255, 250, 200, 255))
        d.line([(cx_, cy_ - 3), (cx_ + 2, cy_ - 7)], fill=(70, 160, 90, 255))
    # 藍黃拐杖糖煙囪（冒黃星星煙）
    cx0 = hx + hw - 16
    for y in range(rt + 2, ht - 2):
        stripe = (52, 170, 160) if ((y // 3) % 2) else (255, 236, 120)
        d.line([(cx0, y), (cx0 + 5, y)], fill=stripe + (255,))
    d.rectangle((cx0, rt + 2, cx0 + 5, ht - 2), outline=line + (255,))
    # 檸檬餅乾圓窗（會發光）
    glow = 0.75 + 0.25 * math.sin(t * 1.8)
    win_c = tuple(int(c * glow + 200 * (1 - glow)) for c in (255, 246, 160)) + (255,)
    for wx in (hx + 13, hx + hw - 14):
        wy = ht + 13
        d.ellipse((wx - 7, wy - 7, wx + 7, wy + 7), fill=(210, 180, 90, 255), outline=line + (255,))
        d.ellipse((wx - 5, wy - 5, wx + 5, wy + 5), fill=win_c)
        d.line([(wx, wy - 5), (wx, wy + 5)], fill=(180, 150, 70, 255))
        d.line([(wx - 5, wy), (wx + 5, wy)], fill=(180, 150, 70, 255))
        for dx_, dy_ in ((-6, -2), (5, 3), (-2, 6)):
            d.point((wx + dx_, wy + dy_), fill=(90, 140, 130, 255))
    # 藍綠糖霜門
    dx0, dw = hx + hw // 2 - 8, 16
    d.rounded_rectangle((dx0, hb - 22, dx0 + dw, hb), radius=6, fill=(40, 140, 132, 255), outline=line + (255,))
    for gy in range(hb - 16, hb, 6):
        d.line([(dx0 + 2, gy), (dx0 + dw - 2, gy)], fill=(70, 180, 170, 255))
    d.line([(dx0 + dw // 2, hb - 19), (dx0 + dw // 2, hb)], fill=(70, 180, 170, 255))
    d.point((dx0 + dw - 4, hb - 9), fill=(255, 226, 100, 255))
    # 門口的藍黃馬卡龍台階
    for k, col in enumerate(((255, 226, 120), (96, 210, 196), (255, 246, 170))):
        mx = dx0 - 10 + k * 18
        d.rounded_rectangle((mx, hb - 1, mx + 9, hb + 4), radius=2, fill=col + (255,), outline=line + (255,))
        d.line([(mx + 1, hb + 1), (mx + 8, hb + 1)], fill=(255, 252, 230, 255))
    # 棒棒糖樹（藍綠／檸檬黃）
    for i, (bx, hh, c1, c2) in enumerate(((18, 46, (52, 186, 176), (255, 246, 170)),
                                          (52, 34, (255, 226, 100), (96, 210, 196)),
                                          (int(w * 0.48), 28, (120, 214, 200), (255, 236, 120)))):
        top = floor_y - hh
        d.line([(bx, top), (bx, floor_y)], fill=(255, 250, 220, 255), width=2)
        r = 9 if i == 0 else 7
        d.ellipse((bx - r, top - r, bx + r, top + r), fill=c1 + (255,), outline=line + (255,))
        rot = t * 0.8 + i
        for k in range(28):  # 漩渦
            ang = rot + k * 0.45
            rr = r * k / 28
            d.point((bx + math.cos(ang) * rr, top + math.sin(ang) * rr), fill=c2 + (255,))
    # 藍黃拐杖糖、軟糖
    for cx_ in (76, int(w * 0.95)):
        for y in range(floor_y - 22, floor_y):
            stripe = (52, 170, 160) if ((y // 3) % 2) else (255, 236, 120)
            d.point((cx_, y), fill=stripe + (255,))
            d.point((cx_ + 1, y), fill=stripe + (255,))
        d.arc((cx_ - 5, floor_y - 27, cx_ + 2, floor_y - 19), 180, 360, fill=(52, 170, 160, 255), width=2)
    for k, col in enumerate(((96, 210, 196), (255, 226, 100), (150, 230, 210), (255, 246, 160))):
        gx = 90 + k * 9
        d.pieslice((gx - 4, floor_y - 6, gx + 4, floor_y + 2), 180, 360, fill=col + (255,), outline=line + (255,))
        d.point((gx - 1, floor_y - 4), fill=(255, 255, 255, 255))
    # 飄落的藍黃糖粒、煙囪冒出的小星星
    cols = [(52, 186, 176), (255, 226, 100), (120, 214, 200), (255, 246, 160), (70, 160, 150)]
    for i in range(26):
        x = (i * 37 + math.sin(t + i) * 6) % w
        y = (t * (8 + i % 5 * 3) + i * 23) % (floor_y - 2)
        c = cols[i % len(cols)] + (255,)
        if i % 2:
            d.line([(x, y), (x + 1, y + 1)], fill=c)
        else:
            d.line([(x, y + 1), (x + 1, y)], fill=c)
    for i in range(4):
        prog = (t * 7 + i * 9) % 34
        hx_, hy_ = cx0 + 3 + math.sin(t * 2 + i) * 2 + prog * 0.15, rt - 2 - prog
        c = (255, 236, 120, 255)
        for dx_, dy_ in ((0, -1), (-1, 0), (1, 0), (0, 1), (0, 0)):
            d.point((hx_ + dx_, hy_ + dy_), fill=c)
    return out


# ------------------------------------------------------------------ 背景：湖水綠的湖底夢幻小屋
def draw_lake(t: float, w=240, h=150) -> Image.Image:
    """湖底小屋：湖水綠的水、水面灑下的光、水草、珊瑚、小魚、往上飄的泡泡，和一間會發光的夢幻小屋。"""
    yy, xx = np.mgrid[0:h, 0:w]
    dith = _BAYER[yy % 4, xx % 4]
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = _dither_gradient(h, w, (112, 222, 204), (14, 84, 92), 9)
    img[..., 3] = 255
    floor_y = int(h * 0.8)

    def put(x, y, c):
        if 0 <= x < w and 0 <= y < h:
            img[int(y), int(x), :3] = c

    # 水面：亮的波紋線＋閃爍的光點
    for x in range(w):
        wy = max(0, int(2 + 1.5 * math.sin(x * 0.18 + t * 1.6) + math.sin(x * 0.07 - t * 0.9)))
        img[wy, x, :3] = (206, 252, 240)
        if (x + int(t * 6)) % 7 == 0:
            put(x, wy + 2, (176, 244, 228))
    # 光束：斜斜的、會慢慢擺動，用網點做半透明
    for i, bx in enumerate((30, 78, 132, 190)):
        sway = 6 * math.sin(t * 0.5 + i)
        lx = bx + sway + yy * 0.35
        band = (np.abs(xx - lx) < 5 + (i % 2) * 3) & (yy < floor_y) & (dith < 0.22 - yy / h * 0.18)
        img[band, :3] = np.minimum(img[band, :3].astype(int) + 26, 255).astype(np.uint8)
    # 遠景的岩石剪影
    xs = np.arange(w)
    far = floor_y - 14 - 8 * np.abs(np.sin(xs / w * 3.1 + 0.6)) - 3 * np.sin(xs * 0.21)
    for x in range(w):
        img[int(far[x]):floor_y, x, :3] = (30, 112, 112)
        img[int(far[x]), x, :3] = (44, 134, 128)
    # 湖底的沙
    img[floor_y:, :, :3] = (126, 170, 152)
    sand = (yy >= floor_y) & (dith < 0.25)
    img[sand, :3] = (108, 152, 136)
    img[floor_y, :, :3] = (150, 196, 176)
    rng = np.random.default_rng(3)
    for _ in range(40):  # 小石頭、貝殼
        x, y = int(rng.integers(0, w)), int(rng.integers(floor_y + 2, h))
        c = [(92, 132, 120), (232, 206, 214), (210, 232, 222)][int(rng.integers(0, 3))]
        put(x, y, c)
        put(x + 1, y, c)
    # 水底光斑（波光）
    for i in range(24):
        cx = (rng.uniform(0, w) + t * 4 * (1 if i % 2 else -1)) % w
        cy = floor_y + 2 + (i * 7) % max(h - floor_y - 3, 1)
        if (int(t * 2 + i) % 3) != 0:
            put(cx, cy, (190, 236, 214))
            put(cx + 1, cy, (190, 236, 214))
    # ---- 夢幻小屋（右邊）
    hx, hw, hb = int(w * 0.6), 64, floor_y + 2  # 左緣、寬、底
    ht = hb - 36  # 牆頂
    wall, wall_d, line = (214, 244, 232), (178, 222, 208), (34, 82, 84)
    for y in range(ht, hb):
        for x in range(hx, hx + hw):
            img[y, x, :3] = wall_d if ((y - ht) % 6 == 5 or dith[y, x] < 0.12) else wall
    img[ht:hb, hx, :3] = line
    img[ht:hb, hx + hw - 1, :3] = line
    # 屋頂：圓弧形、扇貝狀的瓦片
    roof_c, roof_l, roof_d = (52, 170, 156), (96, 206, 188), (30, 120, 116)
    for y in range(ht - 22, ht + 3):
        k = (y - (ht - 22)) / 25
        half = int((hw / 2 + 6) * math.sqrt(max(0.0, 1 - (1 - k) ** 2)))
        x0, x1 = hx + hw // 2 - half, hx + hw // 2 + half
        if x1 <= x0:
            continue
        img[y, x0:x1, :3] = roof_c
        for x in range(x0, x1):
            if (y - ht) % 5 == 0 and (x - x0) % 6 in (0, 5):
                img[y, x, :3] = roof_d
            elif (y - ht) % 5 == 1 and (x - x0) % 6 in (2, 3):
                img[y, x, :3] = roof_l
        img[y, x0, :3] = line
        img[y, x1 - 1, :3] = line
    img[ht - 22, hx + hw // 2 - 4:hx + hw // 2 + 4, :3] = line
    img[ht + 3, hx - 6:hx + hw + 6, :3] = line
    # 屋頂上的小狸貓耳朵風向標
    vx = hx + hw // 2
    for y in range(ht - 30, ht - 22):
        put(vx, y, line)
    for dx, dy in ((-3, -32), (-2, -33), (-2, -32), (2, -33), (2, -32), (3, -32), (-1, -31), (0, -31), (1, -31),
                   (-2, -31), (2, -31), (-1, -30), (0, -30), (1, -30)):
        put(vx + dx, ht + dy, (186, 140, 100))
    put(vx - 2, ht - 32, (110, 70, 56))
    put(vx + 2, ht - 32, (110, 70, 56))
    # 煙囪（冒泡泡）
    cx0 = hx + hw - 18
    img[ht - 26:ht - 12, cx0:cx0 + 7, :3] = (196, 150, 160)
    img[ht - 26:ht - 12, cx0, :3] = line
    img[ht - 26:ht - 12, cx0 + 6, :3] = line
    img[ht - 27, cx0 - 1:cx0 + 8, :3] = line
    # 圓窗（會發光）
    glow = 0.75 + 0.25 * math.sin(t * 1.8)
    win_c = tuple(int(c * glow + 60 * (1 - glow)) for c in (255, 236, 160))
    for wx in (hx + 12, hx + hw - 14):
        wy = ht + 12
        rr = np.hypot(xx - wx, yy - wy)
        img[(rr < 7) & (rr >= 5.2), :3] = line
        img[rr < 5.2, :3] = win_c
        img[(rr < 5.2) & ((np.abs(xx - wx) < 0.6) | (np.abs(yy - wy) < 0.6)), :3] = (150, 120, 90)
        halo = (rr >= 7) & (rr < 10) & (dith < 0.3)
        img[halo, :3] = np.minimum(img[halo, :3].astype(int) + 30, 255).astype(np.uint8)
    # 拱門
    dx0, dw = hx + hw // 2 - 7, 14
    cxm = dx0 + dw // 2
    for y in range(hb - 20, hb):
        k = (y - (hb - 20)) / 6
        half = dw // 2 if k >= 1 else int(dw / 2 * math.sqrt(max(0.0, 1 - (1 - k) ** 2)))
        if half:
            img[y, cxm - half:cxm + half, :3] = (120, 86, 92)
            img[y, cxm - half, :3] = line
            img[y, cxm + half - 1, :3] = line
    put(dx0 + dw - 4, hb - 9, (255, 226, 140))
    # 門口的小燈籠
    lx, ly = dx0 - 6, hb - 22
    put(lx, ly - 1, line)
    for dy in range(0, 5):
        for dxx in (-1, 0, 1):
            put(lx + dxx, ly + dy, win_c if dy < 4 else line)
    # 門前的貝殼小路
    for k in range(5):
        put(dx0 + 4 + (k % 2) * 4, hb + 1 + k * 2, (236, 214, 222))
        put(dx0 + 5 + (k % 2) * 4, hb + 1 + k * 2, (236, 214, 222))
    out = Image.fromarray(img)
    d = ImageDraw.Draw(out)
    # 水草（會擺動）
    for i, (bx, n, hh) in enumerate(((10, 4, 46), (36, 3, 30), (int(w * 0.52), 3, 26), (w - 8, 3, 40))):
        for j in range(n):
            x0 = bx + j * 4
            pts = []
            for k in range(0, hh, 2):
                sw = math.sin(t * 1.4 + i + j * 0.7 + k * 0.12) * (k / hh) * 4
                pts.append((x0 + sw, floor_y + 1 - k))
            d.line(pts, fill=(52, 156, 112, 255) if j % 2 else (82, 184, 128, 255), width=2)
    # 珊瑚
    for cx, col in ((60, (250, 160, 176, 255)), (int(w * 0.55) - 14, (250, 196, 140, 255))):
        d.line([(cx, floor_y + 1), (cx, floor_y - 9)], fill=col, width=2)
        d.line([(cx, floor_y - 5), (cx - 4, floor_y - 10)], fill=col, width=2)
        d.line([(cx, floor_y - 3), (cx + 4, floor_y - 8)], fill=col, width=2)
    # 小魚
    for i in range(4):
        sp = 10 + i * 4
        direction = 1 if i % 2 == 0 else -1
        fx = (t * sp * direction + i * 70) % (w + 20) - 10
        fy = 26 + i * 15 + 3 * math.sin(t * 1.3 + i)
        col = [(250, 214, 120, 255), (250, 160, 190, 255), (200, 236, 250, 255), (250, 190, 140, 255)][i]
        d.ellipse((fx - 3, fy - 2, fx + 3, fy + 2), fill=col)
        tx = fx - 4 * direction
        d.polygon([(tx, fy), (tx - 3 * direction, fy - 2), (tx - 3 * direction, fy + 2)], fill=col)
        d.point((fx + 1.5 * direction, fy - 0.5), fill=(30, 50, 60, 255))
    # 往上飄的泡泡（煙囪冒出來的＋湖底冒出來的）
    for i in range(14):
        if i < 5:
            bx0, by0 = cx0 + 3, ht - 28
        else:
            bx0, by0 = (i * 37) % w, floor_y
        prog = (t * (6 + i % 4 * 2) + i * 11) % (by0 + 4)
        by = by0 - prog
        bx = bx0 + math.sin(t * 2 + i) * 2 + (prog * 0.05 if i < 5 else 0)
        r = 1 if i % 3 else 2
        d.ellipse((bx - r, by - r, bx + r, by + r), outline=(214, 252, 244, 255))
        d.point((bx - r * 0.4, by - r * 0.4), fill=(255, 255, 255, 255))
    return out


# ------------------------------------------------------------------ 花仙的白色半透明翅膀
WING_ROOT_ROW = 33  # 正面／背面：翅膀根部在 64 格中的列（肩胛骨）
WING_ALPHA = 145


def make_fairy_wing():
    """單邊翅膀（往右長）：上大下小兩片、白色半透明、淡紫邊與翅脈。回傳 (RGBA 陣列, 根部所在列)。"""
    W, H, root = 32, 36, 22
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    ly = yy - root

    def ell(cx, cy, rx, ry, ang):
        t = math.radians(ang)
        c, sn = math.cos(t), math.sin(t)
        dx, dy = xx - cx, ly - cy
        u = (dx * c + dy * sn) / rx
        v = (-dx * sn + dy * c) / ry
        return u * u + v * v <= 1.0

    upper = ell(16, -9, 15, 8.5, -28)
    lower = ell(11, 6, 9, 5.5, 25)
    stem = (xx < 4) & (np.abs(ly) < 2.5)
    m = upper | lower | stem
    inner = m.copy()
    inner[1:] &= m[:-1]
    inner[:-1] &= m[1:]
    inner[:, 1:] &= m[:, :-1]
    inner[:, :-1] &= m[:, 1:]
    edge = m & ~inner
    a = np.zeros((H, W, 4), np.uint8)
    a[m] = (246, 248, 255, WING_ALPHA)
    # 翅脈：從根部放射出去
    for tx, ty in ((28, -16), (22, -3), (17, 10), (10, -16), (6, 9)):
        n = int(max(abs(tx), abs(ty))) * 2
        for i in range(n + 1):
            x = int(round(1 + (tx - 1) * i / n))
            y = int(round(root + ty * i / n))
            if 0 <= x < W and 0 <= y < H and m[y, x]:
                a[y, x] = (232, 236, 255, 185)
    a[edge] = (188, 192, 232, 225)
    # 上翅外緣幾點亮光
    for x, y in ((24, root - 15), (27, root - 11), (14, root + 9)):
        if m[y, x]:
            a[y, x] = (255, 255, 255, 235)
    return a, root


# ------------------------------------------------------------------ 小遊戲（Python 版：接星星；泡泡射擊是 Unity 版）
def make_small_sprites(outfit: "S.Outfit"):
    """小遊戲用的 32 格角色（正面／左／右），直接從原圖點陣化；Chico 沒有翅膀（給一張透明圖）。"""
    out = {k: Image.fromarray(outfit.small(k, 32)) for k in ("front", "left", "right")}
    out["wing"] = (Image.new("RGBA", (1, 1), (0, 0, 0, 0)), 0)
    return out


class StarCatchGame:
    """接點心（Python 備用版）：左右移動接住落下的點心。無生命、無星星；漏接不算輸。"""

    W, H = 180, 270
    SPEED = 115.0
    TITLE = "接點心（Python 備用版）"
    HELP = "← → / A D 或滑鼠左右移動・接住點心（無生命）"
    SAVE_KEY = "best_stars"
    SNACK_KINDS = ("lollipop", "cookie", "cake", "donut", "candy", "macaron")

    def __init__(self, sprites, best=0):
        self.spr = sprites
        self.best = best
        self.mouse = None
        self.reset()

    @property
    def meters(self):
        return self.score

    def reset(self):
        self.floor = self.H - 22
        self.x = self.W / 2
        self.vx = 0.0
        self.face = 0
        self.objs = []
        self.fx = []
        self.score = 0
        self.t = 0.0
        self.spawn_t = 0.6
        self.state = "play"
        self.just_over = False
        self.reached = False
        self.squash = 0.0
        self.hurt = 0.0

    def click(self):
        pass

    def level(self):
        return min(1.0, self.t / 90.0)

    def step(self, dt, dx):
        self.t += dt
        self.just_over = False
        self.squash = max(0.0, self.squash - dt * 4)
        self.hurt = max(0.0, self.hurt - dt)
        for f in self.fx:
            f[0] += f[2] * dt
            f[1] += f[3] * dt
            f[3] += 60 * dt
            f[4] -= dt
        self.fx = [f for f in self.fx if f[4] > 0]
        if dx:
            self.vx = dx * self.SPEED
        elif self.mouse is not None:
            self.vx = max(-self.SPEED, min(self.SPEED, (self.mouse - self.x) * 6))
        else:
            self.vx *= 0.8
        self.face = (1 if self.vx > 0 else -1) if abs(self.vx) > 14 else 0
        self.x = min(max(self.x + self.vx * dt, 10), self.W - 10)
        lv = self.level()
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = random.uniform(0.9, 1.3) * (1 - 0.6 * lv)
            kind = random.choice(self.SNACK_KINDS)
            sp = random.uniform(55, 75) + 90 * lv
            self.objs.append(dict(x=random.uniform(10, self.W - 10), y=-8.0, vy=sp, kind=kind,
                                  vx=0.0, ph=random.uniform(0, 6)))
        keep = []
        top = self.floor - 30
        for o in self.objs:
            o["y"] += o["vy"] * dt
            o["x"] = min(max(o["x"] + o["vx"] * dt, 6), self.W - 6)
            if top <= o["y"] <= self.floor and abs(o["x"] - self.x) < 13:
                self.score += 1
                self.squash = 1.0
                self.burst(o["x"], o["y"], "spark")
                self.best = max(self.best, self.score)
                continue
            if o["y"] > self.floor + 4:
                continue  # 漏接：不扣生命
            keep.append(o)
        self.objs = keep

    def burst(self, x, y, kind):
        for _ in range(6):
            a = random.uniform(0, math.tau)
            self.fx.append([x, y, math.cos(a) * 35, math.sin(a) * 35 - 20, 0.5, kind])

    def render(self):
        W, H = self.W, self.H
        img = np.zeros((H, W, 4), np.uint8)
        img[..., :3] = _dither_gradient(H, W, (96, 196, 196), (255, 236, 150), 8)
        img[..., 3] = 255
        out = Image.fromarray(img)
        d = ImageDraw.Draw(out)
        # 地面
        d.rectangle((0, self.floor, W, H), fill=(96, 210, 196, 255))
        d.line((0, self.floor, W, self.floor), fill=(255, 246, 170, 255))
        # 落下的點心
        for o in self.objs:
            x, y = int(o["x"]), int(o["y"])
            c = Image.fromarray(S.snack(o["kind"]))
            out.paste(c, (x - c.width // 2, y - c.height // 2), c)
        for f in self.fx:
            if 0 <= int(f[0]) < W and 0 <= int(f[1]) < H:
                out.putpixel((int(f[0]), int(f[1])), (255, 246, 170, 255))
        # 她
        key = "front" if self.face == 0 else ("right" if self.face > 0 else "left")
        body = self.spr[key]
        sq = self.squash
        bh = max(1, int(body.height * (1 - 0.15 * sq)))
        bimg = body.resize((int(body.width * (1 + 0.1 * sq)), bh), Image.NEAREST)
        px, py = int(round(self.x)) - bimg.width // 2, self.floor - bh + 1
        if not (self.hurt > 0 and int(self.hurt * 12) % 2):
            out.paste(bimg, (px, py), bimg)
        # HUD（無生命、無星星）
        d = ImageDraw.Draw(out)
        d.fontmode = "1"
        font = pixel_font(11)
        d.rectangle((2, 2, 78, 30), fill=(255, 249, 224, 255), outline=(58, 168, 154, 255))
        d.text((5, 3), f"點心 {self.score}", font=font, fill=(31, 95, 90, 255))
        d.text((5, 16), f"最佳 {self.best}", font=font, fill=(31, 95, 90, 255))
        return out


# ------------------------------------------------------------------ 換裝
# Chico 的衣服是各自畫好的 PSD（preview/dress_psd、preview/sailor_psd），名稱 → sprites.py 的 key
OUTFITS = {"洋裝": "dress", "水手服": "sailor"}
DEFAULT_OUTFIT = "洋裝"
SLEEVES = {  # 捧東西時袖子的顏色（袖子, 袖口）
    "dress": ((226, 246, 238, 255), (44, 52, 52, 255)),
    "sailor": ((246, 250, 248, 255), (96, 182, 150, 255)),
}


def sleeve_colors(name: str):
    return SLEEVES.get(OUTFITS.get(name, "dress"), SLEEVES["dress"])


# ------------------------------------------------------------------ 玩具與音符（點陣）
TANUKI_H = S.HELD_H  # 小狸貓（抱著、放著、丟出去都一樣大）


def tanuki_img(view="front") -> Image.Image:
    return Image.fromarray(S.tanuki(view, TANUKI_H))


PLUSH = tanuki_img("front")
_TOY_IMGS: dict = {}


def toy_img(view):
    if view not in _TOY_IMGS:
        _TOY_IMGS[view] = tanuki_img(view)
    return _TOY_IMGS[view]

NOTE_COLORS = {"n": (236, 230, 255, 255), "o": (150, 140, 196, 255)}
PARTICLES["note"] = _pix([
    "..oooo",
    "..onno",
    "..on.o",
    "..on..",
    "oonn..",
    "onnn..",
    ".oo...",
], NOTE_COLORS)
PARTICLES["note2"] = _pix([
    "...oo.",
    "...ono",
    "...on.",
    "...on.",
    ".oonn.",
    "onnnn.",
    ".ooo..",
], NOTE_COLORS)

# ------------------------------------------------------------------ 音樂（程式合成的原創曲子）
SAMPLE_RATE = 22050


def _freq(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _synth_tone(m, dur, kind):
    n = int(SAMPLE_RATE * dur)
    t = np.arange(n) / SAMPLE_RATE
    f = _freq(m)
    if kind == "harp":  # 撥弦：泛音快速衰減
        w = np.sin(2 * np.pi * f * t) + 0.45 * np.sin(4 * np.pi * f * t) + 0.18 * np.sin(6 * np.pi * f * t)
        env = np.exp(-t * 3.0)
    elif kind == "pluck":  # 輕快的撥奏（柔和的方波）
        w = np.tanh(2.5 * np.sin(2 * np.pi * f * t)) * 0.6 + 0.25 * np.sin(4 * np.pi * f * t)
        env = np.exp(-t * 6.0)
    elif kind == "pop":  # 泡泡「啵」：音高往下滑的短音
        ph = 2 * np.pi * f * (t + 0.04 * (1 - np.exp(-t / 0.04)))
        w = np.sin(ph)
        env = np.exp(-t * 28.0)
    elif kind == "box":  # 音樂盒：清脆的高泛音
        w = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 4 * t)
        env = np.exp(-t * 4.0)
    else:  # bass
        w = np.sin(2 * np.pi * f * t) + 0.2 * np.sin(4 * np.pi * f * t)
        env = np.exp(-t * 2.5)
    att = np.minimum(1.0, t / 0.006)
    return w * env * att


def render_tune(events, bpm, length_beats):
    """events: (拍, midi, 長度拍, 音色, 音量)。回傳 16-bit PCM bytes 與每個音的開始秒數。"""
    sec = 60.0 / bpm
    total = int(SAMPLE_RATE * (length_beats * sec + 1.5))
    buf = np.zeros(total)
    for beat, m, dur, kind, vol in events:
        st = int(SAMPLE_RATE * beat * sec)
        tone = _synth_tone(m, max(dur * sec, 0.6) + 0.8, kind) * vol
        end = min(total, st + tone.size)
        buf[st:end] += tone[:end - st]
    buf = buf / max(1e-6, np.abs(buf).max()) * 0.55
    return (buf * 32767).astype(np.int16).tobytes(), sorted({b * sec for b, *_ in events})


DANCE_BPM = 132


def dance_tune():
    """草莓糖霜波卡（原創，F 大調，4/4 拍，132 BPM）：輕快的撥奏旋律＋跳躍的低音＋糖果「啵」聲。"""
    R_ = None
    mel = [  # 每小節 8 個八分音符（None = 休止）
        (72, R_, 69, 72, 77, 76, 74, 72),  # F
        (74, R_, 72, 69, 65, 67, 69, R_),  # Dm
        (70, 74, 77, 74, 70, 74, 77, 79),  # Bb
        (76, R_, 79, 76, 72, R_, 74, 76),  # C
        (77, R_, 81, 77, 72, 74, 77, R_),  # F
        (76, 72, 69, 72, 76, 79, 81, 79),  # Am
        (77, 74, 70, 74, 77, 74, 79, 77),  # Bb
        (76, 72, 79, 76, 77, R_, R_, R_),  # C → F
    ]
    bass = [(41, 48, 41, 48), (38, 45, 38, 45), (46, 41, 46, 41), (48, 43, 48, 43),
            (41, 48, 41, 48), (45, 40, 45, 40), (46, 41, 46, 41), (48, 43, 41, 41)]
    chord = [(65, 69, 72), (62, 65, 69), (62, 65, 70), (64, 67, 72), (65, 69, 72), (64, 69, 72), (62, 65, 70),
             (64, 67, 72)]
    ev = []
    for i in range(8):
        b0 = i * 4
        for k, m in enumerate(mel[i]):
            if m:
                ev.append((b0 + k * 0.5, m, 0.5, "pluck", 0.75))
        for k, m in enumerate(bass[i]):
            ev.append((b0 + k, m, 1, "bass", 0.55))
        for k in (1, 3):  # 反拍的和弦
            for m in chord[i]:
                ev.append((b0 + k + 0.5, m, 0.5, "box", 0.16))
        for k in (0.5, 1.5, 2.5, 3.5):  # 泡泡聲
            ev.append((b0 + k, 96 + (i + int(k)) % 3 * 2, 0.25, "pop", 0.22))
    return render_tune(ev, DANCE_BPM, 32)


DANCE_TUNE = dance_tune()


# ------------------------------------------------------------------ 玩具（可以拖、會彈、會滾）
class Toy:
    def __init__(self, kind, x, y):
        self.kind = kind  # 目前只有 "plush"（小狸貓）
        self.x, self.y = x, y  # 底部中央（螢幕座標）
        self.vx = self.vy = 0.0
        self.angle = 0.0  # 轉圈（8 個視角，單位：45 度）
        self.spin = 0.0  # 每秒轉幾格
        self.held = False  # 被滑鼠拿著
        self.carried = False  # 被她抱著
        self.size = (PLUSH.width, PLUSH.height)

    def view(self):
        return S.SPIN_ORDER[int(round(self.angle)) % 8]

    def image(self):
        return toy_img(self.view())

    def grounded(self, floor):
        return self.y >= floor - 1 and abs(self.vy) < 1

    def step(self, dt, work, g):
        if self.held or self.carried:
            self.vx = self.vy = 0.0
            return
        l, t, r, b = work
        hw = self.size[0] * SCALE / 2
        self.vy += g * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x < l + hw:
            self.x, self.vx = l + hw, abs(self.vx) * 0.7
        elif self.x > r - hw:
            self.x, self.vx = r - hw, -abs(self.vx) * 0.7
        if self.y - self.size[1] * SCALE < t:
            self.y, self.vy = t + self.size[1] * SCALE, abs(self.vy) * 0.5
        self.angle += self.spin * dt
        if self.y >= b:
            self.y = b
            rest = 0.3
            self.vy = -self.vy * rest if self.vy > 90 else 0.0
            self.vx *= max(0.0, 1 - 6.0 * dt)
            self.spin *= max(0.0, 1 - 8.0 * dt)
            if abs(self.vx) < 3:
                self.vx = 0.0
            if abs(self.spin) < 0.5:  # 停下來後慢慢轉回正面
                self.spin = 0.0
                target = round(self.angle / 8) * 8
                self.angle += (target - self.angle) * min(1.0, dt * 6)


class Rig:
    """8 張 64×64 點陣視圖 + 類 Live2D 參數變形（以整數像素位移，維持點陣風格）。

    物理與參數以「螢幕像素」計算；繪製在原生點陣解析度進行，最後以最近鄰整數倍放大。
    """

    def __init__(self, scale: float, outfit: "S.Outfit", sleeve=None):
        self.s = s = float(scale)
        self.outfit = outfit
        self.U = SRC * KN * s  # 一個「角色高度」單位（螢幕像素，約 130）
        self.C = (CANVAS / 2, PAD + (CENTER_Y - SRC_Y0) * KN)  # 原生畫布上的旋轉中心
        self.df = (FEET_Y - CENTER_Y) * KN * s
        self.dh = (CENTER_Y - HEAD_Y) * KN * s
        self.hw = 0.28 * self.U
        self.W = int(round(WIN_N * s))
        self.views: dict[tuple[str, bool], np.ndarray] = {}
        for key, cv in CHICO_VIEW.items():
            self.views[key] = self._canvas(outfit.full(cv))
        for key in ("front", "left", "right", "back", "top", "bottom"):  # 其餘鏡像（備用）
            self.views[(key, True)] = self.views[(key, False)][:, ::-1].copy()
        self.eye_cache: dict = {}
        yy, xx = np.mgrid[0:CANVAS, 0:CANVAS].astype(np.float64)
        self.yy, self.xx = yy.astype(np.int32), xx.astype(np.int32)
        src_y = (yy + 0.5 - PAD) / KN + SRC_Y0
        v = src_y / SRC
        u = (xx + 0.5 - CANVAS / 2) / KN / CROP_HALF
        au = np.abs(u)
        self.u = u
        self.w_lean = np.clip((0.93 - v) / 0.9, 0, 1)
        self.w_head = smoothstep(0.56, 0.4, v)
        self.w_hair = smoothstep(0.12, 0.45, au) * smoothstep(0.28, 0.5, v) * smoothstep(0.74, 0.6, v)
        self.w_skirt = smoothstep(0.6, 0.72, v) * smoothstep(0.84, 0.76, v)
        self.w_legs = smoothstep(0.76, 0.9, v)
        self.w_breath = smoothstep(0.8, 0.42, v)
        self.w_wing = smoothstep(0.14, 0.03, v) * smoothstep(0.1, 0.3, au)
        # 捧東西時的袖子（Chico 走路時袖子已經畫在身體上，不另外畫擺動的手臂）
        dress, frill = sleeve or SLEEVES["dress"]
        self.hold_hands = _pix(HOLD_PATTERN, {"o": OUTLINE, "#": dress, "F": frill})
        # 側面視圖：用 PSD 的「腿」圖層，走路時複製成前後兩隻腳交替擺動
        self.legs = {}
        for key in (("left", False), ("right", False), ("left", True), ("right", True)):
            cv = CHICO_VIEW.get((key[0], False))
            leg = self._canvas(outfit.part(cv, "legs"))
            base = self._canvas(outfit.part(cv, "upper"))
            if key[1]:
                leg, base = leg[:, ::-1].copy(), base[:, ::-1].copy()
            rows = np.nonzero((leg[..., 3] > 0).any(1))[0]
            top, bot = (int(rows.min()), int(rows.max())) if rows.size else (PAD + N - 20, PAD + N - 1)
            back = leg.copy()
            inner = (back[..., 3] > 0) & ~np.all(back[..., :3] == OUTLINE[:3], axis=-1)
            back[inner, :3] = (back[inner, :3] * 0.72).astype(np.uint8)
            facing = 1 if (key[0] == "right") != key[1] else -1
            self.legs[key] = (base, leg, back, top, bot, facing, (CANVAS // 2, PAD + SHOULDER_ROW))
        self.head_cut = PAD + NECK_ROW
        self.wing, self.wing_root = make_fairy_wing()

    @staticmethod
    def _canvas(a: np.ndarray) -> np.ndarray:
        c = np.zeros((CANVAS, CANVAS, 4), np.uint8)
        c[PAD:PAD + N, PAD:PAD + N] = a
        return c

    def eye_view(self, view, eyes, blink):
        """正面／斜側時眼睛往滑鼠方向看（整數點位移），或閉眼。"""
        cv = CHICO_VIEW.get(view)
        if cv is None or not self.outfit.has_eyes(cv):
            return self.views[view]
        ex, ey = eyes if cv in ("front", "fl", "fr") else (0, 0)
        key = (cv, ex, ey, bool(blink))
        if key not in self.eye_cache:
            self.eye_cache[key] = self._canvas(self.outfit.full(cv, ex, ey, bool(blink)))
        return self.eye_cache[key]

    @staticmethod
    def _pattern(rows, cols):
        h, w = len(rows), len(rows[0])
        a = np.zeros((h, w, 4), np.uint8)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch != ".":
                    a[y, x] = cols[ch]
        return a

    @staticmethod
    def _stamp_rotated(out, spr, pivot, angle):
        """把小圖以頂端中央為軸旋轉（最近鄰）後貼到 out 的 pivot 位置。"""
        h, w = spr.shape[:2]
        px, py = (w - 1) / 2, 0.5
        r = math.radians(angle)
        c, s = math.cos(r), math.sin(r)
        R = int(math.ceil(math.hypot(w, h))) + 1
        for oy in range(-2, R):
            for ox in range(-R, R + 1):
                # 反向旋轉找來源像素
                sxf = ox * c + oy * s + px
                syf = -ox * s + oy * c + py
                ix, iy = int(math.floor(sxf + 0.5)), int(math.floor(syf))
                if 0 <= ix < w and 0 <= iy < h and spr[iy, ix, 3]:
                    X, Y = pivot[0] + ox, pivot[1] + oy
                    if 0 <= X < out.shape[1] and 0 <= Y < out.shape[0]:
                        out[Y, X] = spr[iy, ix]

    def compose_walk(self, view, phase: float, stride: float) -> np.ndarray:
        """前後腳交替：以髖部為軸做像素剪切，往前擺的那隻腳抬起 1~2 格。
        手臂與同側腳反向擺動（前手配前腳反向、後手配後腳反向），避免同手同腳。"""
        base, leg, back, top, bot, facing, shoulder = self.legs[view]
        out = np.zeros_like(base)
        h = max(bot - top, 1)
        for img, sgn in ((back, -1), (leg, 1)):
            swing = sgn * stride * math.sin(phase) * facing
            lift = int(round(max(0.0, sgn * math.cos(phase)) * 1.6))
            for y in range(top, bot + 1):
                row = img[y]
                xs = np.nonzero(row[:, 3])[0]
                if xs.size == 0:
                    continue
                dy = y - lift
                if not 0 <= dy < CANVAS:
                    continue
                dx = xs + int(round(swing * (y - top) / h))
                ok = (dx >= 0) & (dx < CANVAS)
                out[dy, dx[ok]] = row[xs[ok]]
        m = base[..., 3] > 0
        out[m] = base[m]
        return out

    def _wing_patch(self, out, root, side, sx, over, alpha_mul=1.0, dy=0):
        """把翅膀以根部為軸、水平縮放 sx（拍動／透視）貼上。side=+1 往右、-1 往左；
        over=False 畫在身體後面，True 疊在身體前面（半透明混合）。"""
        wing = self.wing
        h, w = wing.shape[:2]
        n = max(1, int(round(w * sx)))
        cols = np.arange(n)
        src = np.clip((cols / max(sx, 1e-3)).astype(int), 0, w - 1)
        X = root[0] + side * cols
        Y0 = root[1] - self.wing_root + dy
        okx = (X >= 0) & (X < CANVAS)
        X, src = X[okx], src[okx]
        for r in range(h):
            Y = Y0 + r
            if not 0 <= Y < CANVAS:
                continue
            px = wing[r, src].astype(np.float32)
            a = px[:, 3] * alpha_mul / 255.0
            vis = a > 0
            if not vis.any():
                continue
            Xv, pv, av = X[vis], px[vis], a[vis]
            dst = out[Y, Xv].astype(np.float32)
            if over:
                body = dst[:, 3] > 0
                mix = dst.copy()
                mix[:, :3] = pv[:, :3] * av[:, None] + dst[:, :3] * (1 - av[:, None])
                mix[:, 3] = np.maximum(dst[:, 3], av * 255)
                res = np.where(body[:, None], mix, np.concatenate([pv[:, :3], (av * 255)[:, None]], 1))
            else:
                empty = dst[:, 3] == 0
                res = np.where(empty[:, None], np.concatenate([pv[:, :3], (av * 255)[:, None]], 1), dst)
            out[Y, Xv] = res.astype(np.uint8)

    def compose_wings(self, arr: np.ndarray, view, flap: float) -> np.ndarray:
        key, mir = view
        if key in ("top", "bottom"):
            return arr
        out = arr.copy()
        cx, cy = CANVAS // 2, PAD + WING_ROOT_ROW
        if key == "front":
            for side in (1, -1):
                self._wing_patch(out, (cx + side * 2, cy), side, flap, over=False)
        elif key == "back":
            for side in (1, -1):
                self._wing_patch(out, (cx + side * 2, cy), side, flap, over=True)
        elif key in ("fl", "bl"):
            # 斜側：面向的那一側翅膀比較窄（透視）
            facing = -1 if not mir else 1
            over = key == "bl"
            for side in (1, -1):
                k = 0.6 if side == facing else 1.0
                self._wing_patch(out, (cx + side * 2, cy), side, flap * k, over=over, alpha_mul=1.0 if k == 1 else 0.85)
        else:  # 側面：翅膀往背後長
            sh = self.legs[view][6]
            f = self.legs[view][5]
            root = (sh[0] - f * 3, sh[1] + 2)
            self._wing_patch(out, (root[0] - f, root[1] - 1), -f, flap * 0.6, over=False, alpha_mul=0.7)
            self._wing_patch(out, root, -f, flap * 0.75, over=False)
        return out

    def compose_head(self, body: np.ndarray, head_view) -> np.ndarray:
        out = body.copy()
        out[: self.head_cut] = 0
        head = self.views[head_view]
        hm = head[: self.head_cut, :, 3] > 0
        out[: self.head_cut][hm] = head[: self.head_cut][hm]
        return out

    def deform(self, arr: np.ndarray, p: dict) -> Image.Image:
        if not DEFORM:  # Chico：不做分區塊的像素位移（會把頭、身體、裙子撕開），整個人一起動
            return Image.fromarray(arr)
        s = self.s
        dx = (
            p["lean"] * self.w_lean
            + p["head"] * self.w_head
            + p["hair"] * self.w_hair
            + p["skirt"] * self.w_skirt
            + p["flare"] * self.u * (CROP_HALF * KN * s) * self.w_skirt
            + p["legs"] * self.w_legs
            + p.get("look_x", 0.0) * self.w_head
        ) / s
        dy = (-p["breath"] * self.w_breath + p["wing"] * self.w_wing + p.get("look_y", 0.0) * self.w_head) / s
        sx = self.xx - np.rint(dx).astype(np.int32)
        sy = self.yy - np.rint(dy).astype(np.int32)
        ok = (sx >= 0) & (sx < CANVAS) & (sy >= 0) & (sy < CANVAS)
        out = arr[np.clip(sy, 0, CANVAS - 1), np.clip(sx, 0, CANVAS - 1)]
        out[~ok] = 0
        return Image.fromarray(out)

    def render(self, view, params, rot, sx, sy, frac=(0.0, 0.0)) -> Image.Image:
        if params.get("head_view") and view == ("front", False):
            view = params["head_view"]  # 滑鼠很遠：整個人轉向斜側看（Chico 的頭很大，不拆頭身）
        arr = self.views[view]
        if params.get("stride", 0) > 0 and view in self.legs:
            arr = self.compose_walk(view, params["gait"], params["stride"])
        elif params.get("eyes", (0, 0)) != (0, 0) or params.get("blink"):
            arr = self.eye_view(view, params.get("eyes", (0, 0)), params.get("blink"))
        if HAS_WINGS and params.get("wing_flap") is not None:
            arr = self.compose_wings(arr, view, params["wing_flap"])
        img = self.deform(arr, params)
        W = WIN_N
        r = math.radians(rot)
        c, s = math.cos(r), math.sin(r)
        if abs(c) < 1e-9:
            c = 0.0
        if abs(s) < 1e-9:
            s = 0.0
        sx = max(sx, 0.05)
        sy = max(sy, 0.05)
        wcx, wcy = W / 2, W / 2
        a, b = c / sx, s / sx
        d, e = -s / sy, c / sy
        Cx, Cy = self.C
        coeffs = (a, b, Cx - a * wcx - b * wcy, d, e, Cy - d * wcx - e * wcy)
        # 回傳原生解析度（WIN_N×WIN_N）；放大在送進視窗時以整數倍複製像素完成
        return img.transform((W, W), Image.AFFINE, coeffs, Image.NEAREST)

# ------------------------------------------------------------------ pet logic
class Spring:
    def __init__(self, k, d):
        self.k, self.d, self.x, self.v = k, d, 0.0, 0.0

    def step(self, target, dt):
        self.v += (self.k * (target - self.x) - self.d * self.v) * dt
        self.x += self.v * dt
        return self.x


class Pet:
    ANIM_KEYS = ("lean", "head", "legs", "wing", "flare")

    def __init__(self, rig: Rig, work_fn):
        self.work_fn = work_fn
        self.set_rig(rig)
        l, t, r, b = work_fn((0, 0))
        self.P = [(l + r) / 2, t + (b - t) * 0.35]
        self.lastP = list(self.P)
        self.rot = 0.0
        self.sx = self.sy = 1.0
        self.squeeze_x = self.squeeze_y = 1.0
        self.yaw = 0.0
        self.view = ("front", False)
        self.view_rot = 0.0
        self.a = {k: 0.0 for k in self.ANIM_KEYS}
        self.a_s = dict(self.a)
        self.gait = 0.0  # 走路相位
        self.stride = 0.0  # 跨步幅度（點陣像素），0 = 不走路
        self.jelly = Spring(260, 9)
        self.hair = Spring(70, 5.5)
        self.skirt = Spring(95, 7)
        self.flare = Spring(55, 5)
        self.t = 0.0
        self.dt = 1 / 30
        self.work = work_fn(self.P)
        self.action = None
        self.queue: list = []
        self.auto = True
        self.last_kind = "idle"
        self.dragging = False
        self.mouse = (0.0, 0.0)
        self.v_world = (0.0, 0.0)
        self.on_snack = None  # callback(x, y, vx, vy)：扔出一個零食
        self.eyes = (0, 0)  # 眼睛位移（點）
        self.eyes_override = None  # 動作指定的視線（例如許願時往上看）
        self.happy_eyes = False  # 開心瞇眼（抱抱時）
        self.blink_t = random.uniform(BLINK_MIN_S, BLINK_MAX_S)
        self.blink_left = 0.0
        self.care = None  # Care
        self.props: dict = {}  # name -> (img, x, bottom_y, layer)
        self.particles: list = []
        self.speech = None  # (text, until_t)
        self.sleeping = False
        self.wake_req = False
        self.platform = None  # 站在某個視窗頂端：{"hwnd", "rect"}
        self.win_rect_fn = None
        self.windows_fn = None
        self.cursor_pos = None
        self.look_enabled = True
        self.follow_enabled = True
        self.toys: list = []  # Toy，由 App 管理
        self.on_sound = None  # callback(name or None)：播放／停止音樂
        self.music_on = False
        self.busy_look = False
        self.clip_y = None
        self.quilt_frac = 0.0
        self.flying = False  # 飛行中（倒吊前飛上去）：翅膀快速拍動
        self.in_air = False
        self.wing_phase = 0.0
        self.wing_amp = 0.12
        self.cursor_last = None
        self.cursor_moved_t = -99.0
        self.look = [0.0, 0.0]
        self.head_view = None
        self.base_work = self.work
        self.run(self.act_fall(0, 0, 0))

    def set_rig(self, rig: Rig):
        self.rig = rig
        self.U = rig.U
        self.G = 9.0 * rig.U

    # ---------------------------------------------------------- geometry
    def total_scale(self):
        j = self.jelly.x
        return self.sx * self.squeeze_x * (1 + 0.7 * j), self.sy * self.squeeze_y * (1 - j)

    def extent(self):
        sxT, syT = self.total_scale()
        df, dh, hw = self.rig.df, self.rig.dh, self.rig.hw
        pts = [(0, df), (0, -dh), (hw, 0), (-hw, 0), (hw * 0.7, df * 0.8), (-hw * 0.7, df * 0.8),
               (hw * 0.8, -dh * 0.6), (-hw * 0.8, -dh * 0.6)]
        ys = [rot2(x * sxT, y * syT, self.rot)[1] for x, y in pts]
        return min(ys), max(ys)

    def feet_vec(self):
        sxT, syT = self.total_scale()
        return rot2(0, self.rig.df * syT, self.rot)

    def place_feet(self, fx, fy):
        vx, vy = self.feet_vec()
        self.P[0], self.P[1] = fx - vx, fy - vy

    def ground(self, lift=0.0):
        l, t, r, b = self.work
        hw = self.rig.hw
        self.P[0] = min(max(self.P[0], l + hw), r - hw)
        self.P[1] = b - lift - self.extent()[1]

    def grounded(self):
        return self.P[1] + self.extent()[1] >= self.work[3] - 3

    def set_yaw(self, y):
        self.yaw = y % 360.0
        self.view = YAW_VIEWS[int(round(self.yaw / 45.0)) % 8]
        self.view_rot = 0.0
        self.squeeze_x = 0.72 + 0.28 * abs(math.cos(math.radians(4 * self.yaw)))

    def kick(self, impact_vy, scale=1.0):
        self.jelly.v += min(abs(impact_vy) / self.U * 0.75, 3.6) * scale

    # ---------------------------------------------------------- frame update
    def step(self, dt):
        self.dt = dt
        self.t += dt
        self.update_platform()
        vx = (self.P[0] - self.lastP[0]) / dt
        vy = (self.P[1] - self.lastP[1]) / dt
        self.lastP = list(self.P)
        self.v_world = (vx, vy)
        bvx, bvy = rot2(vx, vy, -self.rot)
        U = self.U
        lim = 0.07 * U
        self.hair.step(max(-lim, min(lim, -bvx * 0.045)), dt)
        self.skirt.step(max(-lim, min(lim, -bvx * 0.035)), dt)
        self.flare.step(max(-0.05, min(0.2, bvy / U * 0.06)), dt)
        self.jelly.step(0.0, dt)
        self.jelly.x = max(-0.3, min(0.35, self.jelly.x))

        if self.dragging:
            self.drag_step()
        else:
            if self.action is None:
                self.action = self.next_action()
            try:
                next(self.action)
            except StopIteration:
                self.action = None
        f = min(1.0, dt * 14)
        for k in self.ANIM_KEYS:
            self.a_s[k] += (self.a[k] - self.a_s[k]) * f
        self.update_look(dt)
        self.update_particles(dt)
        self.blink_t -= dt
        self.blink_left = max(0.0, self.blink_left - dt)
        if self.blink_t <= 0:
            self.blink_left = 0.13
            self.blink_t = random.uniform(BLINK_MIN_S, BLINK_MAX_S)
        # 翅膀：平常輕輕拍、空中拍快、飛行時用力拍
        if self.flying:
            hz, amp = 7.0, 0.55
        elif self.in_air or self.dragging:
            hz, amp = 4.5, 0.4
        elif self.sleeping:
            hz, amp = 0.5, 0.05
        else:
            hz, amp = 1.1, 0.14
        self.wing_phase += dt * 2 * math.pi * hz
        self.wing_amp += (amp - self.wing_amp) * min(1.0, dt * 6)
        if self.cursor_pos is not None:
            if self.cursor_last is None or abs(self.cursor_pos[0] - self.cursor_last[0]) + abs(
                    self.cursor_pos[1] - self.cursor_last[1]) > 4:
                self.cursor_moved_t = self.t
            self.cursor_last = self.cursor_pos
        if self.care:
            self.care.tick(dt, self.sleeping)

    def params(self):
        U, t, a = self.U, self.t, self.a_s
        gx, gy = math.sin(math.radians(self.rot)), math.cos(math.radians(self.rot))
        return {
            "lean": a["lean"],
            "head": a["head"] + self.hair.x * 0.25,
            "breath": (0.016 * U * math.sin(t * 2 * math.pi / 4.6)) if self.sleeping
            else 0.008 * U * math.sin(t * 2 * math.pi / 3.4),
            "hair": self.hair.x + gx * 0.04 * U,
            "skirt": self.skirt.x + gx * 0.03 * U,
            "flare": self.flare.x + a["flare"] + (1 - gy) * 0.03,
            "legs": a["legs"] + self.skirt.x * 0.4,
            "wing": a["wing"] + 0.004 * U * math.sin(t * 2.1),
            "gait": self.gait,
            "stride": self.stride,
            "look_x": 0.0,  # Chico 用眼睛看，不移動頭
            "look_y": 0.0,
            "head_view": self.head_view,
            "eyes": self.eyes_override or self.eyes,
            "blink": self.sleeping or self.blink_left > 0 or self.happy_eyes,
            "wing_flap": None,  # Chico 沒有翅膀
        }

    def facing(self):
        return 1 if self.view in (("right", False), ("left", True)) else -1

    def frame(self):
        W = self.rig.W
        ox, oy = self.P[0] - W / 2, self.P[1] - W / 2
        wx, wy = math.floor(ox), math.floor(oy)
        sxT, syT = self.total_scale()
        img = self.rig.render(self.view, self.params(), self.rot + self.view_rot, sxT, syT, (ox - wx, oy - wy))
        if self.clip_y is not None:  # 躺在床裡：床墊以下不畫
            cut = int(round((self.clip_y - self.P[1]) / self.rig.s + WIN_N / 2))
            if cut < WIN_N:
                a = np.array(img)
                a[max(cut, 0):, :, 3] = 0
                img = Image.fromarray(a)
            if "bed" in self.props and self.quilt_frac > 0:
                img = self.draw_quilt(img, cut)
        if self.props or self.particles:
            img = self.compose_extras(img)
        return img, wx, wy

    def draw_quilt(self, img, mat):
        """湖水綠被子：沿著她露出床墊的身體輪廓往上多蓋 2 格，從頸部蓋到床尾，只露出頭。"""
        s = self.rig.s
        half = WIN_N / 2
        a = np.array(img)
        alpha = a[..., 3] > 0
        bed_left = (self.bed_x - self.P[0]) / s + half - 39  # 床圖左緣（床寬 78）
        x0, x1 = int(round(bed_left + 38)), int(round(bed_left + 72))
        mat = min(max(mat, 1), WIN_N - 5)
        tops = {}
        for x in range(max(x0, 0), min(x1, WIN_N - 1) + 1):
            col = np.nonzero(alpha[:mat, x])[0]
            tops[x] = int(col[0]) if col.size else mat - 3
        xs = sorted(tops)
        if not xs:
            return img
        # 平滑：取附近最高點、再做移動平均，往上多蓋 2 格；quilt_frac 控制被子拉上來的程度
        hi = {x: min(tops[k] for k in xs if abs(k - x) <= 3) for x in xs}
        avg = {x: sum(hi[k] for k in xs if abs(k - x) <= 3) / sum(1 for k in xs if abs(k - x) <= 3) for x in xs}
        f = self.quilt_frac
        sm = {x: int(round(mat - (mat - (min(avg[x], hi[x]) - 2)) * f)) for x in xs}
        quilt, quilt_d, quilt_l = (150, 222, 206, 255), (112, 192, 180, 255), (204, 244, 234, 255)  # 湖水綠被子
        line = (34, 92, 96, 255)
        for i, x in enumerate(xs):
            top = max(sm[x], 0)
            a[top:mat + 4, x] = quilt
            a[top, x] = line
            a[mat + 4, x] = line
            if x % 2 == 0:
                a[mat + 2, x] = quilt_d
            if i < 3:  # 翻折的被緣
                a[top + 1:mat + 3, x] = quilt_l
        a[max(sm[xs[0]], 0):mat + 5, xs[0]] = line
        a[max(sm[xs[-1]], 0):mat + 5, xs[-1]] = line
        for k, x in enumerate(xs[6:-3:9]):  # 被子上的小狸貓腳印
            y = max(sm[x], 0) + 4 + (k % 2) * 2
            if y + 2 < mat + 3:
                paw, toe = (186, 140, 100, 255), (150, 104, 76, 255)
                for dx, dy in ((0, 1), (1, 1), (0, 2), (1, 2)):
                    a[y + dy, x + dx] = paw
                for dx in (-1, 1, 2):
                    a[y - 1 if dx != 1 else y - 1, x + dx] = toe
        return Image.fromarray(a)

    def compose_extras(self, img):
        s = self.rig.s
        half = WIN_N / 2

        def at(spr, x, y, anchor="bottom"):
            nx = (x - self.P[0]) / s + half - spr.width / 2
            ny = (y - self.P[1]) / s + half - (spr.height if anchor == "bottom" else spr.height / 2)
            return int(round(nx)), int(round(ny))

        back = [v for v in self.props.values() if v[3] == "back"]
        front = [v for v in self.props.values() if v[3] != "back"]
        if back:
            base = Image.new("RGBA", img.size, (0, 0, 0, 0))
            for spr, x, by, _ in back:
                base.paste(spr, at(spr, x, by), spr)
            base.alpha_composite(img)
            img = base
        else:
            img = img.copy()
        for spr, x, by, _ in front:
            img.paste(spr, at(spr, x, by), spr)
        for q in self.particles:
            if q["age"] > q["life"] * 0.7 and int(q["age"] * 14) % 2:
                continue
            spr = PARTICLES[q["kind"]]
            img.paste(spr, at(spr, q["x"], q["y"], "center"), spr)
        return img

    # ---------------------------------------------------------- action plumbing
    def over(self, dur):
        t = 0.0
        while t < dur:
            yield t / dur
            t += self.dt
        yield 1.0

    def reset_pose(self):
        for k in self.ANIM_KEYS:
            self.a[k] = 0.0
        self.sx = self.sy = 1.0
        self.squeeze_y = 1.0
        self.view_rot = 0.0
        self.stride = 0.0
        self.squeeze_x = 1.0
        self.flying = False
        self.in_air = False
        self.busy_look = False
        self.clip_y = None
        if self.music_on and self.on_sound:
            self.on_sound(None)
        self.music_on = False
        for toy in self.toys:  # 被打斷時把抱著的玩具放下
            if toy.carried:
                toy.carried = False
                toy.x, toy.y = self.P[0] + 0.3 * self.U, self.work[3]
        self.quilt_frac = 0.0
        self.eyes_override = None
        self.happy_eyes = False
        self.props.clear()
        self.sleeping = False
        self.set_yaw(round(self.yaw / 45.0) * 45.0)

    def _chain(self, gen):
        if not self.grounded() or abs(wrap180(self.rot)) > 5:
            self.set_yaw(self.yaw)
            yield from self.act_fall(0, 0, 0, keep_rot=True)
        self.reset_pose()
        yield from gen

    def run(self, gen):
        self.dragging = False
        self.queue.clear()
        self.action = self._chain(gen)

    def next_action(self):
        if self.queue:
            return self._chain(self.queue.pop(0)())
        if not self.auto:
            return self._chain(self.act_idle(2.0, face=False))
        if self.follow_want():
            self.last_kind = "follow"
            return self._chain(self.act_follow())
        c = self.care
        if c and c.v["energy"] < 15 and not self.platform:
            self.last_kind = "sleep"
            return self._chain(self.act_sleep())
        if self.last_kind != "idle":
            self.last_kind = "idle"
            if c and c.v["hunger"] < 20 and random.random() < 0.35:
                self.say(random.choice(LINES["hungry"]))
            elif c and c.v["clean"] < 20 and random.random() < 0.3:
                self.say(random.choice(LINES["dirty"]))
            elif c and c.v["energy"] < 25 and random.random() < 0.3:
                self.say(random.choice(LINES["sleepy"]))
            elif random.random() < CHATTER_CHANCE:
                pool = LINES["night"] if (is_night() and random.random() < 0.5) else LINES["idle"]
                self.say(random.choice(pool))
            return self._chain(self.act_idle(random.uniform(1.5, 4.0)))
        if self.platform:
            choices = [
                ("walk", 4.0, lambda: self.act_walk()),
                ("look", 1.2, lambda: self.act_look()),
                ("spin", 0.8, lambda: self.act_spin()),
                ("bounce", 0.6, lambda: self.act_bounce((0.45, 0.2))),
                ("jump_down", 1.4, lambda: self.act_jump_down()),
            ]
        else:
            choices = [
                ("walk", 4.0, lambda: self.act_walk()),
                ("look", 1.2, lambda: self.act_look()),
                ("spin", 1.0, lambda: self.act_spin()),
                ("bounce", 1.2, lambda: self.act_bounce()),
                ("frontflip", 0.7, lambda: self.act_frontflip()),
                ("somersault", 0.7, lambda: self.act_somersault()),
                ("hang", 0.8, lambda: self.act_hang()),
            ]
            if self.windows_fn:
                choices.append(("climb", 0.9, lambda: self.act_climb()))
            choices.append(("dance", 0.5, lambda: self.act_dance()))
            if any(tt.kind == "plush" for tt in self.toys):
                choices.append(("plush", 1.0, lambda: self.act_hug_plush()))
                choices.append(("toss", 0.7, lambda: self.act_toss_plush()))
            choices.append(("snack", 0.4, lambda: self.act_plant()))
        r = random.uniform(0, sum(w for _, w, _ in choices))
        for kind, w, fn in choices:
            r -= w
            if r <= 0:
                break
        self.last_kind = kind
        return self._chain(fn())

    # ---------------------------------------------------------- building blocks
    def turn_to(self, target, per45=0.1):
        cur = self.yaw
        diff = wrap180(target - cur)
        if abs(diff) < 1:
            return
        for p in self.over(per45 * abs(diff) / 45):
            self.set_yaw(cur + diff * ease(p))
            self.ground()
            yield
        self.set_yaw(target)

    def settle(self, dur=0.35):
        r0 = wrap180(self.rot)
        sx0, sy0 = self.sx, self.sy
        for p in self.over(dur):
            e = ease(p)
            self.rot = r0 * (1 - e)
            self.sx = sx0 + (1 - sx0) * e
            self.sy = sy0 + (1 - sy0) * e
            self.ground()
            yield
        self.rot = 0.0

    def crouch(self, dur=0.16, depth=0.18):
        for p in self.over(dur):
            e = ease(p)
            self.sy = 1 - depth * e
            self.sx = 1 + depth * 0.7 * e
            self.ground()
            yield
        self.sx = self.sy = 1.0
        self.jelly.x = -depth * 0.8  # 起跳拉長

    def airborne(self, vx, vy, spin=0.0, cb=None):
        T = 0.0
        hw = self.rig.hw
        self.in_air = True
        while True:
            dt = self.dt
            vy += self.G * dt
            self.P[0] += vx * dt
            self.P[1] += vy * dt
            self.rot += spin * dt
            l, t, r, b = self.work
            if self.P[0] < l + hw:
                self.P[0], vx = l + hw, abs(vx) * 0.6
            elif self.P[0] > r - hw:
                self.P[0], vx = r - hw, -abs(vx) * 0.6
            if cb:
                cb(T)
            T += dt
            lo, hi = self.extent()
            if self.P[1] + lo < t and vy < 0:
                self.P[1], vy = t - lo, abs(vy) * 0.4
            if vy > 0 and self.P[1] + hi >= b:
                self.P[1] = b - hi
                self.in_air = False
                return vy, vx
            yield

    # ---------------------------------------------------------- actions
    def act_idle(self, dur, face=True):
        if face:
            yield from self.turn_to(0)
        for _ in self.over(dur):
            if self.follow_want():
                return
            t = self.t
            self.a["head"] = 0.012 * self.U * math.sin(t * 1.3)
            self.a["lean"] = 0.006 * self.U * math.sin(t * 0.9)
            self.ground()
            yield

    def act_look(self):
        yield from self.turn_to(0)
        for target in (315, 0, 45, 0):
            yield from self.turn_to(target, 0.14)
            yield from self.act_idle(random.uniform(0.5, 1.0), face=False)

    def act_walk(self, direction=0, dist=None, face_front=True, events=True):
        U = self.U
        l, t, r, b = self.work
        if direction == 0:
            room_r, room_l = r - self.P[0], self.P[0] - l
            direction = 1 if random.random() < room_r / max(room_r + room_l, 1) else -1
        dist = dist or random.uniform(1.5, 5.0) * U
        yield from self.turn_to(90 if direction > 0 else 270)
        speed = WALK_SPEED * U
        phase = 0.0
        moved = 0.0
        hw = self.rig.hw
        # 隨機邊走邊扔零食／跌倒
        snack_at = (random.uniform(0.25, 0.75) * dist
                    if (events and self.on_snack and random.random() < SNACK_CHANCE) else -1)
        trip_at = random.uniform(0.2, 0.9) * dist if (events and random.random() < TRIP_CHANCE) else -1
        while moved < dist:
            if 0 <= snack_at <= moved:  # 不停下來，直接往身後扔
                snack_at = -1
                self.throw_snack(-direction)
            if 0 <= trip_at <= moved:
                self.stride = 0.0
                self.a["lean"] = 0.0
                yield from self.act_trip()
                return
            l, t, r, b = self.work
            nx = self.P[0] + speed * self.dt * direction
            if nx > r - hw or nx < l + hw:
                self.a["lean"] = 0.0
                self.stride = 0.0
                if not events:
                    break
                if self.platform and random.random() < 0.5:
                    yield from self.act_jump_down(direction)
                    return
                direction = -direction
                yield from self.turn_to(90 if direction > 0 else 270, 0.08)
                continue
            self.P[0] = nx
            moved += speed * self.dt
            phase += self.dt * 2 * math.pi * WALK_STEP_HZ
            # 點陣風：前傾用整數像素位移，不做小角度旋轉（避免鋸齒抖動）
            # 前後腳交替、前後手反向擺（Rig.compose_walk）；雙腳併攏時身體最高
            self.gait = phase
            self.stride = WALK_STRIDE
            self.a["lean"] = direction * 0.025 * U
            self.a["legs"] = 0.0
            self.a["head"] = math.cos(phase * 2) * 0.01 * U
            self.ground(abs(math.cos(phase)) * 0.016 * U)
            yield
        self.stride = 0.0
        for p in self.over(0.12):
            self.a["lean"] = 0.0
            self.ground()
            yield
        if face_front:
            yield from self.turn_to(0)

    def throw_snack(self, direction, power=1.0):
        """從手的位置往 direction 那一邊扔出一個零食（棒棒糖、餅乾、蛋糕、甜甜圈）。"""
        if not self.on_snack:
            return
        U = self.U
        self.on_snack(self.P[0], self.P[1] - 0.05 * U, direction * random.uniform(0.5, 1.1) * U * power,
                      -random.uniform(2.0, 2.8) * U * power)
        self.kick(0.3 * U, 0.4)

    def act_plant(self):
        """停下來、轉正面，把零食往旁邊扔出去。"""
        yield from self.turn_to(0, 0.08)
        d = random.choice([1, -1])
        yield from self.crouch(0.12, 0.1)
        self.throw_snack(d, 1.3)
        for p in self.over(0.3):
            self.a["lean"] = d * 0.02 * self.U * math.sin(math.pi * p)
            self.ground()
            yield
        self.a["lean"] = 0.0
        self.say(random.choice(["給你點心！", "接好喔～", "請你吃！"]), 1.2)
        yield from self.act_idle(0.6, face=False)

    def act_spin(self, turns=None):
        turns = turns or random.choice([1, 1, 2])
        d = random.choice([1, -1])
        start = self.yaw
        dur = 0.8 * turns
        for p in self.over(dur):
            self.set_yaw(start + d * 360 * turns * ease(p))
            self.a["flare"] = 0.12 * math.sin(math.pi * p)
            self.ground(4 * 0.12 * self.U * p * (1 - p))
            yield
        self.set_yaw(start)
        self.a["flare"] = 0.0
        self.kick(0.6 * self.U)
        yield from self.act_idle(0.3, face=False)

    def act_bounce(self, heights=(0.75, 0.45, 0.22)):
        yield from self.crouch()
        for h in heights:
            v0 = math.sqrt(2 * self.G * h * self.U)
            impact, _ = yield from self.airborne(0, -v0)
            self.kick(impact)
        yield from self.settle(0.4)

    def act_frontflip(self):
        yield from self.turn_to(0)
        yield from self.crouch(0.2, 0.22)
        v0 = math.sqrt(2 * self.G * 1.3 * self.U)
        t_air = 2 * v0 / self.G

        def cb(T):
            p = min(1.0, T / (t_air * 0.9))
            phi = 360 * ease(p)
            view, vrot = FLIP_VIEWS[int(round(phi / 90.0)) % 4]
            self.view, self.view_rot = view, vrot
            self.squeeze_y = 0.55 + 0.45 * abs(math.cos(math.radians(2 * phi)))
            self.a["flare"] = 0.1 * math.sin(math.pi * p)

        impact, _ = yield from self.airborne(0, -v0, cb=cb)
        self.squeeze_y = 1.0
        self.a["flare"] = 0.0
        self.set_yaw(0)
        self.kick(impact)
        yield from self.settle(0.45)

    def act_somersault(self, direction=0):
        direction = direction or random.choice([1, -1])
        yield from self.turn_to(90 if direction > 0 else 270)
        yield from self.crouch(0.18, 0.2)
        v0 = math.sqrt(2 * self.G * 1.0 * self.U)
        t_air = 2 * v0 / self.G
        spin = direction * 360 / (t_air * 0.85)

        def cb(T):
            if abs(self.rot) >= 360:
                self.rot = 360.0 * direction
            self.a["legs"] = -direction * 0.03 * self.U * math.sin(math.pi * min(1, T / t_air))

        impact, _ = yield from self.airborne(direction * 0.55 * self.U, -v0, spin, cb)
        self.rot = wrap180(self.rot)
        self.a["legs"] = 0.0
        self.kick(impact)
        yield from self.settle(0.3)
        yield from self.turn_to(0)

    def act_hang(self, from_drag=False):
        U = self.U
        l, t, r, b = self.work
        target_y = t + self.rig.dh + 0.03 * U
        if not from_drag:
            yield from self.turn_to(0)
            yield from self.crouch(0.18, 0.15)
            vy = 0.0
            x0 = self.P[0]
            t0 = self.t
            self.flying = True
            while self.P[1] > target_y:
                vy = min(vy + 3.0 * U * self.dt, 2.4 * U)
                self.P[1] = max(target_y, self.P[1] - vy * self.dt)
                self.P[0] = x0 + math.sin((self.t - t0) * 4) * 0.04 * U
                self.a["wing"] = math.sin(self.t * 30) * 0.025 * U
                self.a["legs"] = math.sin(self.t * 7) * 0.012 * U
                yield
        # 翻成倒立
        r0 = wrap180(self.rot)
        target_rot = 180.0 if r0 >= 0 else -180.0
        y0 = self.P[1]
        for p in self.over(0.45):
            e = ease(p)
            self.rot = r0 + (target_rot - r0) * e
            self.P[1] = y0 + (target_y - y0) * e
            self.a["wing"] = math.sin(self.t * 30) * 0.025 * U
            yield
        self.rot = 180.0
        self.a["wing"] = 0.0
        self.flying = False
        fx, fy = self.P[0] + self.feet_vec()[0], self.P[1] + self.feet_vec()[1]
        for p in self.over(0.18):
            self.place_feet(fx, fy + (t - fy) * ease(p))
            yield
        anchor = (fx, t)
        self.kick(0.8 * U, 0.6)
        # 倒吊擺盪
        T = 0.0
        dur = random.uniform(5.0, 8.0)
        for p in self.over(dur):
            T += self.dt
            amp = 4 + 12 * math.exp(-T * 0.6)
            self.rot = 180 + amp * math.sin(T * 2 * math.pi / 1.5)
            self.a["legs"] = math.sin(T * 3.1) * 0.006 * U
            self.a["head"] = math.sin(T * 1.7) * 0.01 * U
            if 0.35 < p < 0.5:
                self.set_yaw(315)
            elif 0.55 < p < 0.7:
                self.set_yaw(45)
            else:
                self.set_yaw(0)
            self.place_feet(*anchor)
            yield
        self.set_yaw(0)
        # 放手：落下時半圈翻回正
        self.rot = 180.0
        fall_h = max(b - self.P[1], 1)
        t_fall = math.sqrt(2 * fall_h / self.G)
        spin = 180 / max(t_fall * 0.85, 0.15)

        def cb(T):
            if self.rot >= 360:
                self.rot = 360.0

        impact, _ = yield from self.airborne(0, 0, spin, cb)
        self.rot = wrap180(self.rot)
        self.kick(impact)
        yield from self.settle(0.35)

    def act_fall(self, vx, vy, spin, keep_rot=False):
        if not keep_rot:
            self.reset_pose()
        while True:
            impact, vx = yield from self.airborne(vx, vy, spin)
            self.kick(impact)
            if impact > 1.6 * self.U:
                vy, vx, spin = -impact * 0.42, vx * 0.7, spin * 0.5
            else:
                break
        yield from self.settle(0.4)
        yield from self.turn_to(0)

    # ---------------------------------------------------------- 系統：說話、粒子、視線、視窗平台
    def say(self, text, dur=None):
        self.speech = (text, self.t + (dur or 1.8 + 0.13 * len(text)))

    def spawn(self, kind, x, y, vx=0.0, vy=0.0, g=0.0, life=1.0):
        if len(self.particles) < 90:
            self.particles.append({"kind": kind, "x": x, "y": y, "vx": vx, "vy": vy, "g": g, "life": life,
                                   "age": 0.0, "ph": random.uniform(0, 6.28)})

    def update_particles(self, dt):
        keep = []
        for q in self.particles:
            q["age"] += dt
            if q["age"] > q["life"]:
                continue
            q["vy"] += q["g"] * dt
            q["x"] += q["vx"] * dt
            q["y"] += q["vy"] * dt
            if q["kind"] in ("bubble", "z"):
                q["x"] += math.sin(q["age"] * 5 + q["ph"]) * 0.06 * self.U * dt
            keep.append(q)
        self.particles = keep

    def update_look(self, dt):
        """視線跟著滑鼠：頭部位移；滑鼠離很遠時頭轉向斜側。"""
        tx = ty = 0.0
        hv = None
        ok = (self.look_enabled and not self.busy_look and self.cursor_pos is not None and not self.dragging
              and self.stride == 0
              and not self.sleeping and self.view == ("front", False) and abs(wrap180(self.rot)) < 3
              and self.squeeze_y == 1.0)
        if ok:
            U = self.U
            dx = self.cursor_pos[0] - self.P[0]
            dy = self.cursor_pos[1] - (self.P[1] - 0.3 * U)
            tx = max(-1.0, min(1.0, dx / (2.5 * U)))
            ty = max(-1.0, min(1.0, dy / (2.5 * U)))
            enter, leave = 0.9 * U, 0.6 * U
            if self.head_view == ("fl", False) and dx < -leave:
                hv = ("fl", False)
            elif self.head_view == ("fl", True) and dx > leave:
                hv = ("fl", True)
            elif dx < -enter:
                hv = ("fl", False)
            elif dx > enter:
                hv = ("fl", True)
        self.head_view = hv
        if ok:
            self.eyes = (0 if abs(dx) < 0.2 * U else (1 if dx > 0 else -1),
                         -1 if dy < -0.4 * U else (1 if dy > 0.35 * U else 0))
        else:
            self.eyes = (0, 0)
        s = self.rig.s
        k = min(1.0, dt * 8)
        self.look[0] += (tx * 1.6 * s - self.look[0]) * k
        self.look[1] += (ty * 1.2 * s - self.look[1]) * k

    def update_platform(self):
        self.base_work = self.work_fn(self.P)
        self.work = self.base_work
        if not self.platform:
            return
        rect = self.win_rect_fn(self.platform["hwnd"]) if self.win_rect_fn else None
        bl, bt, br, bb = self.base_work
        if (rect is None or rect[2] - rect[0] < 0.6 * self.U or rect[1] < bt + 0.3 * self.U
                or rect[1] > bb - 0.3 * self.U):
            self.platform = None
            if not self.dragging:
                self.say("哇！", 1.0)
                self.run(self.act_idle(0.3, face=False))  # _chain 會先讓她掉下來
            return
        old = self.platform["rect"]
        dx, dy = rect[0] - old[0], rect[1] - old[1]
        if not self.dragging:
            self.P[0] += dx
            self.lastP[0] += dx
            self.lastP[1] += dy
        self.platform["rect"] = rect
        self.work = (rect[0], bt, rect[2], rect[1])

    def follow_want(self):
        """滑鼠最近有在動、而且離她夠遠 → 想跟過去。"""
        if not (self.follow_enabled and self.auto) or self.cursor_pos is None or self.dragging or self.sleeping:
            return False
        if self.t - self.cursor_moved_t > 1.2:
            return False
        l, t, r, b = self.work
        cx, cy = self.cursor_pos
        if not (l <= cx <= r and t - 50 <= cy <= b + 50):
            return False
        return abs(cx - self.P[0]) > FOLLOW_START * self.U

    def act_follow(self):
        """默默地左右走到滑鼠下面，停下來盯著看。"""
        U = self.U
        hw = self.rig.hw
        phase = 0.0
        direction = 0
        if random.random() < 0.15:
            self.say(random.choice(LINES["follow"]), 1.2)
        while self.cursor_pos is not None and self.follow_enabled:
            dx = self.cursor_pos[0] - self.P[0]
            if abs(dx) < FOLLOW_STOP * U or self.t - self.cursor_moved_t > FOLLOW_IDLE_S:
                break
            d = 1 if dx > 0 else -1
            if d != direction:
                self.stride = 0.0
                self.a["lean"] = 0.0
                yield from self.turn_to(90 if d > 0 else 270, 0.07)
                direction = d
            l, t, r, b = self.work
            nx = self.P[0] + FOLLOW_SPEED * U * self.dt * d
            if nx > r - hw or nx < l + hw:
                break
            self.P[0] = nx
            phase += self.dt * 2 * math.pi * FOLLOW_STEP_HZ
            self.gait = phase
            self.stride = WALK_STRIDE
            self.a["lean"] = d * 0.025 * U
            self.a["head"] = math.cos(phase * 2) * 0.01 * U
            self.ground(abs(math.cos(phase)) * 0.016 * U)
            yield
        self.stride = 0.0
        self.a["lean"] = self.a["head"] = 0.0
        yield from self.turn_to(0)
        yield from self.act_idle(0.6, face=False)

    def act_change(self):
        """換好衣服：轉一圈、冒星光。"""
        for _ in range(10):
            self.spawn("spark", self.P[0] + random.uniform(-0.35, 0.35) * self.U,
                       self.P[1] + random.uniform(-0.45, 0.35) * self.U, 0, -0.12 * self.U, 0, 1.0)
        yield from self.act_spin(1)
        self.say("換好了！好看嗎？")
        yield from self.act_idle(0.8, face=False)

    def music(self, name):
        if self.on_sound:
            self.on_sound(name)
            self.music_on = name is not None

    def act_dance(self):
        """跳舞：跟著「草莓糖霜波卡」的節拍（132 BPM）搖擺、側步、小跳、轉圈，最後擺姿勢。"""
        U = self.U
        yield from self.turn_to(0)
        self.say("跳舞囉～♪", 1.2)
        self.music("dance")
        beat = 60.0 / DANCE_BPM
        phrases = ["sway", "sway", "step", "hop", "spin", "sway", "step", "spin"]
        for ph in phrases:
            if ph == "spin":
                start = self.yaw
                d = random.choice([1, -1])
                for p in self.over(beat * 4):
                    self.set_yaw(start + d * 360 * ease(p))
                    self.a["flare"] = 0.16 * math.sin(math.pi * p)
                    self.ground(math.sin(math.pi * p) * 0.06 * U)
                    yield
                self.set_yaw(0)
                self.a["flare"] = 0.0
                continue
            for b in range(4):
                side = 1 if b % 2 == 0 else -1
                self.spawn("note" if b % 2 else "note2", self.P[0] + side * random.uniform(0.2, 0.4) * U,
                           self.P[1] - 0.45 * U, side * 0.1 * U, -0.35 * U, 0, 1.4)
                if ph == "step":
                    self.set_yaw(315 if side > 0 else 45)
                for p in self.over(beat):
                    w = math.sin(math.pi * p)
                    if ph == "sway":
                        self.a["lean"] = side * 0.04 * U * w
                        self.a["head"] = -side * 0.02 * U * w
                        self.sy = 1 - 0.05 * w
                        self.ground()
                    elif ph == "step":
                        self.P[0] += side * 0.25 * U * self.dt
                        self.ground(0.05 * U * w)
                    else:  # hop
                        self.a["flare"] = 0.12 * w
                        self.ground(0.14 * U * w)
                    yield
                self.sy = 1.0
            self.a["lean"] = self.a["head"] = self.a["flare"] = 0.0
            self.set_yaw(0)
        # 收尾的姿勢：蹲一下、跳起來
        yield from self.crouch(0.15, 0.2)
        v0 = math.sqrt(2 * self.G * 0.45 * U)
        impact, _ = yield from self.airborne(0, -v0)
        self.kick(impact)
        self.music(None)
        if self.care:
            self.care.add("mood", 6)
            self.care.add("energy", -3)
        self.say("跳完了！好好玩～")
        yield from self.settle(0.3)

    def nearest_toy(self, kind):
        toys = [tt for tt in self.toys if tt.kind == kind and not tt.held and not tt.carried]
        return min(toys, key=lambda tt: abs(tt.x - self.P[0])) if toys else None

    def fetch_toy(self, kind="plush"):
        """走到玩具旁邊、彎腰撿起來（抱在懷裡）。回傳玩具，找不到回傳 None。"""
        U = self.U
        toy = self.nearest_toy(kind)
        if not toy:
            self.say("小狸貓跑去哪了？")
            return None
        for _tries in range(4):
            toy = self.nearest_toy(kind)
            if not toy:
                return None
            for _ in range(90):  # 還在空中就等它落地
                if toy.grounded(self.work_fn((toy.x, toy.y - 10))[3]):
                    break
                yield
            gap = abs(toy.x - self.P[0])
            if gap < 0.3 * U:
                break
            yield from self.act_walk(1 if toy.x > self.P[0] else -1, gap - 0.15 * U, face_front=False, events=False)
        toy = self.nearest_toy(kind)
        if not toy:
            return None
        yield from self.turn_to(0)
        for p in self.over(0.25):  # 彎腰撿起來
            self.sy = 1 - 0.15 * ease(p)
            self.ground()
            yield
        toy.carried = True
        toy.angle = toy.spin = 0.0
        self.busy_look = True
        self.head_view = None
        for p in self.over(0.25):
            self.sy = 0.85 + 0.15 * ease(p)
            self.ground()
            yield
        self.sy = 1.0
        return toy

    def hold_toy(self, toy, dx=0.0, lift=0.0):
        s = self.rig.s
        cb = self.mouth_y() + (PLUSH.height + 4 - lift) * s
        self.props["plush"] = (toy_img("front"), self.P[0] + dx * s, cb, "front")
        return cb

    def act_hug_plush(self):
        """走到小狸貓旁邊，撿起來抱一抱，再放下。"""
        U = self.U
        plush = yield from self.fetch_toy("plush")
        if not plush:
            return
        self.say("小狸貓抱抱～", 1.6)
        for p in self.over(3.0):  # 抱在懷裡左右搖
            sway = math.sin(p * 3 * 2 * math.pi)
            self.a["lean"] = sway * 0.02 * U
            self.a["head"] = sway * 0.015 * U
            self.hold_toy(plush, sway)
            if random.random() < 0.02:
                self.spawn("heart", self.P[0], self.P[1] - 0.45 * U, 0, -0.3 * U, 0, 1.0)
            self.ground()
            yield
        self.a["lean"] = self.a["head"] = 0.0
        self.props.pop("plush", None)
        plush.carried = False
        side = random.choice([1, -1])
        plush.x, plush.y, plush.vx, plush.vy = self.P[0] + side * 0.32 * U, self.work[3], 0.0, 0.0
        self.busy_look = False
        if self.care:
            self.care.add("mood", 5)
        yield from self.act_idle(0.8, face=False)

    def act_toss_plush(self):
        """把小狸貓往上拋、接住，拋三次，最後往旁邊丟出去。"""
        U = self.U
        toy = yield from self.fetch_toy("plush")
        if not toy:
            return
        self.say("飛高高囉～！", 1.4)
        for i in range(3):
            for p in self.over(0.12):  # 蹲一下準備
                self.sy = 1 - 0.1 * ease(p)
                self.hold_toy(toy, 0, -2 * ease(p))
                self.ground()
                yield
            self.sy = 1.0
            cb = self.hold_toy(toy)
            self.props.pop("plush", None)
            toy.carried = False
            toy.x, toy.y = self.P[0], cb
            toy.vx = 0.0
            toy.vy = -math.sqrt(2 * self.G * random.uniform(0.9, 1.3) * U)
            toy.spin = random.choice([1, -1]) * random.uniform(8, 13)
            self.eyes_override = (0, -1)
            caught = False
            for _ in range(int(4 / max(self.dt, 1e-3))):
                if toy not in self.toys or toy.held:  # 被滑鼠搶走了
                    self.eyes_override = None
                    self.busy_look = False
                    return
                if toy.vy > 0 and toy.y >= cb:  # 掉回手上：接住
                    toy.carried = True
                    toy.vx = toy.vy = toy.spin = toy.angle = 0.0
                    caught = True
                    break
                self.ground()
                yield
            self.eyes_override = None
            if not caught:
                self.busy_look = False
                return
            self.kick(0.6 * U, 0.6)
            for p in self.over(0.25):
                self.hold_toy(toy, 0, 2 * math.sin(math.pi * p))
                self.ground()
                yield
            if self.care:
                self.care.add("mood", 2)
        # 最後一下往旁邊丟
        d = random.choice([1, -1])
        yield from self.turn_to(45 if d > 0 else 315, 0.08)
        cb = self.hold_toy(toy)
        self.props.pop("plush", None)
        toy.carried = False
        toy.x, toy.y = self.P[0] + d * 0.1 * U, cb
        toy.vx, toy.vy = d * random.uniform(1.4, 2.2) * U, -2.6 * U
        toy.spin = d * 10
        self.kick(0.5 * U, 0.5)
        self.busy_look = False
        self.say("哇，飛好遠！", 1.2)
        yield from self.act_idle(0.8, face=False)

    def act_tilt(self):
        """被點到的反應（開朗）：轉過來、開心地跳一下、冒愛心。"""
        yield from self.turn_to(0, 0.06)
        self.spawn("heart", self.P[0], self.P[1] - 0.45 * self.U, 0, -0.3 * self.U, 0, 1.0)
        yield from self.crouch(0.1, 0.1)
        v0 = math.sqrt(2 * self.G * 0.3 * self.U)
        impact, _ = yield from self.airborne(0, -v0)
        self.kick(impact, 0.6)
        yield from self.settle(0.25)
        yield from self.act_idle(0.6, face=False)

    def act_wish(self):
        """許願：抬頭看天，流星劃過，無口地許一個願。"""
        U = self.U
        yield from self.turn_to(0, 0.1)
        self.say(random.choice(LINES["wish"]), 2.2)
        # 慢慢抬頭（視線往上、頭微揚）
        for p in self.over(0.55):
            e = ease(p)
            self.a["head"] = -0.05 * U * e
            self.look[1] = -0.85 * e
            self.eyes_override = (0, -1)
            self.ground()
            yield
        # 流星從畫面上方斜劃而下
        sx = self.P[0] + random.uniform(-0.8, 0.4) * U
        sy = self.P[1] - 1.6 * U
        for p in self.over(1.1):
            e = ease(p)
            mx = sx + 1.4 * U * e
            my = sy + 1.1 * U * e
            self.spawn("spark", mx, my, 0.15 * U, 0.12 * U, 0, 0.45)
            if random.random() < 0.55:
                self.spawn("spark", mx - 0.08 * U, my - 0.05 * U, 0.05 * U, 0.08 * U, 0, 0.35)
            self.a["head"] = -0.05 * U
            self.look[1] = -0.85
            self.ground()
            yield
        # 收尾：心口一小下，心情上升
        self.spawn("heart", self.P[0], self.P[1] - 0.4 * U, 0, -0.25 * U, 0, 1.0)
        if self.care:
            self.care.add("mood", 6)
        for p in self.over(0.4):
            e = 1 - ease(p)
            self.a["head"] = -0.05 * U * e
            self.look[1] = -0.85 * e
            self.ground()
            yield
        self.a["head"] = 0.0
        self.look[1] = 0.0
        self.eyes_override = None
        yield from self.act_idle(0.6, face=False)

    # ---------------------------------------------------------- 互動動作
    def mouth_y(self):
        """嘴巴的世界座標 y（正面、站直時）。"""
        sxT, syT = self.total_scale()
        return self.P[1] + (PAD + MOUTH_ROW - self.rig.C[1]) * self.rig.s * syT

    def act_eat(self):
        """點心（隨機：糖果、餅乾、蛋糕、馬卡龍）從天上掉下來 → 撿起來 → 捧在嘴邊一口一口吃掉。"""
        U = self.U
        s = self.rig.s
        yield from self.turn_to(0)
        kind = random.choice(S.FOODS)
        food = [Image.fromarray(x) for x in S.food_stages(kind)]
        l, t, r, b = self.work
        d = 1 if (r - self.P[0]) > (self.P[0] - l) else -1
        fx = self.P[0] + d * 0.3 * U
        self.say(f"有{S.SNACK_NAMES[kind]}！", 1.2)
        # 1. 糖果閃著光掉下來
        fy, vy, bounced = b - 1.3 * U, 0.0, False
        while True:
            vy += self.G * 0.6 * self.dt
            fy += vy * self.dt
            if fy >= self.work[3]:
                fy = self.work[3]
                if not bounced and vy > 0.5 * U:
                    vy, bounced = -vy * 0.3, True
                else:
                    break
            if random.random() < 0.3:
                self.spawn("spark", fx + random.uniform(-4, 4) * s, fy - 6 * s, 0, -0.1 * U, 0, 0.5)
            self.props["food"] = (food[0], fx, fy, "front")
            self.ground()
            yield
        # 2. 轉過去、彎腰撿起來
        yield from self.turn_to(90 if d > 0 else 270)
        for p in self.over(0.3):
            e = ease(p)
            self.sy = 1 - 0.16 * e
            self.sx = 1 + 0.08 * e
            self.a["lean"] = d * 0.05 * U * e
            self.a["head"] = d * 0.03 * U * e
            self.ground()
            yield
        hand_x = self.P[0] + d * 0.16 * U
        for p in self.over(0.25):  # 糖果移到手上
            e = ease(p)
            cy = self.work[3] + (self.P[1] - self.work[3]) * e * 0.5
            self.props["food"] = (food[0], fx + (hand_x - fx) * e, cy, "front")
            self.ground()
            yield
        # 3. 站起來、轉正面，捧到嘴邊
        for p in self.over(0.25):
            e = ease(p)
            self.sy = 0.84 + 0.16 * e
            self.sx = 1.08 - 0.08 * e
            self.a["lean"] = d * 0.05 * U * (1 - e)
            self.a["head"] = d * 0.03 * U * (1 - e)
            self.props["food"] = (food[0], hand_x, self.P[1], "front")
            self.ground()
            yield
        self.sx = self.sy = 1.0
        self.busy_look = True
        self.head_view = None
        yield from self.turn_to(0, 0.08)

        def hold(size_i, lift=0.0):
            my = self.mouth_y()
            candy = food[size_i]
            cb = my + (candy.height / 2 + 3 - lift) * s
            self.props["food"] = (candy, self.P[0], cb, "front")

        for p in self.over(0.3):  # 點心捧上來
            hold(0, -6 * (1 - ease(p)))
            self.ground()
            yield
        # 4. 一口、兩口、三口
        for k in range(3):
            for p in self.over(0.18):  # 湊上去咬
                e = math.sin(math.pi * p)
                self.a["head"] = 0.0
                self.sy = 1 - 0.03 * e
                hold(k, 2 * e)
                self.ground()
                yield
            if k == 0:
                self.say("（嚼嚼）好甜～", 1.6)
            nxt = k + 1
            for _ in range(3):
                self.spawn("crumb" if random.random() < 0.5 else "spark", self.P[0] + random.uniform(-3, 3) * s,
                           self.mouth_y() + 4 * s, random.uniform(-0.3, 0.3) * U, -0.2 * U, 2.5 * U, 0.6)
            for p in self.over(0.6):  # 嚼
                self.sy = 1 - 0.025 * abs(math.sin(p * 3 * math.pi))
                if nxt < len(food):
                    hold(nxt)
                else:
                    self.props.pop("food", None)
                self.ground()
                yield
        self.sy = 1.0
        self.props.pop("food", None)
        self.busy_look = False
        if self.care:
            self.care.add("hunger", 35)
            self.care.add("mood", 4)
        self.say(random.choice(LINES["eat"]))
        self.spawn("heart", self.P[0], self.P[1] - 0.45 * U, 0, -0.3 * U, 0, 1.0)
        yield from self.act_idle(0.8, face=False)

    def update_bed(self, show=True):
        if not show:
            self.props.pop("bed", None)
            self.props.pop("bed_front", None)
            return
        if getattr(self, "_bed_key", None) != is_night():
            self._bed_key = is_night()
            self._bed = make_moonflower_bed(0.8 if self._bed_key else 0.0)
        back, front = self._bed
        x = self.bed_x if getattr(self, "bed_x", None) is not None else self.P[0]
        self.props["bed"] = (back, x, self.work[3], "back")
        self.props["bed_front"] = (front, x, self.work[3], "front")  # 前層與後層同尺寸，底部對齊

    def act_sleep(self, max_dur=None):
        U = self.U
        s = self.rig.s
        max_dur = max_dur if max_dur is not None else random.uniform(SLEEP_MIN_S, SLEEP_MAX_S)
        min_dur = min(SLEEP_MIN_S, max_dur)
        yield from self.turn_to(0)
        self.say("呼啊～想睡覺了…")
        for p in self.over(0.7):  # 打呵欠
            self.sy = 1 + 0.06 * math.sin(math.pi * p)
            self.sx = 1 - 0.04 * math.sin(math.pi * p)
            self.ground()
            yield
        self.sx = self.sy = 1.0
        # 小狸貓小床冒出來
        self.bed_x = self.P[0]
        for _ in range(8):
            self.spawn("spark", self.bed_x + random.uniform(-0.35, 0.35) * U, self.work[3] - random.uniform(0, 8) * s,
                       0, -0.15 * U, 0, 0.9)
        self.update_bed()
        for p in self.over(0.35):
            self.ground()
            yield
        # 爬上床、躺進被子裡（頭在左邊、枕在枕頭上）
        x0, y0 = self.P
        bed_cx, bed_cy = self.bed_x + 2 * s, self.work[3] - (BED_LIFT + 4) * s
        self.clip_y = self.work[3] - BED_LIFT * s
        for p in self.over(0.6):
            e = ease(p)
            self.rot = -90 * e
            self.P[0] = x0 + (bed_cx - x0) * e
            self.P[1] = y0 + (bed_cy - y0) * e - math.sin(math.pi * p) * 0.12 * U
            self.update_bed()
            yield
        self.rot = -90.0
        self.P[0], self.P[1] = bed_cx, bed_cy
        for p in self.over(0.4):  # 把被子拉上來蓋好
            self.quilt_frac = ease(p)
            self.update_bed()
            yield
        self.quilt_frac = 1.0
        self.sleeping, self.wake_req = True, False
        T = zt = 0.0
        while T < max_dur and not self.wake_req and not (
                T > min_dur and self.care and self.care.v["energy"] >= 100):
            T += self.dt
            zt += self.dt
            if zt > 1.6:
                zt = 0.0
                hx, hy = rot2(0, -0.8 * self.rig.dh, self.rot)
                self.spawn("z", self.P[0] + hx, self.P[1] + hy - 0.1 * U, 0.06 * U, -0.25 * U, 0, 2.0)
            self.P[0], self.P[1] = bed_cx, self.work[3] - (BED_LIFT + 4) * s
            self.clip_y = self.work[3] - BED_LIFT * s
            self.update_bed()
            yield
        self.sleeping = False
        self.say("嗯？醒了～" if self.wake_req else "早安！睡得好飽！")
        self.wake_req = False
        for p in self.over(0.35):  # 掀開被子
            self.quilt_frac = 1 - ease(p)
            self.update_bed()
            yield
        self.quilt_frac = 0.0
        for p in self.over(0.6):  # 坐起來、下床
            e = ease(p)
            self.rot = -90 * (1 - e)
            self.P[0] = bed_cx + (x0 - bed_cx) * e
            fy = self.work[3] - self.extent()[1]
            self.P[1] = bed_cy + (fy - bed_cy) * e - math.sin(math.pi * p) * 0.12 * U
            if p > 0.6:
                self.clip_y = None
            self.update_bed()
            yield
        self.clip_y = None
        self.rot = 0.0
        for _ in range(6):
            self.spawn("spark", self.bed_x + random.uniform(-0.35, 0.35) * U, self.work[3] - random.uniform(0, 8) * s,
                       0, -0.15 * U, 0, 0.8)
        self.update_bed(False)
        self.bed_x = None
        yield from self.turn_to(0)

    def act_bath(self):
        U = self.U
        yield from self.turn_to(0)
        self.say("泡泡澡時間～")
        bt = 0.0
        for p in self.over(3.0):
            self.props["foam"] = (FOAM, self.P[0], self.P[1] - self.rig.dh * 0.62, "front")
            self.a["head"] = math.sin(self.t * 10) * 0.02 * U
            self.squeeze_x = 1 + 0.04 * math.sin(self.t * 14)
            bt += self.dt
            if bt > 0.12:
                bt = 0.0
                self.spawn("bubble", self.P[0] + random.uniform(-0.35, 0.35) * U,
                           self.P[1] + random.uniform(-0.3, 0.3) * U, 0, -random.uniform(0.25, 0.55) * U, 0,
                           random.uniform(1.0, 1.8))
            self.ground()
            yield
        self.squeeze_x = 1.0
        self.a["head"] = 0.0
        self.props.pop("foam", None)
        self.say("甩甩甩～", 1.2)
        start = self.yaw
        for p in self.over(0.8):
            self.set_yaw(start + 360 * ease(p))
            if random.random() < 0.6:
                ang = random.uniform(0, 2 * math.pi)
                self.spawn("drop", self.P[0], self.P[1] - 0.2 * U, math.cos(ang) * 1.2 * U,
                           -abs(math.sin(ang)) * 1.0 * U, 3 * U, 0.6)
            self.ground()
            yield
        self.set_yaw(start)
        for _ in range(6):
            self.spawn("spark", self.P[0] + random.uniform(-0.4, 0.4) * U, self.P[1] + random.uniform(-0.45, 0.3) * U,
                       0, -0.1 * U, 0, 1.0)
        if self.care:
            self.care.v["clean"] = 100.0
            self.care.add("mood", 5)
        self.say("香香的了！")
        yield from self.act_idle(0.8, face=False)

    def act_trip(self):
        U = self.U
        if self.view not in self.rig.legs:
            yield from self.turn_to(random.choice([90, 270]))
        d = self.facing()
        self.say("哇！", 1.0)
        for p in self.over(0.3):  # 往前撲倒
            self.rot = d * 90 * ease(p)
            self.P[0] += d * 0.5 * U * self.dt
            self.ground(0.1 * U * math.sin(math.pi * p))
            yield
        self.rot = d * 90.0
        self.kick(1.4 * U)
        for _ in range(6):
            self.spawn("dust", self.P[0] + d * 0.3 * U + random.uniform(-0.25, 0.25) * U, self.work[3] - 2,
                       random.uniform(-0.4, 0.4) * U, -random.uniform(0.2, 0.5) * U, 1.5 * U, 0.6)
        if self.care:
            self.care.add("mood", -4)
        for _ in self.over(1.1):
            self.ground()
            yield
        self.say(random.choice(LINES["trip"]))
        yield from self.settle(0.45)
        yield from self.turn_to(0)

    def act_climb(self):
        """走到某個視窗旁，沿著視窗邊緣爬上去，站在視窗頂端。"""
        U = self.U
        if self.platform or not self.windows_fn:
            return
        l, t, r, b = self.base_work
        hw = self.rig.hw
        cands = []
        for hwnd, (wl, wt, wr, wb) in self.windows_fn():
            if wr - wl < 1.4 * U or wt < t + 1.15 * U or wt > b - 0.9 * U:
                continue
            for side, edge in ((-1, wl), (1, wr)):
                ax = edge + side * 0.2 * U
                if l + hw <= ax <= r - hw:
                    cands.append((abs(ax - self.P[0]), hwnd, side))
        if not cands:
            self.say("咦，沒有窗戶可以爬耶～")
            yield from self.act_idle(1.0, face=False)
            return
        cands.sort(key=lambda c: c[0])
        _, hwnd, side = random.choice(cands[:3])
        self.say("看我爬上去！")

        def edge_x():
            rc = self.win_rect_fn(hwnd)
            if rc is None:
                return None, None
            return (rc[0] if side < 0 else rc[2]), rc

        ex, rect = edge_x()
        if ex is None:
            return
        ax = ex + side * 0.2 * U
        if abs(ax - self.P[0]) > 2:
            yield from self.act_walk(1 if ax > self.P[0] else -1, abs(ax - self.P[0]), face_front=False, events=False)
        yield from self.turn_to(180)
        fy = self.work[3]
        x0 = self.P[0]
        phase = 0.0
        while True:  # 爬
            ex, rect = edge_x()
            if ex is None:
                self.say("哇！", 1.0)
                yield from self.act_fall(0, 0, 0, keep_rot=True)
                return
            xc = ex + side * 0.06 * U
            fy -= CLIMB_SPEED * U * self.dt * (0.6 + 0.4 * abs(math.sin(phase)))
            phase += self.dt * 2 * math.pi * 1.4
            self.a["legs"] = math.sin(phase) * 0.025 * U
            self.a["head"] = math.sin(phase) * 0.012 * U
            x = x0 + (xc - x0) * min(1.0, (self.work[3] - fy) / (0.3 * U))
            if fy <= rect[1]:
                break
            self.place_feet(x + math.sin(phase) * 0.01 * U, fy)
            yield
        self.a["legs"] = self.a["head"] = 0.0
        tx = ex - side * 0.45 * U
        for p in self.over(0.35):  # 翻上視窗頂
            ex2, rect = edge_x()
            if ex2 is None:
                break
            self.place_feet(xc + (tx - xc) * ease(p), rect[1] - math.sin(math.pi * p) * 0.18 * U)
            yield
        ex, rect = edge_x()
        if ex is None:
            yield from self.act_fall(0, 0, 0, keep_rot=True)
            return
        self.platform = {"hwnd": hwnd, "rect": rect}
        self.work = (rect[0], self.base_work[1], rect[2], rect[1])
        self.ground()
        self.kick(0.8 * U)
        yield from self.turn_to(0)
        self.say("爬上來了！好高喔～")
        yield from self.act_idle(0.8, face=False)

    def act_jump_down(self, direction=0):
        if not self.platform:
            return
        rect = self.platform["rect"]
        hw = self.rig.hw
        if direction == 0:
            direction = 1 if (rect[2] - self.P[0]) < (self.P[0] - rect[0]) else -1
            edge = rect[2] - hw if direction > 0 else rect[0] + hw
            if abs(edge - self.P[0]) > 2:
                yield from self.act_walk(direction, abs(edge - self.P[0]), face_front=False, events=False)
        yield from self.turn_to(90 if direction > 0 else 270, 0.06)
        self.say("要跳囉～", 1.2)
        yield from self.crouch(0.16, 0.18)
        self.platform = None
        self.work = self.base_work
        impact, _ = yield from self.airborne(direction * 0.6 * self.U, -1.6 * self.U)
        self.kick(impact)
        yield from self.settle(0.35)
        yield from self.turn_to(0)

    # ---------------------------------------------------------- drag
    def grab(self, mx, my):
        self.action = None
        self.dragging = True
        self.queue.clear()
        self.reset_pose()
        self.platform = None
        dx, dy = self.P[0] - mx, self.P[1] - my
        self.grab_o = rot2(dx, dy, -self.rot)
        self.mouse = (mx, my)
        self.m_prev = (mx, my)
        self.m_v = (0.0, 0.0)
        self.rot_v = 0.0

    def drag_to(self, mx, my):
        self.mouse = (mx, my)

    def drag_step(self):
        dt = self.dt
        mx, my = self.mouse
        nvx, nvy = (mx - self.m_prev[0]) / dt, (my - self.m_prev[1]) / dt
        self.m_prev = (mx, my)
        a = 0.5
        ovx, ovy = self.m_v
        self.m_v = (ovx + (nvx - ovx) * a, ovy + (nvy - ovy) * a)
        ax = max(-9000, min(9000, (self.m_v[0] - ovx) / dt))
        ay = max(-9000, min(9000, (self.m_v[1] - ovy) / dt))
        ox, oy = self.grab_o
        L = max(math.hypot(ox, oy), 0.15 * self.U)
        wx, wy = rot2(ox, oy, self.rot)
        beta = math.radians(wrap180(math.degrees(math.atan2(wy, wx)) - 90))
        g_eff = self.G - ay
        acc = (-(g_eff / L) * math.sin(beta) + (ax / L) * math.cos(beta)) * 57.2958 - 3.5 * self.rot_v
        self.rot_v += acc * dt
        self.rot_v = max(-1500, min(1500, self.rot_v))
        self.rot += self.rot_v * dt
        wx, wy = rot2(ox, oy, self.rot)
        self.P[0], self.P[1] = mx + wx, my + wy
        self.a["legs"] = math.sin(self.t * 6) * 0.015 * self.U
        self.a["wing"] = math.sin(self.t * 24) * 0.012 * self.U

    def release(self):
        if not self.dragging:
            return
        self.dragging = False
        U = self.U
        vx = max(-4 * U, min(4 * U, self.m_v[0]))
        vy = max(-5 * U, min(4 * U, self.m_v[1]))
        spin = max(-720, min(720, self.rot_v * 0.6 + vx * 0.15))
        self.a["legs"] = self.a["wing"] = 0.0
        lo, _ = self.extent()
        if self.P[1] + lo - self.work[1] < 0.15 * U and abs(vy) < 1.5 * U:
            self.action = self.act_hang(from_drag=True)
        else:
            self.action = self.act_fall(vx, vy, spin, keep_rot=True)


# ------------------------------------------------------------------ Win32 window
def run_app():
    import ctypes
    import ctypes.wintypes as wt
    import tkinter as tk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:  # 讓工作列用我們自己的狸貓圖示，而不是 Python 的
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Chico.PixelPet")
    except Exception:
        pass

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class POINT(ctypes.Structure):
        _fields_ = [("x", wt.LONG), ("y", wt.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = wt.HDC
    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
    gdi32.CreateDIBSection.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                                           wt.HDC, ctypes.POINTER(POINT), wt.DWORD,
                                           ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
    user32.UpdateLayeredWindow.restype = wt.BOOL
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.MonitorFromPoint.argtypes = [POINT, wt.DWORD]
    user32.MonitorFromPoint.restype = wt.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wt.UINT]

    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x80000, 0x80, 0x8
    ULW_ALPHA = 2
    HWND_TOPMOST = wt.HWND(-1)

    def work_area(pt):
        mon = user32.MonitorFromPoint(POINT(int(pt[0]), int(pt[1])), 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(mi))
        w = mi.rcWork
        return (w.left, w.top, w.right, w.bottom)

    def cursor():
        p = POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    gdi32.DeleteDC.argtypes = [wt.HDC]
    screen_dc = user32.GetDC(None)
    blend = BLENDFUNCTION(0, 0, 255, 1)

    class LWin:
        """逐像素半透明的 Tk 視窗（UpdateLayeredWindow）。"""

        def __init__(self, win):
            win.overrideredirect(True)
            win.geometry("8x8+-3000+-3000")
            win.update_idletasks()
            win.attributes("-topmost", True)
            win.update()
            self.win = win
            self.hwnd = int(win.wm_frame(), 16)
            ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
            self.dc = gdi32.CreateCompatibleDC(screen_dc)
            self.size = (0, 0)
            self.bits = None
            self.bmp = None

        def _alloc(self, w, h):
            bmi = BITMAPINFO()
            hd = bmi.bmiHeader
            hd.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            hd.biWidth, hd.biHeight = w, -h
            hd.biPlanes, hd.biBitCount = 1, 32
            bits = ctypes.c_void_p()
            bmp = gdi32.CreateDIBSection(self.dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            gdi32.SelectObject(self.dc, bmp)
            if self.bmp:
                gdi32.DeleteObject(self.bmp)
            self.size, self.bits, self.bmp = (w, h), bits, bmp
            self.win.geometry(f"{w}x{h}")

        def push(self, img, x, y, scale=1):
            """img 為原生點陣；在原生尺寸做預乘 alpha，再以最近鄰放大到螢幕尺寸。"""
            a = np.asarray(img, dtype=np.uint8)
            al = a[..., 3:4].astype(np.uint16)
            rgb = ((a[..., :3].astype(np.uint16) * al + 127) // 255).astype(np.uint8)
            out = np.empty_like(a)
            out[..., 0] = rgb[..., 2]
            out[..., 1] = rgb[..., 1]
            out[..., 2] = rgb[..., 0]
            out[..., 3] = a[..., 3]
            if scale != 1:
                if abs(scale - round(scale)) < 1e-6 and scale >= 1:
                    k = int(round(scale))
                    out = np.repeat(np.repeat(out, k, 0), k, 1)
                else:
                    nh = max(1, int(round(out.shape[0] * scale)))
                    nw = max(1, int(round(out.shape[1] * scale)))
                    out = np.asarray(Image.fromarray(out).resize((nw, nh), Image.NEAREST))
            out = np.ascontiguousarray(out)
            h, w = out.shape[:2]
            if (w, h) != self.size:
                self._alloc(w, h)
            ctypes.memmove(self.bits, out.ctypes.data, out.nbytes)
            user32.UpdateLayeredWindow(self.hwnd, screen_dc, ctypes.byref(POINT(int(x), int(y))),
                                       ctypes.byref(SIZE(w, h)), self.dc, ctypes.byref(POINT(0, 0)), 0,
                                       ctypes.byref(blend), ULW_ALPHA)

        def raise_top(self):
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

        def destroy(self):
            try:
                self.win.destroy()
            finally:
                if self.bmp:
                    gdi32.DeleteObject(self.bmp)
                gdi32.DeleteDC(self.dc)

    from PIL import ImageTk

    # ---- 視窗列舉（爬視窗用）
    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsIconic.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.WindowFromPoint.argtypes = [POINT]
    user32.WindowFromPoint.restype = wt.HWND
    user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
    user32.GetAncestor.restype = wt.HWND
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
    my_pid = os.getpid()

    def win_rect(hwnd):
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return None
        cloaked = wt.DWORD(0)
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        if cloaked.value:
            return None
        r = wt.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    def top_visible(hwnd, r):
        """視窗頂端中間是不是真的看得到（沒有被別的視窗蓋住）。"""
        x, y = (r[0] + r[2]) // 2, r[1] + 4
        h = user32.WindowFromPoint(POINT(x, y))
        return h and user32.GetAncestor(h, 2) == hwnd

    def list_windows():
        out = []

        def cb(h, _l):
            if user32.GetWindowTextLengthW(h) == 0:
                return True
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == my_pid:
                return True
            if user32.GetWindowLongPtrW(h, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            r = win_rect(h)
            if r and r[2] - r[0] > 60 and r[3] - r[1] > 60 and top_visible(h, r):
                out.append((h, r))
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return out

    # ---- 主角
    def log_error(*_args):
        """打包成 exe（沒有主控台）時，把錯誤寫到 %APPDATA%/ChicoPet/error.log。"""
        import traceback

        try:
            path = Path(os.environ.get("APPDATA", str(APP_DIR))) / "ChicoPet" / "error.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fp:
                fp.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
        except Exception:
            pass

    root = tk.Tk()
    # 對話框、按鈕、輸入框都用 Cubic 11 點陣字（只在這個程式內註冊，不安裝到系統）
    try:
        ctypes.windll.gdi32.AddFontResourceExW(str(FONT_PATH), 0x10, 0)
    except Exception:
        pass
    # 主屋按鈕用原生 11px（跟朵莉姆 9pt 差不多緊）；獨立對話框才用 2 倍字
    UI_FONT = ("Cubic 11", -11)
    UI_FONT_LG = ("Cubic 11", -22)
    UI_BG, UI_FILL, UI_LINE, UI_LINE2 = "#d8f4ee", "#fff9e0", "#3aa89a", "#c8efe6"  # 藍綠＋檸檬黃
    UI_HOVER, UI_TEXT, UI_HI = "#ffe9a0", "#1f5f5a", "#c9a014"

    def pix_box(parent, fill=UI_FILL, pad=1):
        """點陣風雙框：外框藍綠、內框薄荷；pad=1 時跟朵莉姆按鈕一樣扁。"""
        outer = tk.Frame(parent, bg=UI_LINE, bd=0)
        gap = tk.Frame(outer, bg=fill, bd=0)
        gap.pack(fill="both", expand=True, padx=pad, pady=pad)
        line2 = tk.Frame(gap, bg=UI_LINE2, bd=0)
        line2.pack(fill="both", expand=True, padx=pad, pady=pad)
        inner = tk.Frame(line2, bg=fill, bd=0)
        inner.pack(fill="both", expand=True, padx=pad, pady=pad)
        return outer, inner

    def pix_button(parent, text, command, selected=None, font=None, pad=1):
        """點陣按鈕：點陣框＋點陣字，滑鼠移上去變亮。selected() 回傳 True 時顯示成選取中。"""
        outer, inner = pix_box(parent, pad=pad)
        lab = tk.Label(inner, text=text, font=font or UI_FONT, bg=UI_FILL, fg=UI_TEXT,
                       cursor="hand2", padx=2, pady=0)
        lab.pack(fill="both", expand=True)

        def paint(hover=False):
            on = selected() if selected else False
            bg = UI_HOVER if (hover or on) else UI_FILL
            lab.configure(bg=bg, fg=UI_HI if (hover or on) else UI_TEXT)
            inner.configure(bg=bg)

        for wdg in (outer, inner, lab):
            wdg.bind("<Enter>", lambda _e: paint(True))
            wdg.bind("<Leave>", lambda _e: paint(False))
            wdg.bind("<ButtonRelease-1>", lambda _e: (command(), paint(True)))
        paint()
        outer.repaint = paint
        return outer

    def pix_entry(parent, width, font=None, pad=1):
        outer, inner = pix_box(parent, pad=pad)
        e = tk.Entry(inner, width=width, font=font or UI_FONT, bg=UI_FILL, fg=UI_TEXT,
                     insertbackground=UI_HI, relief="flat", bd=0, highlightthickness=0)
        e.pack(fill="both", expand=True, padx=1, pady=0)
        return outer, e
    root.report_callback_exception = lambda *a: log_error()
    root.title(f"{PET_NAME} 桌寵")
    # 所有視窗（甜點屋、對話框）的圖示都換成小狸貓
    icons = [ImageTk.PhotoImage(tanuki_icon(n), master=root) for n in (16, 32, 48, 64)]
    root.iconphoto(True, *icons)
    root._tanuki_icons = icons
    pet_win = LWin(root)

    data_dir = Path(os.environ.get("APPDATA", str(ROOT))) / "ChicoPet"
    state = {"press": None, "dragged": False, "skip_release": False, "last": time.perf_counter(),
             "topmost_t": 0.0, "garden_t": 0.0, "home_t": 0.0}
    outfit_save = data_dir / "outfit.json"
    try:
        outfit = json.loads(outfit_save.read_text(encoding="utf-8"))["outfit"]
        if outfit not in OUTFITS:
            outfit = DEFAULT_OUTFIT
    except Exception:
        outfit = DEFAULT_OUTFIT
    rig = Rig(SCALE, load_outfit(outfit), sleeve_colors(outfit))
    pet = Pet(rig, work_area)
    cur = {"outfit": outfit}
    pet.care = Care(data_dir / "state.json")
    pet.windows_fn = list_windows
    pet.win_rect_fn = win_rect

    # ---- 零食（她邊走邊扔；點一下可以收掉）
    save_path = data_dir / "snacks.json"

    class Snacks:
        def __init__(self):
            self.items: list[dict] = []
            try:
                for d in json.loads(save_path.read_text(encoding="utf-8")):
                    if time.time() - float(d["t0"]) < SNACK_LIFE_S and d["kind"] in S.SNACKS:
                        self.add(float(d["x"]), float(d["y"]), 0.0, 0.0, d["kind"], float(d["t0"]), save=False)
            except Exception:
                pass

        def save(self):
            try:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                data = [{"x": it["x"], "y": it["y"], "kind": it["kind"], "t0": it["t0"]} for it in self.items]
                save_path.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass

        def add(self, x, y, vx=0.0, vy=0.0, kind=None, t0=None, save=True):
            while len(self.items) >= MAX_SNACKS:
                self.remove(self.items[0], save=False)
            it = {"x": x, "y": y, "vx": vx, "vy": vy, "kind": kind or random.choice(list(S.SNACKS)),
                  "t0": t0 if t0 is not None else time.time(), "key": None, "bounced": False}
            raw = Image.fromarray(S.snack(it["kind"]))
            k = SNACK_DISPLAY / max(raw.width, raw.height)
            it["img"] = raw.resize((max(1, int(round(raw.width * k))),
                                    max(1, int(round(raw.height * k)))), Image.NEAREST)
            it["win"] = LWin(tk.Toplevel(root))
            it["win"].win.bind("<ButtonPress-1>", lambda _e, it=it: self.remove(it))
            self.items.append(it)
            pet_win.raise_top()
            if save:
                self.save()

        def remove(self, it, save=True):
            if it in self.items:
                self.items.remove(it)
                it["win"].destroy()
                if save:
                    self.save()

        def clear(self):
            for it in list(self.items):
                self.remove(it, save=False)
            self.save()

        def update(self, dt):
            now = time.time()
            moved = False
            for it in list(self.items):
                age = now - it["t0"]
                if age > SNACK_LIFE_S:
                    self.remove(it, save=False)
                    moved = True
                    continue
                l, t, r, b = work_area((it["x"], it["y"] - 10))
                if it["vy"] != 0.0 or it["y"] < b:
                    it["vy"] += pet.G * dt
                    it["x"] = min(max(it["x"] + it["vx"] * dt, l + 12), r - 12)
                    it["y"] += it["vy"] * dt
                    if it["y"] >= b:
                        it["y"] = b
                        if not it["bounced"] and it["vy"] > 200:
                            it["vy"], it["vx"], it["bounced"] = -it["vy"] * 0.3, it["vx"] * 0.4, True
                        else:
                            it["vy"] = it["vx"] = 0.0
                            moved = True
                else:
                    it["y"] = b
                blink = SNACK_LIFE_S - age < 8 and int(age * 6) % 2
                key = (int(it["x"]), int(it["y"]), blink)
                if key == it["key"]:
                    continue
                it["key"] = key
                img = EMPTY if blink else it["img"]
                it["win"].push(img, it["x"] - img.width / 2, it["y"] - img.height, 1)
            if moved:
                self.save()

    EMPTY = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    snacks = Snacks()
    pet.on_snack = lambda x, y, vx, vy: snacks.add(x, y, vx, vy)

    # ---- 說話泡泡
    bubble = LWin(tk.Toplevel(root))
    bub = {"text": None, "img": None, "shown": False}

    # ---- 聲音（Windows 內建 winsound 播放合成好的 wav）
    sound = {"on": True}

    def wav_file(name, data):
        import wave

        path = data_dir / f"{name}.wav"
        if not path.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(data)
        return path

    def play_sound(name):
        try:
            import winsound

            if name is None or not sound["on"]:
                winsound.PlaySound(None, 0)
                return
            data = DANCE_TUNE[0]
            import zlib

            tag = f"{zlib.crc32(data):08x}"  # 曲子改了就換檔名，不會一直播舊的
            winsound.PlaySound(str(wav_file(f"music_{name}_{tag}", data)), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass

    pet.on_sound = play_sound

    # ---- 玩具：月光兔布偶（可以拖、會掉下來）
    class ToyBox:
        def __init__(self):
            self.items = []  # (Toy, LWin, state)

        def add(self, kind):
            if any(tt.kind == kind for tt, _w, _s in self.items):
                pet.say("已經拿出來了喔～", 1.2)
                return
            l, t, r, b = pet.base_work
            x = min(max(pet.P[0] + random.choice([-1, 1]) * 0.8 * pet.U, l + 40), r - 40)
            toy = Toy(kind, x, t + 0.3 * (b - t))
            win = LWin(tk.Toplevel(root))
            st = {"key": None, "drag": None, "last": None, "v": (0.0, 0.0)}
            win.win.bind("<ButtonPress-1>", lambda _e, toy=toy, st=st: self.press(toy, st))
            win.win.bind("<B1-Motion>", lambda _e, toy=toy, st=st: self.motion(toy, st))
            win.win.bind("<ButtonRelease-1>", lambda _e, toy=toy, st=st: self.release(toy, st))
            self.items.append((toy, win, st))
            pet.toys.append(toy)
            pet_win.raise_top()

        def clear(self):
            for toy, win, _st in self.items:
                win.destroy()
            self.items.clear()
            pet.toys.clear()

        def press(self, toy, st):
            mx, my = cursor()
            toy.held = True
            st["drag"] = (toy.x - mx, toy.y - my)
            st["last"] = (mx, my, time.perf_counter())
            st["v"] = (0.0, 0.0)

        def motion(self, toy, st):
            if not st["drag"]:
                return
            mx, my = cursor()
            now = time.perf_counter()
            lx, ly, lt = st["last"]
            dt = max(now - lt, 1e-3)
            st["v"] = (0.6 * st["v"][0] + 0.4 * (mx - lx) / dt, 0.6 * st["v"][1] + 0.4 * (my - ly) / dt)
            st["last"] = (mx, my, now)
            toy.x, toy.y = mx + st["drag"][0], my + st["drag"][1]

        def release(self, toy, st):
            if not st["drag"]:
                return
            st["drag"] = None
            toy.held = False
            lim = 5 * pet.U
            toy.vx = max(-lim, min(lim, st["v"][0]))
            toy.vy = max(-lim, min(lim, st["v"][1]))

        def update(self, dt):
            for toy, win, st in self.items:
                toy.step(dt, work_area((toy.x, toy.y - 10)), pet.G)
                if toy.carried:
                    if st["key"] != "hidden":
                        win.push(EMPTY, -3000, -3000)
                        st["key"] = "hidden"
                    continue
                img = toy.image()
                key = (int(toy.x), int(toy.y), toy.view())
                if key != st["key"]:
                    st["key"] = key
                    win.push(img, toy.x - img.width * SCALE / 2, toy.y - img.height * SCALE, SCALE)

    toybox = ToyBox()


    def update_bubble():
        sp = pet.speech
        if sp and pet.t > sp[1]:
            pet.speech = sp = None
        if sp is None:
            if bub["shown"]:
                bubble.push(EMPTY, -3000, -3000)
                bub["shown"], bub["text"] = False, None
            return
        if sp[0] != bub["text"]:
            bub["text"], bub["img"] = sp[0], render_bubble(sp[0])
        img = bub["img"]
        w, h = img.width * BUBBLE_SCALE, img.height * BUBBLE_SCALE
        l, t, r, b = pet.base_work
        x = min(max(pet.P[0] - w / 2, l), r - w)
        y = max(pet.P[1] + pet.extent()[0] - h + 4, t)
        bubble.push(img, x, y, BUBBLE_SCALE)
        if not bub["shown"]:
            bubble.raise_top()
        bub["shown"] = True

    # ---- 動作
    actions = {
        "eat": pet.act_eat, "bath": pet.act_bath, "sleep": pet.act_sleep, "climb": pet.act_climb,
        "bounce": pet.act_bounce, "frontflip": pet.act_frontflip, "spin": lambda: pet.act_spin(1),
        "plant": pet.act_plant, "hang": pet.act_hang, "walk": pet.act_walk, "trip": pet.act_trip,
        "jump_down": pet.act_jump_down, "look": pet.act_look, "somersault": pet.act_somersault,
        "walk_l": lambda: pet.act_walk(-1, 4 * pet.U), "walk_r": lambda: pet.act_walk(1, 4 * pet.U),
        "dance": pet.act_dance, "plush": pet.act_hug_plush,
        "toss": pet.act_toss_plush,
        "wish": pet.act_wish,
    }

    def do_action(name):
        if name == "wake":
            if pet.sleeping:
                pet.wake_req = True
            else:
                pet.say("我醒著啦！")
            return
        if name == "sleep" and pet.sleeping:
            return
        if name == "talk":  # 打開甜點屋
            open_home()
            pet.say("歡迎來我家！剛好烤好餅乾了～", 2.2)
            return
        if name == "toys_off":
            toybox.clear()
            return
        if name == "toy_plush":
            toybox.add("plush")
            return
        if name in ("plush", "toss") and not any(tt.kind == "plush" for tt in pet.toys):
            toybox.add("plush")
        if name == "outfit":
            names = list(OUTFITS)
            set_outfit(names[(names.index(cur["outfit"]) + 1) % len(names)])
            return
        if name in ("game", "stars"):
            open_game("bubble" if name == "game" else "stars")
            return
        if name == "jump_down" and not pet.platform:
            pet.say("我已經在地上了～")
            return
        if name == "climb" and pet.platform:
            pet.say("我已經在上面了！")
            return
        pet.run(actions[name]())

    def talk(text):
        reply, act = respond(text)
        pet.say(reply)
        if pet.care:
            pet.care.add("mood", 1)
        if act:
            root.after(900, lambda: do_action(act))

    # ---- 跟她說話（小對話框）
    chat = {"win": None}

    def open_chat():
        if chat["win"] is not None and chat["win"].winfo_exists():
            chat["win"].deiconify()
            chat["win"].lift()
            return
        w = tk.Toplevel(root)
        w.title(f"跟{PET_NAME}說話")
        w.attributes("-topmost", True)
        w.configure(bg=UI_BG)
        w.resizable(False, False)
        box, e = pix_entry(w, 18, font=UI_FONT_LG, pad=2)
        box.pack(side="left", padx=(8, 4), pady=8)

        def send(_e=None):
            text = e.get().strip()
            e.delete(0, "end")
            if text:
                talk(text)

        e.bind("<Return>", send)
        pix_button(w, "說", send, font=UI_FONT_LG, pad=2).pack(side="left", padx=(0, 8), pady=8, fill="y")
        l, t, r, b = pet.base_work
        w.geometry(f"+{int(min(max(pet.P[0] - 160, l), r - 340))}+{int(max(pet.P[1] - 2.2 * pet.U, t))}")
        e.focus_set()
        chat["win"] = w

    # ---- 夢幻甜點屋（背景與照顧面板；畫布尺寸跟朵莉姆山谷一樣：200×125 → 顯示 400×250）
    HS = 2  # 山谷畫面放大倍率
    VW, VH = 200, 125
    # 朵莉姆山谷貼的是 WIN_N=112 的原生畫格；Chico 是 134，整格縮到一樣大
    HOME_PET_SCALE = 112 / WIN_N
    HOME_WIN_N = WIN_N * HOME_PET_SCALE  # = 112
    home = {"win": None, "canvas": None, "photo": None}
    bar_colors = {"hunger": (255, 210, 90), "clean": (96, 210, 196), "mood": (255, 226, 120),
                  "energy": (70, 170, 160)}

    def open_home():
        if home["win"] is not None and home["win"].winfo_exists():
            home["win"].deiconify()
            home["win"].lift()
            return
        w = tk.Toplevel(root)
        w.title(f"夢幻甜點屋 — {PET_NAME}")
        w.configure(bg=UI_BG)
        w.resizable(False, False)
        cv = tk.Canvas(w, width=VW * HS, height=VH * HS, highlightthickness=0, bg="#000000", cursor="hand2")
        cv.pack()
        cv.bind("<ButtonPress-1>", valley_press)
        cv.bind("<Motion>", valley_motion)
        cv.bind("<B1-Motion>", valley_motion)
        cv.bind("<ButtonRelease-1>", valley_release)
        # 下方按鈕區間距／字級對齊朵莉姆山谷（畫布寬 400，整窗不應被按鈕撐寬）
        btns = tk.Frame(w, bg=UI_BG)
        btns.pack(fill="x", padx=4, pady=(4, 1))
        for i, (label, act) in enumerate((("餵食", "eat"), ("洗澡", "bath"), ("睡覺", "sleep"), ("叫醒", "wake"),
                                          ("爬視窗", "climb"), ("跳下來", "jump_down"), ("扔零食", "plant"),
                                          ("跌倒", "trip"), ("泡泡射擊", "game"), ("接點心", "stars"),
                                          ("跳舞", "dance"),
                                          ("抱狸貓", "plush"), ("拋狸貓", "toss"), ("收玩具", "toys_off"),
                                          ("許願", "wish"))):
            pix_button(btns, label, (lambda a=act: do_action(a))).grid(
                row=i // 5, column=i % 5, padx=1, pady=1, sticky="ew")
        for c in range(5):
            btns.grid_columnconfigure(c, weight=1, uniform="home")
        orow = tk.Frame(w, bg=UI_BG)
        orow.pack(fill="x", padx=4, pady=(1, 1))
        tk.Label(orow, text="換裝", bg=UI_BG, fg=UI_TEXT, font=UI_FONT).pack(side="left")
        om = tk.OptionMenu(orow, outfit_var, *OUTFITS.keys(), command=lambda n: set_outfit(n))
        om.configure(bg=UI_FILL, fg=UI_TEXT, activebackground=UI_HOVER, activeforeground=UI_HI,
                     relief="flat", highlightthickness=0, font=UI_FONT)
        om["menu"].configure(bg=UI_FILL, fg=UI_TEXT, font=UI_FONT)
        om.pack(side="left", fill="x", expand=True, padx=(4, 0))
        row = tk.Frame(w, bg=UI_BG)
        row.pack(fill="x", padx=4, pady=(1, 5))
        ebox, e = pix_entry(row, 10)
        ebox.pack(side="left", fill="x", expand=True)

        def send(_e=None):
            text = e.get().strip()
            e.delete(0, "end")
            if text:
                talk(text)

        e.bind("<Return>", send)
        pix_button(row, "說話", send).pack(side="left", padx=(4, 0), fill="y")

        def close():
            w.destroy()
            home["win"] = None

        w.protocol("WM_DELETE_WINDOW", close)
        home.update(win=w, canvas=cv)
        # 鎖成畫布寬，避免字型／按鈕把視窗撐得比朵莉姆大
        w.update_idletasks()
        w.geometry(f"{VW * HS}x{w.winfo_reqheight()}")
        render_home()

    # ---- 小遊戲：泡泡射擊（Unity）／接星星（Unity，沒有建置時用 Python 版）
    game = {"win": None, "photo": None, "sprites": None, "kind": None}
    GS = 2
    game_save = data_dir / "game.json"
    GAMES = {"stars": StarCatchGame}

    def load_bests():
        try:
            d = json.loads(game_save.read_text(encoding="utf-8"))
            return d
        except Exception:
            return {}

    unity = {"proc": None, "result": data_dir / "unity_result.json", "kind": None}

    def open_unity_game(kind):
        """Unity 版小遊戲（unity/Build/ChicoGames.exe）：帶入目前的衣服，關掉後讀成績。"""
        import subprocess

        if unity["proc"] is not None and unity["proc"].poll() is None:
            pet.say("已經在玩了啦～", 1.4)
            return True
        try:
            unity["result"].unlink(missing_ok=True)
            outfit_idx = list(OUTFITS).index(cur["outfit"])
            # 打包成無主控台的 exe 時沒有有效的標準輸入輸出，要明確導到 DEVNULL
            unity["proc"] = subprocess.Popen([str(UNITY_EXE), "-game", kind, "-outfit", str(outfit_idx),
                                              "-result", str(unity["result"])], cwd=str(UNITY_EXE.parent),
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
            unity["kind"] = kind
            pet.say("來射泡泡吧！" if kind == "bubble" else "一起接點心！", 1.4)
            return True
        except Exception:
            log_error()
            return False

    def check_unity_game():
        pr = unity["proc"]
        if pr is None or pr.poll() is None:
            return
        unity["proc"] = None
        try:
            rounds = json.loads(unity["result"].read_text(encoding="utf-8")).get("rounds", [])
        except Exception:
            rounds = []
        if not rounds:
            return
        mood = 0
        for r in rounds:
            if r.get("game") == "bubble":
                mood += 2 + int(r.get("score", 0)) // 300
            else:
                mood += 2 + int(r.get("score", 0)) // 4
                if pet.care:
                    pet.care.add("hunger", min(10, int(r.get("score", 0)) // 3))
        if pet.care:
            pet.care.add("mood", min(20, mood))
        last = rounds[-1]
        if last.get("game") == "bubble":
            pet.say(f"拿到 {last.get('score', 0)} 分！" + ("全部清光光～" if any(r.get("reached") for r in rounds) else "下次會更好！"))
        else:
            pet.say(f"接到 {last.get('score', 0)} 個點心！好飽～")

    def open_game(kind="bubble"):
        if UNITY_EXE.exists() and open_unity_game(kind):
            return
        if kind not in GAMES:
            pet.say("泡泡射擊還沒建置好耶…", 1.8)
            return
        if game["win"] is not None and game["win"].winfo_exists():
            if game["kind"] == kind:
                game["win"].deiconify()
                game["win"].lift()
                game["win"].focus_force()
                return
            game["win"].destroy()
        if game["sprites"] is None:
            game["sprites"] = make_small_sprites(load_outfit(cur["outfit"]))
        cls = GAMES[kind]
        w = tk.Toplevel(root)
        w.title(cls.TITLE)
        w.configure(bg="#06060a")
        w.resizable(False, False)
        cv = tk.Canvas(w, width=cls.W * GS, height=cls.H * GS, highlightthickness=0, bg="#000000")
        cv.pack()
        tk.Label(w, text=cls.HELP, bg=UI_BG, fg=UI_TEXT, font=UI_FONT).pack(pady=(2, 4))
        g = cls(game["sprites"], int(load_bests().get(cls.SAVE_KEY, 0)))
        keys = set()
        w.bind("<KeyPress>", lambda e: keys.add(e.keysym.lower()))
        w.bind("<KeyRelease>", lambda e: keys.discard(e.keysym.lower()))
        w.bind("<space>", lambda _e: g.click())
        cv.bind("<Motion>", lambda e: setattr(g, "mouse", e.x / GS))
        cv.bind("<Leave>", lambda _e: setattr(g, "mouse", None))
        cv.bind("<Button-1>", lambda _e: g.click())
        game.update(win=w, kind=kind)
        pet.say("一起接點心！", 1.4)

        def game_over():
            d = load_bests()
            d[cls.SAVE_KEY] = g.best
            try:
                game_save.parent.mkdir(parents=True, exist_ok=True)
                game_save.write_text(json.dumps(d), encoding="utf-8")
            except Exception:
                pass
            if pet.care:
                pet.care.add("mood", min(12, 2 + g.score // 4))
                pet.care.add("hunger", min(10, g.score // 3))
                pet.say(f"接到 {g.score} 顆星星！")

        def loop():
            if not w.winfo_exists():
                if game["win"] is w:
                    game["win"] = None
                return
            dx = (1 if keys & {"right", "d"} else 0) - (1 if keys & {"left", "a"} else 0)
            if dx:
                g.mouse = None
            g.step(1 / 30, dx)
            if g.just_over:
                game_over()
            ph = ImageTk.PhotoImage(g.render().resize((cls.W * GS, cls.H * GS), Image.NEAREST))
            cv.delete("all")
            cv.create_image(0, 0, anchor="nw", image=ph)
            game["photo"] = ph
            w.after(33, loop)

        w.focus_force()
        loop()

    # ---- 換裝
    def set_outfit(name, animate=True):
        if name not in OUTFITS:
            return
        cur["outfit"] = name
        pet.set_rig(Rig(SCALE, load_outfit(name), sleeve_colors(name)))
        game["sprites"] = None
        try:
            outfit_save.parent.mkdir(parents=True, exist_ok=True)
            outfit_save.write_text(json.dumps({"outfit": name}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        if outfit_var.get() != name:
            outfit_var.set(name)
        if animate:
            pet.run(pet.act_change())

    outfit_var = tk.StringVar(value=cur["outfit"])

    # ---- 在甜點屋點她：短按打招呼；按住拖動才是抓起來移動
    vdrag = {"on": False, "press": None}

    def valley_to_screen(vx, vy):
        l, t, r, b = pet.base_work
        floor_y = int(VH * 0.86)
        return (l + (vx - 26) / (VW - 52) * (r - l),
                pet.work[3] - (floor_y - vy) * (rig.s / HOME_PET_SCALE))

    def valley_press(e):
        vx, vy = e.x / HS, e.y / HS
        home["canvas"].focus_set()
        cx, cy = home.get("pet_xy", (-99, -99))
        if abs(vx - cx) < 18 and abs(vy - cy) < 30:
            vdrag["press"] = (vx, vy)

    def valley_motion(e):
        vx, vy = e.x / HS, e.y / HS
        if vdrag["press"] and not vdrag["on"]:
            px, py = vdrag["press"]
            if abs(vx - px) + abs(vy - py) > 3:
                vdrag["on"] = True
                pet.grab(*valley_to_screen(px, py))
                pet.say("哇！", 1.0)
        if vdrag["on"]:
            pet.drag_to(*valley_to_screen(vx, vy))

    def valley_release(_e):
        if vdrag["on"]:
            vdrag["on"] = False
            pet.release()
        elif vdrag["press"]:
            pet.say("歡迎來我家！剛好烤好餅乾了～", 2.2)
            if pet.care:
                pet.care.add("mood", 2)
        vdrag["press"] = None

    def render_home():
        if home["win"] is None:
            return
        t = pet.t
        bg = draw_sweets(t, VW, VH)
        img, _, _ = pet.frame()
        if abs(HOME_PET_SCALE - 1) > 1e-6:
            nw = max(1, int(round(img.width * HOME_PET_SCALE)))
            nh = max(1, int(round(img.height * HOME_PET_SCALE)))
            img = img.resize((nw, nh), Image.NEAREST)
        s_ = rig.s
        l, t, r, b = pet.base_work
        floor_y = int(VH * 0.86)
        above = (pet.work[3] - pet.P[1]) / s_ * HOME_PET_SCALE
        cx = 26 + (pet.P[0] - l) / max(r - l, 1) * (VW - 52)
        cy = max(floor_y - above, 22)
        ox, oy = int(round(cx - HOME_WIN_N / 2)), int(round(cy - HOME_WIN_N / 2))
        bg.paste(img, (ox, oy), img)
        home["pet_xy"] = (cx, cy)
        d = ImageDraw.Draw(bg)
        d.fontmode = "1"
        font = pixel_font(11)
        d.rectangle((3, 3, 74, 58), fill=(255, 249, 224, 255), outline=(58, 168, 154, 255))
        for i, k in enumerate(CARE_KEYS):
            y = 6 + i * 13
            d.text((6, y), CARE_NAMES[k], font=font, fill=(31, 95, 90, 255))
            d.rectangle((32, y + 3, 70, y + 8), fill=(200, 239, 230, 255))
            v = pet.care.v[k] if pet.care else 0
            if v > 0:
                d.rectangle((32, y + 3, 32 + int(38 * v / 100), y + 8), fill=bar_colors[k] + (255,))
        if pet.speech:
            bb = render_bubble(pet.speech[0], 11)
            head_y = cy + pet.extent()[0] / s_ * HOME_PET_SCALE
            bg.alpha_composite(bb, (int(max(0, min(VW - bb.width, cx - bb.width / 2))),
                                    int(max(0, head_y - bb.height))))
        photo = ImageTk.PhotoImage(bg.resize((VW * HS, VH * HS), Image.NEAREST))
        cv = home["canvas"]
        cv.delete("all")
        cv.create_image(0, 0, anchor="nw", image=photo)
        home["photo"] = photo

    # ---- 滑鼠
    def on_press(_e):
        state["press"] = cursor()
        state["dragged"] = False

    def on_motion(_e):
        if state["press"] is None:
            return
        mx, my = cursor()
        if not state["dragged"]:
            px, py = state["press"]
            if abs(mx - px) + abs(my - py) < 5:
                return
            state["dragged"] = True
            pet.grab(px, py)
            pet.say("哇～飛起來了！", 1.4)
        pet.drag_to(mx, my)

    def on_release(_e):
        state["press"] = None
        if state["dragged"]:
            pet.release()
        elif state["skip_release"]:
            state["skip_release"] = False
        elif pet.sleeping:
            pet.wake_req = True
        else:
            pet.say(random.choice(LINES["click"]))
            if pet.care:
                pet.care.add("mood", 2)
            pet.run(pet.act_tilt())
        state["dragged"] = False

    def on_double(_e):
        state["skip_release"] = True
        open_home()

    # ---- 右鍵選單
    menu = tk.Menu(root, tearoff=0)
    auto_var = tk.BooleanVar(value=True)
    look_var = tk.BooleanVar(value=True)
    sound_var = tk.BooleanVar(value=True)
    follow_var = tk.BooleanVar(value=True)

    def do(name):
        return lambda: do_action(name)

    menu.add_command(label="打開夢幻甜點屋", command=open_home)
    menu.add_command(label="跟她說話…", command=open_chat)
    menu.add_command(label="小遊戲：泡泡射擊", command=lambda: open_game("bubble"))
    menu.add_command(label="小遊戲：接點心", command=lambda: open_game("stars"))
    menu.add_separator()
    menu.add_command(label="餵食", command=do("eat"))
    menu.add_command(label="洗澡", command=do("bath"))
    menu.add_command(label="睡覺", command=do("sleep"))
    menu.add_command(label="叫醒", command=do("wake"))
    menu.add_command(label="爬視窗", command=do("climb"))
    menu.add_command(label="從視窗跳下來", command=do("jump_down"))
    menu.add_command(label="跌倒", command=do("trip"))
    menu.add_command(label="跳舞", command=do("dance"))
    menu.add_command(label="許願", command=do("wish"))
    toys_menu = tk.Menu(menu, tearoff=0)
    toys_menu.add_command(label="拿出小狸貓", command=do("toy_plush"))
    toys_menu.add_command(label="抱小狸貓", command=do("plush"))
    toys_menu.add_command(label="拋小狸貓", command=do("toss"))
    toys_menu.add_separator()
    toys_menu.add_command(label="收起玩具", command=lambda: toybox.clear())
    menu.add_cascade(label="玩具", menu=toys_menu)
    menu.add_separator()
    more = tk.Menu(menu, tearoff=0)
    for label, name in (("往左走", "walk_l"), ("往右走", "walk_r"), ("轉一圈", "spin"), ("東張西望", "look"),
                        ("彈跳", "bounce"), ("前空翻", "frontflip"), ("側翻", "somersault"), ("倒吊", "hang"),
                        ("扔零食", "plant")):
        more.add_command(label=label, command=do(name))
    menu.add_cascade(label="更多動作", menu=more)
    wardrobe = tk.Menu(menu, tearoff=0)
    for name in OUTFITS:
        wardrobe.add_radiobutton(label=name, value=name, variable=outfit_var, command=lambda n=name: set_outfit(n))
    menu.add_cascade(label="換裝", menu=wardrobe)
    menu.add_command(label="清掉地上的零食", command=lambda: snacks.clear())
    menu.add_separator()

    def toggle_auto():
        pet.auto = auto_var.get()

    def toggle_look():
        pet.look_enabled = look_var.get()

    def toggle_follow():
        pet.follow_enabled = follow_var.get()

    def quit_app():
        play_sound(None)
        snacks.save()
        if pet.care:
            pet.care.save()
        root.destroy()

    menu.add_checkbutton(label="視線跟著滑鼠", variable=look_var, command=toggle_look)

    def toggle_sound():
        sound["on"] = sound_var.get()
        if not sound["on"]:
            play_sound(None)

    menu.add_checkbutton(label="聲音", variable=sound_var, command=toggle_sound)
    menu.add_checkbutton(label="跟著滑鼠走", variable=follow_var, command=toggle_follow)
    menu.add_checkbutton(label="自動行動", variable=auto_var, command=toggle_auto)
    autostart_var = tk.BooleanVar(value=autostart_enabled())

    def toggle_autostart():
        ok = set_autostart(autostart_var.get())
        autostart_var.set(autostart_enabled())
        if ok:
            pet.say("每天開機都能見到我囉！" if autostart_var.get() else "好～", 1.6)

    menu.add_checkbutton(label="開機自動啟動", variable=autostart_var, command=toggle_autostart)
    menu.add_separator()
    menu.add_command(label="關閉", command=quit_app)

    def on_menu(_e):
        x, y = cursor()
        menu.tk_popup(x, y)
        menu.grab_release()

    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_motion)
    root.bind("<ButtonRelease-1>", on_release)
    root.bind("<Double-Button-1>", on_double)
    root.bind("<ButtonPress-3>", on_menu)
    root.protocol("WM_DELETE_WINDOW", quit_app)

    def tick():
        now = time.perf_counter()
        dt = min(max(now - state["last"], 1 / 240), 1 / 15)
        state["last"] = now
        try:
            pet.cursor_pos = cursor()
            toybox.update(dt)
            snacks.update(dt)
            pet.step(dt)
            img, x, y = pet.frame()
            pet_win.push(img, x, y, rig.s)
            update_bubble()
            state["garden_t"] += dt
            if state["garden_t"] > 0.15:
                state["garden_t"] = 0.0
                check_unity_game()
            state["home_t"] += dt
            if state["home_t"] > 0.12:
                state["home_t"] = 0.0
                render_home()
            state["topmost_t"] += dt
            if state["topmost_t"] > 2.0:
                state["topmost_t"] = 0.0
                pet_win.raise_top()
                if bub["shown"]:
                    bubble.raise_top()
        except Exception:
            log_error()
        spent = (time.perf_counter() - now) * 1000
        root.after(max(1, int(33 - spent)), tick)

    root.after(10, tick)
    if "--home" in sys.argv:
        root.after(600, open_home)
    if "--do" in sys.argv:  # 測試用：啟動後直接做某個動作，例如 --do eat
        i = sys.argv.index("--do")
        if i + 1 < len(sys.argv) and (sys.argv[i + 1] in actions or sys.argv[i + 1] in ("game", "stars", "wake", "outfit", "talk",
                                                                       "toy_plush")):
            root.after(2500, lambda: do_action(sys.argv[i + 1]))
    root.mainloop()


# ------------------------------------------------------------------ headless demo
def run_demo(out_path: str):
    rig = Rig(SCALE, load_outfit(DEFAULT_OUTFIT), sleeve_colors(DEFAULT_OUTFIT))
    WA = (0, 0, 900, 460)
    FAKE_WIN = (470, 250, 760, 460)  # 示範用的假視窗
    pet = Pet(rig, lambda _p: WA)
    pet.auto = False
    pet.P = [200.0, 150.0]
    pet.care = Care(None)
    pet.windows_fn = lambda: [(1, FAKE_WIN)]
    pet.win_rect_fn = lambda _h: FAKE_WIN
    snacks = []  # [x, y, vx, vy, kind]
    pet.on_snack = lambda x, y, vx, vy: snacks.append([x, y, vx, vy, random.choice(list(S.SNACKS))])
    toy = Toy("plush", 320.0, WA[3])
    pet.toys.append(toy)
    script = [
        ("look-at-mouse", lambda: pet.act_idle(2.4)),
        ("walk", lambda: pet.act_walk(1, 1.2 * pet.U, events=False)),
        ("snack", lambda: pet.act_plant()),
        ("hug", lambda: pet.act_hug_plush()),
        ("toss", lambda: pet.act_toss_plush()),
        ("bounce", lambda: pet.act_bounce()),
        ("eat", lambda: pet.act_eat()),
        ("bath", lambda: pet.act_bath()),
        ("sleep", lambda: pet.act_sleep(2.5)),
        ("trip", lambda: pet.act_trip()),
        ("climb", lambda: pet.act_climb()),
        ("on-window", lambda: pet.act_walk(1, 0.6 * pet.U, events=False)),
        ("jump_down", lambda: pet.act_jump_down(1)),
        ("frontflip", lambda: pet.act_frontflip()),
    ]
    frames = []
    stamps = []
    dt = 1 / 30
    bg = Image.new("RGBA", (WA[2], WA[3] + 20), (206, 214, 232, 255))
    dbg = ImageDraw.Draw(bg)
    dbg.rectangle((0, WA[3], WA[2], WA[3] + 20), fill=(120, 128, 150, 255))
    dbg.rectangle(FAKE_WIN, fill=(240, 240, 246, 255), outline=(90, 90, 110, 255))
    dbg.rectangle((FAKE_WIN[0], FAKE_WIN[1], FAKE_WIN[2], FAKE_WIN[1] + 18), fill=(60, 64, 90, 255))

    def snap(label, i):
        img, x, y = pet.frame()
        img = img.resize((img.width * rig.s, img.height * rig.s), Image.NEAREST)
        if i % 2 == 0:
            f = bg.copy()
            for sx_, sy_, _vx, _vy, kind in snacks:
                sn = Image.fromarray(S.snack(kind))
                sn = sn.resize((sn.width * rig.s, sn.height * rig.s), Image.NEAREST)
                f.alpha_composite(sn, (int(sx_ - sn.width / 2), int(sy_ - sn.height)))
            if not toy.carried:
                ti = toy.image()
                ti = ti.resize((ti.width * rig.s, ti.height * rig.s), Image.NEAREST)
                f.paste(ti, (int(toy.x - ti.width / 2), int(toy.y - ti.height)), ti)
            f.alpha_composite(img, (x, y)) if 0 <= x and 0 <= y else f.paste(img, (x, y), img)
            if pet.speech and pet.t < pet.speech[1]:
                bb = render_bubble(pet.speech[0])
                bb = bb.resize((bb.width * rig.s, bb.height * rig.s), Image.NEAREST)
                f.paste(bb, (int(pet.P[0] - bb.width / 2), int(pet.P[1] + pet.extent()[0] - bb.height)), bb)
            if pet.cursor_pos:
                cx, cy = map(int, pet.cursor_pos)
                ImageDraw.Draw(f).polygon([(cx, cy), (cx, cy + 16), (cx + 11, cy + 11)], fill=(20, 20, 20, 255))
            ImageDraw.Draw(f).text((10, 8), label, fill=(40, 40, 60, 255))
            frames.append(f.convert("RGB").resize((630, 336), Image.NEAREST))
            stamps.append(label)

    i = 0
    # 入場落下
    while pet.action is not None and i < 200:
        pet.step(dt)
        snap("drop-in", i)
        i += 1
    for label, fn in script:
        pet.run(fn())
        n = 0
        while pet.action is not None and n < 900:
            toy.step(dt, WA, pet.G)
            for sn in snacks:
                if sn[1] < WA[3] or sn[3] != 0:
                    sn[3] += pet.G * dt
                    sn[0] += sn[2] * dt
                    sn[1] = min(WA[3], sn[1] + sn[3] * dt)
                    if sn[1] >= WA[3]:
                        sn[2] = sn[3] = 0.0
            if label == "look-at-mouse":
                ang = n / 72 * 2 * math.pi
                pet.cursor_pos = (pet.P[0] + math.cos(ang) * 260, pet.P[1] - 40 + math.sin(ang) * 120)
            else:
                pet.cursor_pos = None
            pet.step(dt)
            snap(label, i)
            i += 1
            n += 1
            if pet.action is None:
                break
    # 拖曳甩動後放開
    pet.run(pet.act_idle(0.2))
    for _ in range(8):
        pet.step(dt)
    gx, gy = pet.P[0], pet.P[1] - rig.dh * 0.7
    pet.grab(gx, gy)
    for n in range(75):
        mx = gx + math.sin(n / 30 * 2 * math.pi * 1.2) * 160 + n * 3
        my = gy - min(n, 30) * 6
        pet.drag_to(mx, my)
        pet.step(dt)
        snap("drag", i)
        i += 1
    pet.release()
    n = 0
    while pet.action is not None and n < 300:
        pet.step(dt)
        snap("throw", i)
        i += 1
        n += 1
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=66, loop=0)
    # 縮圖總覽
    pick = np.linspace(0, len(frames) - 1, 40).astype(int)
    sheet = Image.new("RGB", (250 * 8, 145 * 5))
    for j, k in enumerate(pick):
        sheet.paste(frames[k].resize((250, 145)), ((j % 8) * 250, (j // 8) * 145))
    sheet.save(str(Path(out_path).with_suffix(".png")))
    print(f"frames={len(frames)} -> {out_path}")


# ------------------------------------------------------------------ 開機自動啟動
STARTUP_LNK = (Path(os.environ.get("APPDATA", str(ROOT))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
               / "Startup" / "Chico 桌寵.lnk")


def autostart_enabled() -> bool:
    return STARTUP_LNK.exists()


def set_autostart(on: bool) -> bool:
    """開機自動啟動：在 Windows 啟動資料夾放（或移除）一個執行 l2d_pet.pyw 的捷徑。"""
    import subprocess

    if not on:
        try:
            STARTUP_LNK.unlink()
        except OSError:
            pass
        return True
    if FROZEN:  # 打包版：直接啟動 exe（圖示就是 exe 本身的狸貓）
        target, args, ico = Path(sys.executable), "", Path(sys.executable)
    else:
        exe = Path(sys.executable)
        target = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
        args = f'"{ROOT / "chico_pet.pyw"}"'
        ico = ROOT / "assets" / "icons" / "tanuki.ico"
        if not ico.exists():
            write_tanuki_ico(ico)

    def q(x):
        return str(x).replace("'", "''")

    ps = (f"$s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut('{q(STARTUP_LNK)}'); "
          f"$l.TargetPath='{q(target)}'; $l.Arguments='{q(args)}'; "
          f"$l.WorkingDirectory='{q(APP_DIR)}'; $l.IconLocation='{q(ico)},0'; "
          f"$l.Description='{PET_NAME} 桌寵'; $l.Save()")
    try:
        STARTUP_LNK.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return STARTUP_LNK.exists()
    except Exception:
        return False


# ------------------------------------------------------------------ Unity 小遊戲（泡泡射擊、接星星）
UNITY_PROJECT = ROOT / "unity" / "ChicoGames"
UNITY_EXE = APP_DIR / "unity" / "Build" / "ChicoGames.exe"


def export_unity(project: Path = UNITY_PROJECT):
    """把 Chico／狸貓等點陣圖輸出到 Unity Resources；人物直接用桌寵同一套 full()（N×N）。"""
    res = project / "Assets" / "Resources" / "Pixel"
    res.mkdir(parents=True, exist_ok=True)
    names = list(OUTFITS)
    for i, name in enumerate(names):
        d = res / f"outfit{i}"
        d.mkdir(exist_ok=True)
        o = load_outfit(name)
        for k in ("front", "left", "right"):
            Image.fromarray(o.full(k)).save(d / f"{k}.png")
        Image.fromarray(o.full("front", 0, 0, True)).save(d / "front_blink.png")
    (project / "Assets" / "Resources" / "outfits.json").write_text(
        json.dumps({"names": names}, ensure_ascii=False), encoding="utf-8")
    Image.fromarray(S.tanuki("front", S.TANUKI_H)).save(res / "tanuki.png")
    for i, c in enumerate(STAR_CANDY):
        c.save(res / f"star{i}.png")
    draw_moonflower(4).save(res / "moonflower.png")
    draw_moonflower(4, 0, 1.0).save(res / "moonflower_glow.png")
    for k in S.SNACKS:
        Image.fromarray(S.snack(k)).save(res / f"snack_{k}.png")
    rc = Image.new("RGBA", (16, 12), (0, 0, 0, 0))  # 灰色雨雲（要避開）
    d = ImageDraw.Draw(rc)
    for x0 in (0, 4, 8):
        d.ellipse((x0, 1 + (x0 == 4) * -1, x0 + 7, 8), fill=(150, 156, 176, 255))
    d.rectangle((2, 5, 13, 8), fill=(150, 156, 176, 255))
    d.line((2, 8, 13, 8), fill=(110, 116, 140, 255))
    for x0 in (3, 7, 11):
        d.line((x0, 10, x0 - 1, 11), fill=(140, 190, 250, 255))
    rc.putpixel((5, 5), (60, 60, 80, 255))
    rc.putpixel((10, 5), (60, 60, 80, 255))
    rc.save(res / "raincloud.png")
    PARTICLES["heart"].save(res / "heart.png")
    PARTICLES["spark"].save(res / "spark.png")
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(res / "pixel.png")
    tanuki_icon(128).save(res / "icon.png")
    write_tanuki_ico(ROOT / "assets" / "icons" / "tanuki.ico")
    fonts = project / "Assets" / "Resources" / "Fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    (fonts / "Cubic_11.ttf").write_bytes(FONT_PATH.read_bytes())
    print(f"已匯出 Unity 素材到 {res}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--demo":
        run_demo(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "--autostart":
        print("開機自動啟動：" + ("已開啟" if set_autostart(sys.argv[2] == "on") and autostart_enabled() else "已關閉"))
    elif len(sys.argv) >= 2 and sys.argv[1] == "--export-unity":
        export_unity()
    elif len(sys.argv) >= 2 and sys.argv[1] in ("--export", "--rebuild-sprites"):
        S.export_layers(force=True)
        print(f"已重新從 PSD 拆圖層：{S.LAYER_DIR}")
    else:
        run_app()
