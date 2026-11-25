"""Chico 桌寵的點陣素材：從 PSD 拆圖層、點陣化、眼睛（視線／眨眼）、小狸貓、零食。

畫面尺寸：原生 75×75 點陣，以最近鄰放大顯示為 130×130 px。
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

# 打包成 exe 後圖層／素材在 _MEIPASS
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PREVIEW = Path(__file__).resolve().parent / "preview"  # PSD 只在開發目錄
LAYER_DIR = ROOT / "assets" / "layers"

N = 75  # 原生畫布
DISPLAY = 130  # 螢幕上角色大小（px）
SCALE = DISPLAY / N  # 顯示倍率（75 → 130）
CHAR_H = 70  # 人物原生高度（頭頂到腳底）
FEET_Y = 73  # 腳底所在列（下面留一列給外框）
B = 4  # 點陣化時每個點取 B×B 的子取樣

OUTLINE = (38, 46, 48, 255)
PALETTE_COLORS = 44

OUTFITS = {"dress": ("dress_psd", "洋裝"), "sailor": ("sailor_psd", "水手")}
OUTFIT_NAMES = {"dress": "洋裝", "sailor": "水手服"}
# 視角：程式內用 key，畫面上的「左／右」以螢幕為準（右 = 臉朝螢幕右邊）
VIEWS = {"front": "正面", "fr": "右前", "right": "右側", "br": "右後",
         "back": "背面", "bl": "左後", "left": "左側", "fl": "左前"}
SPIN_ORDER = ["front", "fr", "right", "br", "back", "bl", "left", "fl"]
HEAD_LAYERS = ("臉", "頭髮")
FACE = "臉"


# ------------------------------------------------------------------ 拆圖層（只需做一次）
def export_layers(force=False):
    """把 PSD 的每個圖層存成 PNG（assets/layers/<衣服>/<視角>/<圖層>.png），之後執行就不需要 psd-tools。"""
    done = LAYER_DIR / "index.json"
    if done.exists() and not force:
        return json.loads(done.read_text("utf-8"))
    from psd_tools import PSDImage

    index = {}
    jobs = [(o, v, PREVIEW / folder / f"{prefix}_{vn}.psd") for o, (folder, prefix) in OUTFITS.items()
            for v, vn in VIEWS.items()]
    for outfit, view, path in jobs:
        psd = PSDImage.open(path)
        out = LAYER_DIR / outfit / view
        out.mkdir(parents=True, exist_ok=True)
        names = []
        for layer in psd:  # 由下往上
            im = Image.new("RGBA", psd.size)
            im.alpha_composite(layer.topil().convert("RGBA"), tuple(max(0, c) for c in layer.offset))
            im.save(out / f"{layer.name}.png")
            names.append(layer.name)
        index.setdefault(outfit, {})[view] = names
    psd = PSDImage.open(PREVIEW / "raccoon_8view.psd")
    out = LAYER_DIR / "tanuki"
    out.mkdir(parents=True, exist_ok=True)
    rv = {vn: v for v, vn in VIEWS.items()}
    for layer in psd:
        im = Image.new("RGBA", psd.size)
        im.alpha_composite(layer.topil().convert("RGBA"), tuple(max(0, c) for c in layer.offset))
        im.save(out / f"{rv[layer.name]}.png")
    done.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    return index


# ------------------------------------------------------------------ 共用
def _lum(c):
    return c[..., 0] * 0.299 + c[..., 1] * 0.587 + c[..., 2] * 0.114


def _dilate(m, n=1):
    for _ in range(n):
        d = m.copy()
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def clean_fringe(a: np.ndarray, steps=7, deep=False) -> np.ndarray:
    """去掉去背留下的白邊：從透明處往內，沿著「很亮、不太有顏色」的像素吃掉，碰到線稿就停。
    deep=True（腿）：再沿著「灰白、幾乎沒有顏色」的殘渣一路吃到底（兩腿之間的縫），碰到線稿或有顏色的地方就停。"""
    a = a.copy()
    rgb = a[..., :3].astype(np.float32) / 255
    sat = rgb.max(-1) - rgb.min(-1)
    light = (_lum(rgb) > 0.82) & (sat < 0.16)
    out = a[..., 3] < 140
    for _ in range(steps):
        out = out | (_dilate(out) & light)
    if deep:
        junk = ((_lum(rgb) > 0.5) & (sat < 0.035)) | (a[..., 3] < 200)  # 褲襪是淡薄荷色（差約 0.06），不會被吃掉
        while True:
            nxt = out | (_dilate(out) & junk)
            if (nxt == out).all():
                break
            out = nxt
    a[out, 3] = 0
    return a


def load_rgba(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA")).copy()


def alpha_bbox(a):
    ys, xs = np.nonzero(a[..., 3] > 40)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def pixelate(src: np.ndarray, box, size) -> np.ndarray:
    """把來源的 box（x0,y0,x1,y1，可超出邊界）縮成 size 的點陣：區塊平均，但保留亮區裡的深色細線（眼睛、線稿）。"""
    w, h = size
    im = Image.fromarray(src).crop(tuple(int(round(v)) for v in box)).resize((w * B, h * B), Image.LANCZOS)
    A = np.asarray(im).astype(np.float32) / 255
    blk = A.reshape(h, B, w, B, 4).transpose(0, 2, 1, 3, 4).reshape(h, w, B * B, 4)
    al = blk[..., 3]
    cov = al.mean(-1)
    mean = (blk[..., :3] * al[..., None]).sum(2) / np.maximum(al.sum(-1), 1e-6)[..., None]
    L = np.where(al > 0.5, _lum(blk[..., :3]), 9.0)
    idx = L.argmin(-1)
    mn = np.take_along_axis(blk[..., :3], idx[..., None, None], 2)[:, :, 0]
    contrast = np.clip((_lum(mean) - _lum(mn) - 0.12) / 0.25, 0, 1) * np.clip((_lum(mean) - 0.3) / 0.2, 0, 1)
    wgt = (0.85 * contrast)[..., None]
    out = np.zeros((h, w, 4), np.float32)
    out[..., :3] = mean * (1 - wgt) + mn * wgt
    out[..., 3] = cov
    return (out * 255).clip(0, 255).astype(np.uint8)


def finish(raw: np.ndarray, pal: Image.Image | None, outline=True, thr=110) -> np.ndarray:
    """量化到調色盤、alpha 二值化、加一圈外框。"""
    h, w = raw.shape[:2]
    if pal is not None:
        q = np.asarray(Image.fromarray(np.ascontiguousarray(raw[..., :3])).quantize(
            palette=pal, dither=Image.Dither.NONE).convert("RGB"))
    else:
        q = raw[..., :3]
    m = raw[..., 3] > thr
    res = np.zeros((h, w, 4), np.uint8)
    res[..., :3] = q
    res[..., 3] = m * 255
    fill_holes(res)
    m = res[..., 3] > 0
    if outline:
        res[_dilate(m) & ~m] = OUTLINE
        fill_holes(res)  # 外框可能又圍出小洞
    return res


def fill_holes(res: np.ndarray, max_size=120) -> np.ndarray:
    """把整個被包住的透明洞（頭髮和臉之間、圖層之間的縫）用周圍的顏色補滿。原地修改。"""
    from scipy import ndimage

    h, w = res.shape[:2]
    m = res[..., 3] > 0
    holes = ndimage.binary_fill_holes(m) & ~m
    if not holes.any():
        return res
    lab, n = ndimage.label(holes)
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    holes = np.isin(lab, [i + 1 for i, sz in enumerate(sizes) if sz <= max_size])
    filled = m.copy()
    col = res[..., :3].astype(np.int32)
    # 洞邊如果是外框色，優先用不是外框的鄰居顏色（補出來比較乾淨）
    nonline = filled & ~np.all(res[..., :3] == np.array(OUTLINE[:3], np.uint8), -1)
    for src in (nonline, filled):
        for _ in range(12):
            todo = holes & ~filled
            if not todo.any():
                break
            acc = np.zeros((h, w, 3), np.int64)
            cnt = np.zeros((h, w), np.int64)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                sf = np.roll(src, (dy, dx), (0, 1))
                acc += np.roll(col, (dy, dx), (0, 1)) * sf[..., None]
                cnt += sf
            new = todo & (cnt > 0)
            col[new] = acc[new] // cnt[new][:, None]
            filled |= new
            src = src | new
    res[holes, :3] = col[holes].astype(np.uint8)
    res[holes, 3] = 255
    return res


def shrink2(a: np.ndarray) -> np.ndarray:
    """2 倍點陣 → 1 倍：每 2×2 取一格。區塊裡明暗差很大時保留最深的顏色（眼睛、睫毛、線稿），
    否則取出現最多的顏色（平手取較深色）。"""
    h, w = a.shape[0] // 2, a.shape[1] // 2
    blk = a[:2 * h, :2 * w].reshape(h, 2, w, 2, 4).transpose(0, 2, 1, 3, 4).reshape(h, w, 4, 4)
    alpha = blk[..., 3] > 0
    lum = blk[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    big = np.where(alpha, lum, -1.0)
    small_l = np.where(alpha, lum, 999.0)
    out = np.zeros((h, w, 4), np.uint8)
    cnt = alpha.sum(-1)
    darkest = small_l.argmin(-1)
    contrast = (big.max(-1) - small_l.min(-1)) > 60
    use_dark = contrast & (small_l.min(-1) < 90)
    # 出現最多的顏色
    codes = (blk[..., 0].astype(np.int64) << 16) | (blk[..., 1].astype(np.int64) << 8) | blk[..., 2]
    codes = np.where(alpha, codes, -1)
    same = (codes[..., :, None] == codes[..., None, :]) & alpha[..., None, :] & alpha[..., :, None]
    votes = same.sum(-1) * 1000 - lum.astype(np.int64)  # 平手取較深色
    votes = np.where(alpha, votes, -10 ** 9)
    mode = votes.argmax(-1)
    pick = np.where(use_dark, darkest, mode)
    sel = np.take_along_axis(blk, pick[..., None, None].repeat(4, -1), 2)[:, :, 0]
    ok = cnt >= 2
    out[ok] = sel[ok]
    out[ok, 3] = 255
    return out


def finish_small(a: np.ndarray, outline=True) -> np.ndarray:
    """縮小後：補洞；可選是否再補一圈外框（小遊戲角色可不加）。"""
    a = a.copy()
    if outline:
        m = a[..., 3] > 0
        a[_dilate(m) & ~m] = OUTLINE
    return fill_holes(a)


def thin_dark_edge(a: np.ndarray, lum_thr=100) -> np.ndarray:
    """削掉輪廓最外圈偏黑的線（PSD 線稿點陣化後會偏粗），讓遊戲人物外框更細。"""
    a = a.copy()
    m = a[..., 3] > 0
    edge = np.zeros_like(m)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        edge |= m & np.roll(~m, (dy, dx), (0, 1))
    lum = a[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    a[edge & (lum < lum_thr), 3] = 0
    return a


# 小遊戲用的細外框（比桌寵 OUTLINE 淺很多，看起來比較細）
OUTLINE_THIN = (96, 108, 110, 255)


def add_thin_outline(a: np.ndarray) -> np.ndarray:
    """加一圈較淺的 1px 外框。"""
    a = a.copy()
    m = a[..., 3] > 0
    a[_dilate(m) & ~m] = OUTLINE_THIN
    return a


def make_palette(raws, n=PALETTE_COLORS) -> Image.Image:
    px = np.concatenate([r[..., :3][r[..., 3] > 110] for r in raws])
    return Image.fromarray(px.reshape(-1, 1, 3)).quantize(n, method=Image.Quantize.MEDIANCUT)


# ------------------------------------------------------------------ 人物
class Outfit:
    """一套衣服的 8 個視角。part() 回傳原生點陣（75×75 RGBA）。"""

    def __init__(self, name: str, index: dict):
        self.name = name
        self.layers = {}  # view -> {layer: array}
        self.boxes = {}
        for view, names in index[name].items():
            d = {ln: clean_fringe(load_rgba(LAYER_DIR / name / view / f"{ln}.png"), deep=(ln == "腿")) for ln in names}
            self.layers[view] = d
            full = np.zeros_like(next(iter(d.values())))
            for a in d.values():
                full = np.maximum(full, a)
            x0, y0, x1, y1 = alpha_bbox(full)
            legs = d.get("腿")
            cx = (alpha_bbox(legs)[0] + alpha_bbox(legs)[2]) / 2 if legs is not None else (x0 + x1) / 2
            k = CHAR_H / (y1 - y0)  # 來源 → 原生 的倍率（每個視角各自正規化成同樣身高）
            bx0 = cx - (N / 2) / k
            by0 = y1 - FEET_Y / k
            self.boxes[view] = (bx0, by0, bx0 + N / k, by0 + N / k, k)
        self.eyes = {v: self._find_eyes(v) for v in self.layers}
        raws = [pixelate(self._upper(v, 0, 0, False), self.boxes[v][:4], (N, N)) for v in ("front", "right", "back")]
        raws += [pixelate(self.layers["front"]["腿"], self.boxes["front"][:4], (N, N))]
        self.pal = make_palette(raws)
        self.cache = {}

    def _find_eyes(self, view):
        """臉圖層裡的眼睛：不是膚色、也不是腮紅的像素（偏藍綠或很暗）。"""
        face = self.layers[view].get(FACE)
        if face is None:
            return None
        a = face[..., 3] > 200
        if a.sum() < 50:
            return None
        from scipy import ndimage

        rgb = face[..., :3].astype(np.float32)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        warm = (r >= g) & (r >= b - 4)
        skin = np.median(rgb[a & warm & (_lum(rgb / 255) > 0.8)], 0)
        skinlike = warm & (_lum(rgb / 255) > 0.62)  # 膚色、腮紅
        # 先找虹膜（飽和的藍綠色、在臉中段），再把周圍的非膚色（睫毛、眼白邊線）一起算進眼睛
        fx0, fy0, fx1, fy1 = alpha_bbox(face)
        fh = fy1 - fy0
        band = np.zeros_like(a)
        band[fy0 + int(fh * 0.3):fy0 + int(fh * 0.85), fx0:fx1] = True
        iris = a & band & (g - r > 45) & (b - r > 35)
        lab, n = ndimage.label(_dilate(iris, 1))
        if n == 0:
            return None
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
        order = np.argsort(sizes)[::-1]
        m = np.zeros_like(a)
        for i in order[:2]:
            if sizes[i] < sizes[order[0]] * 0.25 or sizes[i] < 40:
                continue
            ys, xs = np.nonzero(lab == i + 1)
            w, h = xs.max() - xs.min(), ys.max() - ys.min()
            x0, x1 = int(xs.min() - w * 0.25), int(xs.max() + w * 0.25)
            y0, y1 = int(ys.min() - h * 0.45), int(ys.max() + h * 0.15)
            box = np.zeros_like(a)
            box[max(0, y0):y1, max(0, x0):x1] = True
            m |= box & a & ~skinlike
        if m.sum() < 30:
            return None
        m = _dilate(m, 1) & a
        return m, skin

    def _upper(self, view, ex, ey, blink):
        """身體 + 臉 + 頭髮（來源解析度），眼睛依 ex/ey（原生點數）位移，或閉眼。"""
        d = self.layers[view]
        out = Image.new("RGBA", (d[next(iter(d))].shape[1], d[next(iter(d))].shape[0]))
        k = self.boxes[view][4]
        for ln, a in d.items():
            if ln == "腿":
                continue
            if ln == FACE and self.eyes.get(view) and (ex or ey or blink):
                a = self._move_eyes(a, view, ex / k, ey / k, blink)
            out.alpha_composite(Image.fromarray(a))
        return np.asarray(out)

    def _move_eyes(self, face, view, dx, dy, blink):
        m, skin = self.eyes[view]
        f = face.copy()
        eye = np.zeros_like(face)
        eye[m] = face[m]
        f[m, :3] = skin.astype(np.uint8)
        if blink:
            # 每隻眼睛畫一條細細的、往下彎的短線（約眼睛寬度的一半）
            from scipy import ndimage

            lab, n = ndimage.label(m)
            for i in range(1, n + 1):
                ys, xs = np.nonzero(lab == i)
                if xs.size < 40:
                    continue
                cx = (xs.min() + xs.max()) / 2
                half = (xs.max() - xs.min()) * 0.27
                yl = ys.min() + (ys.max() - ys.min()) * 0.6
                for x in range(int(cx - half), int(cx + half) + 1):
                    u = (x - cx) / max(half, 1)
                    y = int(round(yl + 3 * (1 - u * u)))
                    f[y - 1:y + 2, x] = (78, 92, 94, 255)
            return f
        # 只移動虹膜：睫毛、眼線不動；虹膜原本的位置補成眼白，移動後的虹膜只畫在眼白範圍內
        from scipy import ndimage

        f = face.copy()
        rgb = face[..., :3].astype(np.float32)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        L = _lum(rgb / 255)
        dark = m & (L < 0.5)  # 睫毛、眼線、瞳孔外框
        iris = ndimage.binary_fill_holes(m & (g - r > 40) & (b - r > 30)) & m
        ball = ndimage.binary_fill_holes(m & ~dark) & m & ~dark | iris  # 眼睛裡面（眼白＋虹膜）
        white_px = rgb[ball & ~iris & (L > 0.8)]
        white = np.median(white_px, 0) if white_px.size else np.array([240, 248, 246], np.float32)
        f[iris, :3] = white.astype(np.uint8)
        ix, iy = int(round(dx * 0.8)), int(round(dy * 0.6))
        moved = np.zeros_like(iris)
        src = np.roll(np.roll(iris, iy, 0), ix, 1)
        moved[:] = src
        pix = np.roll(np.roll(face, iy, 0), ix, 1)
        put = moved & (ball | iris)
        f[put] = pix[put]
        f[dark] = face[dark]  # 睫毛蓋在最上面
        return f

    def part(self, view, kind, ex=0, ey=0, blink=False) -> np.ndarray:
        key = (view, kind, ex, ey, blink)
        if key not in self.cache:
            box = self.boxes[view][:4]
            if kind == "legs":
                src = self.layers[view].get("腿")
                if src is None:
                    self.cache[key] = np.zeros((N, N, 4), np.uint8)
                    return self.cache[key]
            else:
                src = self._upper(view, ex, ey, blink)
            # 桌面上的小人：直接點陣化成 75 格（使用者比較喜歡這個版本的樣子）
            self.cache[key] = finish(pixelate(src, box, (N, N)), self.pal)
        return self.cache[key]

    def full(self, view, ex=0, ey=0, blink=False) -> np.ndarray:
        """整個人（腿＋上半身），原生 75×75。"""
        key = (view, "full", ex, ey, blink)
        if key not in self.cache:
            c = np.zeros((N, N, 4), np.uint8)
            paste(c, self.part(view, "legs"), 0, 0)
            paste(c, self.part(view, "upper", ex, ey, blink), 0, 0)
            self.cache[key] = fill_holes(c)
        return self.cache[key]

    def small(self, view, n=32, outline=True) -> np.ndarray:
        """小遊戲用的小尺寸角色（n×n，直接從原圖點陣化，不是縮小點陣圖）。
        outline=False 時不加外框（Unity 小遊戲用）。"""
        key = (view, "small", n, outline)
        if key not in self.cache:
            d = self.layers[view]
            im = Image.new("RGBA", (d[next(iter(d))].shape[1], d[next(iter(d))].shape[0]))
            for a in d.values():
                im.alpha_composite(Image.fromarray(a))
            x0, y0, x1, y1, k = self.boxes[view]
            self.cache[key] = finish(pixelate(np.asarray(im), (x0, y0, x1, y1), (n, n)), self.pal, outline=outline)
        return self.cache[key]

    def portrait(self, view="fl", height=200) -> Image.Image:
        """對話立繪：合成原始 PSD 圖層（不點陣化），裁半身後用高品質縮放。"""
        key = (view, "portrait", int(height))
        if key not in self.cache:
            d = self.layers[view]
            im = Image.new("RGBA", (d[next(iter(d))].shape[1], d[next(iter(d))].shape[0]))
            for a in d.values():
                im.alpha_composite(Image.fromarray(a))
            box = im.getbbox()
            if box:
                im = im.crop(box)
            im = im.crop((0, 0, im.width, max(1, int(im.height * 0.58))))  # 頭到腰
            h = max(1, int(height))
            w = max(1, int(round(im.width * h / im.height)))
            self.cache[key] = im.resize((w, h), Image.LANCZOS)
        return self.cache[key]

    def has_eyes(self, view):
        return self.eyes.get(view) is not None

    def legs_split(self, view):
        """腿分成左右兩半（以畫面上的 x 分），走路時各自抬腳。"""
        key = (view, "split")
        if key not in self.cache:
            legs = self.part(view, "legs")
            xs = np.nonzero(legs[..., 3].any(0))[0]
            if xs.size == 0:
                self.cache[key] = (legs, np.zeros_like(legs))
            else:
                mid = int((xs.min() + xs.max() + 1) / 2)
                a, b = legs.copy(), legs.copy()
                a[:, mid:] = 0
                b[:, :mid] = 0
                self.cache[key] = (a, b)
        return self.cache[key]


# ------------------------------------------------------------------ 小狸貓
HELD_H = 32  # 抱在懷裡時的高度
TANUKI_H = HELD_H  # 放在地上／丟出去時跟抱著一樣大


@lru_cache(maxsize=None)
def tanuki(view="front", h=TANUKI_H) -> np.ndarray:
    a = clean_fringe(load_rgba(LAYER_DIR / "tanuki" / f"{view}.png"))
    x0, y0, x1, y1 = alpha_bbox(a)
    k = (h - 2) / (y1 - y0)
    w = int(np.ceil((x1 - x0) * k)) + 4
    cx = (x0 + x1) / 2
    box = (cx - (w / 2) / k, y1 - (h - 1) / k, cx + (w / 2) / k, y1 + 1 / k)
    raw = pixelate(a, box, (w, h))
    return finish(raw, _tanuki_pal())


@lru_cache(maxsize=None)
def _tanuki_pal():
    a = clean_fringe(load_rgba(LAYER_DIR / "tanuki" / "front.png"))
    x0, y0, x1, y1 = alpha_bbox(a)
    return make_palette([pixelate(a, (x0, y0, x1, y1), (40, 40))], 20)


# ------------------------------------------------------------------ 零食（手繪點陣）
SNACK_COLORS = {
    "o": OUTLINE,
    "W": (255, 255, 255, 255),
    "P": (246, 140, 178, 255), "p": (255, 196, 218, 255), "r": (220, 82, 120, 255),  # 粉紅
    "Y": (255, 226, 120, 255), "C": (214, 156, 92, 255), "c": (238, 192, 124, 255),  # 餅乾
    "D": (110, 66, 44, 255),  # 巧克力
    "M": (130, 220, 196, 255), "m": (196, 244, 228, 255),  # 薄荷綠（跟 Chico 同色系）
    "S": (232, 226, 214, 255),  # 棒子
    "R": (232, 60, 76, 255),  # 草莓
    "B": (120, 170, 255, 255),  # 糖粒藍
    "G": (110, 200, 120, 255),  # 葉
}
SNACKS = {
    "lollipop": [
        "..ooooo..",
        ".oPPpWMo.",
        "oPWMMMPMo",
        "oMPPpWPPo",
        "oWMPMMPMo",
        "oPMWPPPWo",
        ".oPMMWMo.",
        "..ooooo..",
        "....oSo..",
        "....oSo..",
        "....oSo..",
        "....oSo..",
        ".....o...",
    ],
    "cookie": [
        "...ooooo...",
        "..occCcco..",
        ".occDcccCo.",
        "occcccDccco",
        "oCcDccccCco",
        "occccCccDco",
        "ocDccccccco",
        ".occcDccCo.",
        "..oCcccco..",
        "...ooooo...",
    ],
    "cake": [
        "....oRo....",
        "...oRRRo...",
        "..oWWGWWo..",
        ".oWWWWWWWo.",
        "oWWWWWWWWWo",
        "oPPPPPPPPPo",
        "oYYYYYYYYYo",
        "oWWWWWWWWWo",
        "oYYYYYYYYYo",
        "oCCCCCCCCCo",
        ".ooooooooo.",
    ],
    "donut": [
        "...ooooo...",
        "..oPpPBPo..",
        ".oPWPPPYPo.",
        "oPBPoooPPpo",
        "oPPo...oBPo",
        "oYPo...oPPo",
        "oPPPoooPWco",
        ".ocPBPPPco.",
        "..occccco..",
        "...ooooo...",
    ],
}
SNACKS["candy"] = [  # 包裝糖果（兩邊扭起來的糖果紙）
    "oo.......oo",
    "oPo.ooo.oPo",
    "oPPoMMMoPPo",
    "oPpMmMMMpPo",
    "oPPMMWMMPPo",
    "oPpMMMMmpPo",
    "oPPoMMMoPPo",
    "oPo.ooo.oPo",
    "oo.......oo",
]
SNACKS["macaron"] = [  # 馬卡龍（粉紅＋奶油夾心）
    "..ooooooo..",
    ".oppPPPPPo.",
    "oPpPPPPPPPo",
    "oPPPPPPPPro",
    "orrrrrrrrro",
    "oWWWWWWWWWo",
    "orrrrrrrrro",
    "oPpPPPPPPPo",
    ".oPPPPPPro.",
    "..ooooooo..",
]
SNACK_NAMES = {"lollipop": "棒棒糖", "cookie": "餅乾", "cake": "蛋糕", "donut": "甜甜圈", "candy": "糖果",
               "macaron": "馬卡龍"}
FOODS = ("candy", "cookie", "cake", "macaron")  # 餵食時隨機挑一種


@lru_cache(maxsize=None)
def food_stages(kind) -> tuple:
    """吃東西的三個階段：完整、咬一口、剩一點點（從右上角咬掉圓形缺口，缺口邊緣補外框）。"""
    base = snack(kind)
    h, w = base.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    out = [base]
    for r in (w * 0.38, w * 0.62):
        a = base.copy()
        bite = np.hypot(xx - (w - 1), yy - h * 0.2) < r
        if r > w * 0.5:
            bite |= np.hypot(xx - (w - 1) * 0.15, yy) < r * 0.55
        a[bite] = 0
        m = a[..., 3] > 0
        edge = m & _dilate(~m) & (bite | _dilate(bite))
        a[edge] = OUTLINE
        out.append(a)
    return tuple(out)


@lru_cache(maxsize=None)
def snack(kind) -> np.ndarray:
    rows = SNACKS[kind]
    w = max(len(r) for r in rows)
    a = np.zeros((len(rows), w, 4), np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in SNACK_COLORS:
                a[y, x] = SNACK_COLORS[ch]
    return a


# ------------------------------------------------------------------ 小工具
def paste(dst: np.ndarray, src: np.ndarray, x: int, y: int):
    """把 src（RGBA，alpha 0/255 為主）貼到 dst 的 (x, y)，超出邊界的部分裁掉。"""
    h, w = src.shape[:2]
    H, W = dst.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return dst
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.uint16)
    d = dst[y0:y1, x0:x1]
    d[..., :3] = ((s[..., :3] * a + d[..., :3] * (255 - a)) // 255).astype(np.uint8)
    d[..., 3] = np.maximum(d[..., 3], s[..., 3])
    return dst


def scale_up(a: np.ndarray, s=None) -> Image.Image:
    """把原生點陣放大到螢幕尺寸（支援非整數倍率，用最近鄰）。"""
    s = SCALE if s is None else s
    if abs(s - round(s)) < 1e-6 and s >= 1:
        k = int(round(s))
        return Image.fromarray(np.repeat(np.repeat(a, k, 0), k, 1))
    h, w = a.shape[:2]
    return Image.fromarray(a).resize((max(1, int(round(w * s))), max(1, int(round(h * s)))), Image.NEAREST)
