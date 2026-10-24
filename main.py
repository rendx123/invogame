# -*- coding: utf-8 -*-
"""
INVOKER: PROCAST TRAINER — прототип на Pygame (v2).

Суть: у каждого врага есть «раунд» — шкала зарядки удара. На шкале подсвечены
ТАЙМИНГ-ОКНА: в каждом окне нужно скастовать подходящее заклинание.
  • Попал во все окна  -> «идеальный прокаст»: КОР умирает, ТАНК бьёт на 80% слабее,
                         САППОРТ пропускает ход.
  • Попал частично      -> враг бьёт слабее.
  • Не попал            -> враг бьёт в полную силу.
У заклинаний есть перезарядка (одно и то же 10 раз подряд не скастуешь),
у Invoke — своя перезарядка, как в Dota 2 (Q W E, слоты D F, R).

Картинки: положи папку `image` (из репозитория rendx123/invogame) рядом с этим файлом.
Иконки ищутся автоматически по названию заклинания (cold_snap.png, invoker_cold_snap.png ...).
Если файла нет — рисуется встроенная иконка.

Запуск:  pip install pygame   затем   python main_v2.py
"""
import math
import os
import random
import sys
from collections import Counter, deque
from functools import lru_cache

import pygame

# ======================================================================
# НАСТРОЙКИ
# ======================================================================
W, H = 1100, 700
FPS = 60

STRICT_ORDER = True      # True: порядок сфер важен (кроме QWE). False: как в Dota (порядок не важен)
SHOW_HINTS = True        # подсказки: окна на шкале, слабости/резисты, предпросмотр комбо
SHOP_ENABLED = False     # магазин отложен на потом

INVOKE_CD = 1.5          # перезарядка Invoke (сек)
OFF_WINDOW_MULT = 0.6    # множитель урона, если каст не попал в тайминг-окно
ALACRITY_MULT = 1.4

PLAYER_POS = (230, 470)  # позиция «ног» героя
ENEMY_POS = (870, 470)
PLAYER_C = (230, 380)    # центр груди (для эффектов)
ENEMY_C = (870, 380)
GROUND_Y = 470

BG = (10, 10, 20)
WHITE = (235, 235, 245)
GOLD = (255, 205, 70)
RED = (255, 70, 90)
GREEN = (90, 230, 130)
CYAN = (80, 220, 255)
BLUE = (110, 170, 255)

ORB_COL = {"Q": (60, 170, 255), "W": (200, 90, 255), "E": (255, 150, 40)}
ORB_NAME = {"Q": "Quas", "W": "Wex", "E": "Exort"}

# ======================================================================
# ДАННЫЕ: ЗАКЛИНАНИЯ
# ======================================================================
SPELLS = {
    "QQQ": dict(name="Cold Snap", abbr="CS", cd=6.0, col=(90, 200, 255), desc="Урон 26 + заморозка (пауза зарядки врага 1.2с)"),
    "QQW": dict(name="Ghost Walk", abbr="GW", cd=10.0, col=(170, 215, 235), desc="Следующий удар по тебе промахнётся (8с)"),
    "QQE": dict(name="Ice Wall", abbr="IW", cd=8.0, col=(140, 230, 255), desc="Урон 14 + замедление зарядки врага на 5с"),
    "WWW": dict(name="EMP", abbr="EMP", cd=9.0, col=(210, 110, 255), desc="Урон 18 + сжигает щит (ману)"),
    "WWQ": dict(name="Tornado", abbr="TO", cd=9.0, col=(170, 140, 255), desc="Урон 12 + подброс (пауза 1.8с)"),
    "WWE": dict(name="Alacrity", abbr="AL", cd=6.0, col=(255, 190, 70), desc="+40% к урону на 6с"),
    "EEE": dict(name="Sun Strike", abbr="SS", cd=8.0, col=(255, 215, 70), desc="Большой урон 48 (через 0.8с)"),
    "EEQ": dict(name="Forge Spirit", abbr="FS", cd=10.0, col=(255, 130, 50), desc="Дух бьёт врага 6 раз (по 8 урона)"),
    "EEW": dict(name="Chaos Meteor", abbr="CM", cd=14.0, col=(255, 90, 40), desc="Урон 34 + поджог 4с"),
    "QWE": dict(name="Deafening Blast", abbr="DB", cd=12.0, col=(220, 225, 255), desc="Урон 18 + оглушение (пауза 2.6с), любой порядок"),
}
BY_NAME = {s["name"]: s for s in SPELLS.values()}
KEY_BY_NAME = {s["name"]: k for k, s in SPELLS.items()}

# ======================================================================
# ДАННЫЕ: ГЕРОИ-ВРАГИ (3 класса)
# ======================================================================
def S(spells, a, b, label):
    """Тайминг-окно: какие заклинания подходят, начало/конец (доля шкалы), подпись."""
    return dict(spells=tuple(spells), a=a, b=b, label=label)


CLASS_INFO = {
    "core": dict(label="КОР", col=RED, perfect="kill",
                 text="Хрупкий, бьёт сильно. Идеальный прокаст = убийство"),
    "tank": dict(label="ТАНК", col=BLUE, perfect="weaken",
                 text="Много HP, режет бурст. Идеальный прокаст = удар слабее на 80% + 20% HP урона"),
    "support": dict(label="САППОРТ", col=GREEN, perfect="skip",
                    text="Мало HP, дебафф. Идеальный прокаст = пропуск хода. Не трать на него ульты"),
    "boss": dict(label="БОСС", col=GOLD, perfect="skip",
                 text="Огромный запас HP, 4 тайминга"),
}

HEROES = {
    # ---------------- КОРЫ ----------------
    "antimage": dict(name="Anti-Mage", cls="core", hp=110, dmg=28, rt=9.0, shield=0, gold=30,
                     pal=((60, 70, 170), (40, 40, 100), (120, 230, 255)),
                     weak={"EMP": 1.5, "Sun Strike": 1.2}, resist={"Chaos Meteor": 0.6, "Tornado": 0.8}, debuff=None,
                     script=[S(("Tornado", "Deafening Blast"), .08, .38, "Прервать Blink"),
                             S(("EMP",), .42, .66, "Сжечь ману"),
                             S(("Sun Strike", "Cold Snap"), .70, .95, "Добить")]),
    "medusa": dict(name="Medusa", cls="core", hp=100, dmg=24, rt=9.5, shield=70, gold=32,
                   pal=((50, 150, 120), (190, 160, 70), (90, 200, 110)),
                   weak={"EMP": 1.5}, resist={}, debuff=None,
                   script=[S(("EMP",), .08, .36, "Пробить Mana Shield"),
                           S(("Tornado", "Deafening Blast"), .40, .66, "Сорвать Stone Gaze"),
                           S(("Sun Strike", "Chaos Meteor"), .70, .95, "Добить")]),
    "drow": dict(name="Drow Ranger", cls="core", hp=85, dmg=30, rt=8.5, shield=0, gold=30,
                 pal=((50, 70, 130), (110, 90, 60), (150, 220, 255)),
                 weak={"Chaos Meteor": 1.3, "Sun Strike": 1.2}, resist={"Cold Snap": 0.7}, debuff=None,
                 script=[S(("Ice Wall", "Cold Snap"), .08, .35, "Замедлить"),
                         S(("Tornado", "Deafening Blast"), .40, .66, "Перебить Gust"),
                         S(("Sun Strike", "Chaos Meteor", "Forge Spirit"), .70, .95, "Добить")]),
    # ---------------- ТАНКИ ----------------
    "mars": dict(name="Mars", cls="tank", hp=320, dmg=18, rt=11.0, shield=0, gold=36,
                 pal=((150, 40, 40), (190, 160, 70), (230, 60, 60)),
                 weak={"Forge Spirit": 1.3, "Deafening Blast": 1.2}, resist={"Sun Strike": 0.5, "Chaos Meteor": 0.7}, debuff=None,
                 script=[S(("Ice Wall", "Cold Snap"), .08, .32, "Замедлить шаг"),
                         S(("Forge Spirit", "Chaos Meteor"), .38, .62, "Дот / дух"),
                         S(("Deafening Blast", "Tornado"), .68, .94, "Оглушить")]),
    "axe": dict(name="Axe", cls="tank", hp=340, dmg=20, rt=11.0, shield=0, gold=36,
                pal=((120, 30, 30), (90, 60, 50), (255, 90, 60)),
                weak={"Chaos Meteor": 1.3, "Cold Snap": 1.2}, resist={"Sun Strike": 0.6, "Forge Spirit": 0.8}, debuff=None,
                script=[S(("Tornado",), .08, .32, "Сбить Berserker's Call"),
                        S(("Chaos Meteor", "Cold Snap"), .38, .64, "Урон"),
                        S(("EMP", "Deafening Blast"), .70, .95, "Контроль")]),
    "pudge": dict(name="Pudge", cls="tank", hp=360, dmg=17, rt=11.5, shield=0, gold=38,
                  pal=((150, 70, 70), (70, 50, 40), (200, 255, 150)),
                  weak={"Ice Wall": 1.3, "Cold Snap": 1.3}, resist={"Sun Strike": 0.7}, debuff=None,
                  script=[S(("Ice Wall",), .08, .32, "Стена против хука"),
                          S(("Cold Snap",), .38, .62, "Заморозка"),
                          S(("Chaos Meteor", "Forge Spirit"), .68, .94, "Дот")]),
    # ---------------- САППОРТЫ ----------------
    "hoodwink": dict(name="Hoodwink", cls="support", hp=75, dmg=12, rt=7.0, shield=0, gold=26,
                     pal=((110, 70, 50), (200, 120, 60), (255, 230, 120)),
                     weak={"Cold Snap": 1.3}, resist={}, debuff="snare",
                     script=[S(("Tornado", "Deafening Blast"), .12, .45, "Сбить Bushwhack"),
                             S(("Sun Strike", "Cold Snap", "Chaos Meteor"), .52, .90, "Добить")]),
    "grimstroke": dict(name="Grimstroke", cls="support", hp=85, dmg=11, rt=7.5, shield=0, gold=26,
                       pal=((45, 30, 70), (200, 170, 80), (190, 90, 255)),
                       weak={"EMP": 1.3}, resist={"Tornado": 0.8}, debuff="ink",
                       script=[S(("EMP", "Deafening Blast"), .12, .45, "Развеять чернила"),
                               S(("Sun Strike", "Cold Snap", "Chaos Meteor"), .52, .90, "Добить")]),
    "lion": dict(name="Lion", cls="support", hp=70, dmg=10, rt=7.0, shield=0, gold=26,
                 pal=((100, 40, 130), (70, 30, 90), (255, 90, 90)),
                 weak={"EMP": 1.3, "Sun Strike": 1.2}, resist={}, debuff="silence",
                 script=[S(("Tornado", "Ice Wall"), .12, .45, "Прервать Hex"),
                         S(("Sun Strike", "EMP", "Deafening Blast"), .52, .90, "Добить")]),
    # ---------------- БОСС ----------------
    "roshan": dict(name="ROSHAN", cls="boss", hp=700, dmg=32, rt=12.0, shield=0, gold=150,
                   pal=((140, 100, 70), (190, 150, 110), (255, 70, 70)),
                   weak={"Deafening Blast": 1.2, "Forge Spirit": 1.2}, resist={"Sun Strike": 0.6, "Cold Snap": 0.8}, debuff=None,
                   script=[S(("Ice Wall", "Cold Snap"), .05, .26, "Замедлить"),
                           S(("Forge Spirit", "Chaos Meteor"), .30, .52, "Дот"),
                           S(("Tornado", "Deafening Blast"), .56, .76, "Контроль"),
                           S(("Sun Strike", "EMP"), .80, .96, "Добить")]),
}

DEBUFF_TEXT = {"silence": ("Безмолвие 2с: нельзя кастовать D/F", 2.0),
               "snare": ("Корни 3с: нельзя Invoke", 3.0),
               "ink": ("Чернила 4с: перезарядки вдвое медленнее", 4.0)}

# Скины Инвокера (нажми K) и варианты скинов врагов
SKINS_PLAYER = [
    dict(name="Dark Artistry", main=(88, 40, 150), sec=(255, 196, 70), acc=(255, 180, 60)),
    dict(name="Crimson Flame", main=(150, 30, 40), sec=(255, 150, 60), acc=(255, 90, 40)),
    dict(name="Frost Ascendant", main=(40, 90, 160), sec=(190, 235, 255), acc=(120, 220, 255)),
    dict(name="Emerald Storm", main=(24, 110, 80), sec=(210, 255, 150), acc=(120, 255, 170)),
]
ENEMY_SKINS = ["Классика", "Ледяной", "Токсичный", "Золотой"]


def tint(pal, v):
    """Скин врага = перекраска палитры."""
    def f(c):
        if v == 1:
            return (c[2], c[1], c[0])
        if v == 2:
            return (c[1], c[0], c[2])
        if v == 3:
            return (min(255, c[0] + 60), min(255, c[1] + 50), c[2] // 2)
        return c
    return tuple(f(c) for c in pal)


# ======================================================================
# ВСПОМОГАТЕЛЬНОЕ
# ======================================================================
def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def lerp2(a, b, k):
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)


def glow(surf, color, pos, r, layers=4):
    """Неоновое свечение."""
    r = max(2, int(r))
    size = int(r * 5)
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size // 2
    for i in range(layers, 0, -1):
        pygame.draw.circle(s, (*color, 26 * (layers - i + 1)), (c, c), int(r * (1 + 0.35 * i)))
    pygame.draw.circle(s, (*color, 255), (c, c), r)
    pygame.draw.circle(s, (255, 255, 255, 190), (c, c), max(1, r // 3))
    surf.blit(s, (int(pos[0]) - c, int(pos[1]) - c))


def wrap_text(font, text, width):
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


SCANCODES = {20: "Q", 26: "W", 8: "E", 21: "R", 7: "D", 9: "F", 14: "K", 11: "H", 44: "SPACE", 41: "ESC"}
CYR = {"й": "Q", "ц": "W", "у": "E", "к": "R", "в": "D", "а": "F", "л": "K", "р": "H"}


def key_char(ev):
    """Раскладконезависимое определение клавиши (работает и на русской раскладке)."""
    ch = SCANCODES.get(getattr(ev, "scancode", None))
    if ch:
        return ch
    u = (getattr(ev, "unicode", "") or "").lower()
    if u in CYR:
        return CYR[u]
    if u == " ":
        return "SPACE"
    return u.upper()


# ======================================================================
# «3D»: ШЕЙДЕНЫЕ ОБЪЁМЫ (сферы/эллипсоиды с градиентом и бликом)
# ======================================================================
@lru_cache(maxsize=256)
def sphere_surf(r, col):
    r = max(3, int(r))
    n = min(r, 36)
    s = pygame.Surface((2 * r + 2, 2 * r + 2), pygame.SRCALPHA)
    dk = shade(col, 0.42)
    lt = tuple(min(255, int(v * 1.25) + 40) for v in col)
    for i in range(n):
        k = i / (n - 1) if n > 1 else 1.0
        rad = max(1, int(r * (1 - 0.78 * k)))
        cx = int(r + 1 - k * r * 0.28)
        cy = int(r + 1 - k * r * 0.32)
        pygame.draw.circle(s, mix(dk, lt, k ** 0.9), (cx, cy), rad)
    pygame.draw.circle(s, (0, 0, 0, 70), (r + 1, r + 1), r, 1)
    return s


@lru_cache(maxsize=512)
def ellipsoid_surf(rx, ry, col):
    base = sphere_surf(40, col)
    return pygame.transform.smoothscale(base, (max(2, int(rx * 2) + 2), max(2, int(ry * 2) + 2)))


class Ctx:
    """Контекст рисования героя (лицом вправо; враги потом отражаются)."""

    def __init__(self, surf, ox, oy, t, pal, pose=0.0):
        self.s, self.ox, self.oy, self.t, self.pose = surf, ox, oy, t, pose
        self.main, self.sec, self.acc = pal

    def P(self, x, y):
        return (int(self.ox + x), int(self.oy + y))

    def sph(self, x, y, r, col):
        im = sphere_surf(int(r), tuple(col))
        self.s.blit(im, (int(self.ox + x - im.get_width() / 2), int(self.oy + y - im.get_height() / 2)))

    def ell(self, x, y, rx, ry, col):
        im = ellipsoid_surf(int(rx), int(ry), tuple(col))
        self.s.blit(im, (int(self.ox + x - im.get_width() / 2), int(self.oy + y - im.get_height() / 2)))

    def limb(self, a, b, w, col):
        A, B, w = self.P(*a), self.P(*b), max(2, int(w))
        pygame.draw.line(self.s, shade(col, 0.45), A, B, w + 2)
        pygame.draw.line(self.s, col, A, B, w)
        o = w // 4
        pygame.draw.line(self.s, shade(col, 1.35), (A[0] - o, A[1] - o), (B[0] - o, B[1] - o), max(1, w // 3))
        for p in (A, B):
            pygame.draw.circle(self.s, col, p, w // 2)

    def poly(self, pts, col, outline=True):
        q = [self.P(*p) for p in pts]
        pygame.draw.polygon(self.s, col, q)
        if outline:
            pygame.draw.polygon(self.s, shade(col, 0.4), q, 2)

    def line(self, a, b, w, col):
        pygame.draw.line(self.s, col, self.P(*a), self.P(*b), max(1, int(w)))

    def glow(self, x, y, r, col):
        glow(self.s, col, self.P(x, y), r, 3)

    def curve(self, cx, cy, r, a0, a1, w, col, n=12):
        pts = [self.P(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
        pygame.draw.lines(self.s, col, False, pts, w)

    def humanoid(self, bw, bh, hr, leg, arm, skin, armor, boots, bob=0.0, legs=True):
        """Универсальный «скелет»: ноги, торс, руки, голова. Возвращает ключевые точки."""
        t = self.t
        hip = -leg
        sh = hip - bh
        if legs:
            sw = math.sin(t * 2) * 2
            for sx, side in ((-1, -sw), (1, sw)):
                fx = sx * (bw * 0.45) + sx * 3 + side
                self.limb((sx * bw * 0.4, hip), (fx, -4), int(bw * 0.38) + 4, boots)
                self.ell(fx + 4, -3, int(bw * 0.45) + 5, 7, shade(boots, 0.8))
        self.ell(0, hip - bh * 0.45 + bob, bw, bh * 0.58, armor)
        bs = (-bw * 0.75, sh + bh * 0.12 + bob)
        bhand = (bs[0] - arm * 0.2, bs[1] + arm * 0.9)
        self.limb(bs, bhand, int(bw * 0.3) + 3, skin)
        hd = (3, sh - hr * 0.55 + bob)
        self.sph(hd[0], hd[1], hr, skin)
        fs = (bw * 0.75, sh + bh * 0.12 + bob)
        fh = lerp2((fs[0] + arm * 0.3, fs[1] + arm * 0.85), (fs[0] + arm * 1.05, fs[1] - arm * 0.2), self.pose)
        self.limb(fs, fh, int(bw * 0.3) + 3, skin)
        self.sph(fs[0], fs[1], int(bw * 0.3) + 4, armor)
        self.sph(bs[0], bs[1], int(bw * 0.3) + 4, armor)
        return dict(head=hd, fhand=fh, bhand=bhand, sh=sh, hip=hip, hr=hr)


# ---------------------- отрисовка конкретных героев ----------------------
def draw_invoker(c):
    t = c.t
    bob = math.sin(t * 2) * 3
    c.poly([(-46, 0), (46, 0), (26, -100 + bob), (-26, -100 + bob)], c.main)
    c.poly([(-9, 0), (9, 0), (6, -100 + bob), (-6, -100 + bob)], c.sec, False)
    for x in (-30, -14, 14, 30):
        c.line((x, -3), (x * 0.9, -30), 2, shade(c.main, 1.5))
    c.sph(-26, -100 + bob, 13, c.main)
    c.sph(26, -100 + bob, 13, c.main)
    c.sph(0, -128 + bob, 24, shade(c.main, 0.85))
    c.ell(3, -126 + bob, 15, 17, (10, 6, 20))
    for dx in (-4, 9):
        c.glow(dx, -127 + bob, 3, c.acc)
    fx, fy = 26, -98 + bob
    hand = lerp2((fx + 30, fy + 44), (fx + 62, fy - 12), c.pose)
    c.limb((fx, fy), hand, 9, shade(c.main, 1.15))
    c.limb((-26, fy), (-40, -54 + bob), 9, shade(c.main, 1.15))
    c.glow(hand[0], hand[1], 7, c.acc)


def draw_antimage(c):
    t = c.t
    bob = math.sin(t * 2.2) * 2
    c.poly([(-6, -128 + bob), (-62, -112 + math.sin(t * 4) * 8), (-74, -96 + math.sin(t * 4 + 1) * 8), (-8, -112 + bob)], c.acc, False)
    p = c.humanoid(20, 62, 18, 50, 60, (130, 150, 200), c.main, c.sec, bob)
    hx, hy = p["head"]
    c.poly([(hx - 16, hy - 2), (hx + 17, hy - 2), (hx + 14, hy + 12), (hx - 14, hy + 12)], shade(c.main, 0.8))
    for dx in (4, 11):
        c.glow(hx + dx, hy - 5, 2, c.acc)
    for h, ln in ((p["fhand"], 72), (p["bhand"], 56)):
        tip = (h[0] + ln * 0.75, h[1] - ln * 0.65)
        c.line(h, tip, 5, (215, 225, 255))
        c.glow(tip[0], tip[1], 4, c.acc)


def draw_medusa(c):
    t = c.t
    bob = math.sin(t * 2) * 2
    for i in range(10, -1, -1):
        k = i / 10
        x = -k * 95 + math.sin(t * 2.2 + k * 5) * 7
        y = -50 + min(1, k * 1.5) * 46
        r = 24 * (1 - k * 0.78)
        c.ell(x, y, r, r * 0.85, c.main if i % 2 else shade(c.main, 1.25))
    p = c.humanoid(20, 58, 18, 46, 56, (150, 200, 170), c.sec, c.main, bob, legs=False)
    hx, hy = p["head"]
    for i in range(9):
        a = -math.pi * 0.95 + i * math.pi * 0.9 / 8
        ex = hx + math.cos(a) * 34 + math.sin(t * 3 + i) * 5
        ey = hy + math.sin(a) * 34 - 4
        c.line((hx + math.cos(a) * 12, hy + math.sin(a) * 12), (ex, ey), 4, c.acc)
        c.sph(ex, ey, 4, c.acc)
    for dx in (5, 13):
        c.glow(hx + dx, hy - 2, 2, (255, 240, 90))
    fh = p["fhand"]
    cx, cy, r = fh[0] - 30, fh[1], 58
    c.curve(cx, cy, r, -1.0, 1.0, 4, (235, 210, 140))
    c.line((cx + r * math.cos(-1), cy + r * math.sin(-1)), (cx + r * math.cos(1), cy + r * math.sin(1)), 2, (230, 230, 230))


def draw_drow(c):
    t = c.t
    sway = math.sin(t * 2.5) * 6
    c.poly([(-4, -122), (-52, -20 + sway), (-10, -8), (10, -112)], shade(c.main, 0.8))
    c.poly([(-26, -112), (-14, -120), (-2, -72), (-14, -64)], c.sec)
    p = c.humanoid(18, 60, 17, 52, 58, (190, 200, 225), c.main, c.sec, math.sin(t * 2.2) * 2)
    hx, hy = p["head"]
    c.poly([(hx - 4, hy - 12), (hx - 50, hy + 30 + sway), (hx - 30, hy + 52), (hx + 2, hy + 10)], (235, 235, 250))
    c.poly([(hx - 21, hy + 5), (hx + 1, hy - 28), (hx + 21, hy + 5)], c.main)
    c.glow(hx + 8, hy - 3, 2, c.acc)
    fh = p["fhand"]
    cx, cy, r = fh[0] - 40, fh[1], 74
    c.curve(cx, cy, r, -0.95, 0.95, 4, (210, 190, 140))
    c.line((cx + r * math.cos(-.95), cy + r * math.sin(-.95)), (cx + r * math.cos(.95), cy + r * math.sin(.95)), 2, (235, 235, 235))
    if c.pose > 0.3:
        c.line(fh, (fh[0] + 62, fh[1]), 3, c.acc)


def draw_mars(c):
    t = c.t
    bob = math.sin(t * 2) * 2
    p = c.humanoid(34, 72, 19, 54, 64, (205, 150, 120), c.main, c.sec, bob)
    hx, hy = p["head"]
    c.sph(hx, hy - 6, 21, c.sec)
    c.poly([(hx - 4, hy - 24), (hx - 40, hy - 16), (hx - 36, hy - 2), (hx - 8, hy - 8)], c.acc)
    c.glow(hx + 9, hy + 1, 2, (255, 230, 150))
    b = p["bhand"]
    c.line(b, (b[0] + 12, b[1] - 150), 5, (190, 170, 120))
    c.poly([(b[0] + 6, b[1] - 148), (b[0] + 18, b[1] - 148), (b[0] + 12, b[1] - 182)], (215, 220, 230))
    f = p["fhand"]
    c.ell(f[0] + 16, f[1], 22, 46, c.sec)
    c.ell(f[0] + 18, f[1], 14, 33, c.main)
    c.sph(f[0] + 20, f[1], 7, GOLD)


def draw_axe(c):
    t = c.t
    p = c.humanoid(34, 70, 20, 52, 62, (205, 70, 60), shade(c.main, 1.2), c.sec, math.sin(t * 2) * 2)
    c.poly([(-30, -50), (30, -50), (38, -18), (-38, -18)], c.sec)
    hx, hy = p["head"]
    for i in range(5):
        x = hx - 12 + i * 7
        c.poly([(x - 4, hy - 16), (x, hy - 34 - (2 - abs(i - 2)) * 5), (x + 4, hy - 16)], (150, 30, 30), False)
    for dx in (5, 12):
        c.glow(hx + dx, hy - 2, 2, (255, 230, 120))
    f = p["fhand"]
    c.line(f, (f[0] + 20, f[1] - 74), 6, (120, 80, 50))
    c.poly([(f[0] + 14, f[1] - 78), (f[0] + 56, f[1] - 96), (f[0] + 56, f[1] - 48), (f[0] + 14, f[1] - 62)], (205, 212, 228))
    c.line((f[0] + 56, f[1] - 96), (f[0] + 56, f[1] - 48), 3, c.acc)


def draw_pudge(c):
    t = c.t
    p = c.humanoid(50, 72, 18, 34, 50, (135, 165, 115), (150, 90, 80), c.sec, math.sin(t * 2) * 2)
    c.ell(4, -62, 48, 38, (165, 190, 140))
    c.poly([(-26, -74), (26, -74), (30, -22), (-30, -22)], (140, 50, 50))
    hx, hy = p["head"]
    c.ell(hx + 4, hy + 7, 10, 5, (40, 10, 10))
    for dx in (-5, 0, 5, 10):
        c.line((hx + dx, hy + 4), (hx + dx, hy + 8), 1, (230, 230, 210))
    for dx in (5, 13):
        c.glow(hx + dx, hy - 5, 2, c.acc)
    f = p["fhand"]
    c.line(f, (f[0] + 10, f[1] - 40), 5, (110, 80, 60))
    c.poly([(f[0] - 6, f[1] - 34), (f[0] + 46, f[1] - 40), (f[0] + 50, f[1] - 82), (f[0] - 4, f[1] - 88)], (205, 208, 218))
    b = p["bhand"]
    c.line(b, (b[0] - 46, b[1] - 24), 3, (170, 170, 180))
    c.curve(b[0] - 56, b[1] - 36, 14, 0.4, 4.6, 4, (190, 190, 200))


def draw_hoodwink(c):
    t = c.t
    for i in range(6):
        c.ell(-30 - i * 8, -70 + math.sin(t * 2 + i * 0.5) * 6 - i * 8, 24 - i * 2, 20 - i * 2, c.sec if i % 2 else shade(c.sec, 1.2))
    p = c.humanoid(15, 38, 17, 32, 40, (205, 150, 95), c.main, c.sec, math.sin(t * 2.4) * 2)
    hx, hy = p["head"]
    c.poly([(hx - 14, hy - 10), (hx - 10, hy - 38), (hx - 2, hy - 14)], c.sec)
    c.poly([(hx + 2, hy - 14), (hx + 10, hy - 38), (hx + 14, hy - 10)], c.sec)
    for dx in (3, 11):
        c.glow(hx + dx, hy - 2, 3, (255, 255, 255))
    f = p["fhand"]
    c.line(f, (f[0] + 36, f[1] - 6), 5, (120, 90, 60))
    c.line((f[0] + 24, f[1] - 26), (f[0] + 24, f[1] + 16), 4, (160, 130, 90))
    c.line((f[0] + 24, f[1] - 26), (f[0] + 36, f[1] - 6), 1, WHITE)
    c.line((f[0] + 24, f[1] + 16), (f[0] + 36, f[1] - 6), 1, WHITE)


def draw_grimstroke(c):
    t = c.t
    bob = math.sin(t * 2) * 3
    c.poly([(-36, 0), (36, 0), (18, -122 + bob), (-18, -122 + bob)], c.main)
    c.poly([(-6, 0), (6, 0), (4, -122 + bob), (-4, -122 + bob)], c.sec, False)
    c.sph(-24, -118 + bob, 12, c.main)
    c.sph(24, -118 + bob, 12, c.main)
    c.sph(2, -146 + bob, 19, (215, 200, 160))
    c.ell(2, -156 + bob, 34, 8, shade(c.main, 1.1))
    c.poly([(-14, -156 + bob), (14, -156 + bob), (8, -222 + bob), (-8, -222 + bob)], shade(c.main, 1.1))
    for dx in (-3, 9):
        c.glow(dx, -146 + bob, 2, c.acc)
    fs = (26, -116 + bob)
    hand = lerp2((fs[0] + 34, fs[1] + 40), (fs[0] + 74, fs[1] - 14), c.pose)
    c.limb(fs, hand, 8, shade(c.main, 1.3))
    c.line(hand, (hand[0] + 26, hand[1] - 28), 3, (150, 120, 80))
    c.glow(hand[0] + 28, hand[1] - 30, 6, (20, 10, 40))
    c.limb((-24, -116 + bob), (-44, -62 + bob), 8, shade(c.main, 1.3))
    for i in range(3):
        a = t * 2 + i * 2.1
        c.glow(50 + math.cos(a) * 20, -90 + math.sin(a) * 30, 5, c.acc)


def draw_lion(c):
    t = c.t
    c.poly([(-26, -50), (26, -50), (40, -2), (-40, -2)], c.main)
    p = c.humanoid(22, 54, 18, 46, 58, (95, 175, 150), c.main, c.sec, math.sin(t * 2.3) * 2)
    hx, hy = p["head"]
    c.poly([(hx - 14, hy - 12), (hx - 20, hy - 40), (hx - 5, hy - 16)], (230, 220, 190))
    c.poly([(hx + 4, hy - 16), (hx + 16, hy - 40), (hx + 18, hy - 10)], (230, 220, 190))
    for dx in (5, 12):
        c.glow(hx + dx, hy - 3, 3, c.acc)
    b = p["bhand"]
    c.line(b, (b[0] + 8, b[1] - 112), 4, (150, 110, 70))
    c.glow(b[0] + 8, b[1] - 114, 8, c.acc)
    f = p["fhand"]
    if c.pose > 0.3:
        c.glow(f[0] + 6, f[1], 9, (255, 120, 255))


def draw_roshan(c):
    t = c.t
    bob = math.sin(t * 1.6) * 3
    for i in range(7):
        c.ell(-90 - i * 14, -40 - math.sin(t * 2 + i * 0.5) * 8 - i * 6, 24 - i * 2, 20 - i * 2, c.main)
    c.ell(-48, -20, 34, 24, shade(c.main, 0.8))
    c.ell(48, -20, 34, 24, shade(c.main, 0.8))
    c.ell(0, -100 + bob, 102, 84, c.main)
    c.ell(10, -84 + bob, 62, 50, c.sec)
    c.limb((-78, -126 + bob), (-112, -52), 26, c.main)
    f = lerp2((112, -66 + bob), (138, -140 + bob), c.pose)
    c.limb((78, -126 + bob), f, 26, c.main)
    for h in ((-112, -52), f):
        for k in (-8, 0, 8):
            c.poly([(h[0] + k - 3, h[1]), (h[0] + k + 3, h[1]), (h[0] + k, h[1] + 22)], (235, 225, 200), False)
    c.sph(16, -196 + bob, 44, c.main)
    for s_ in (-1, 1):
        c.poly([(16 + s_ * 28, -224 + bob), (16 + s_ * 58, -270 + bob), (16 + s_ * 44, -216 + bob)], (235, 225, 200))
    for dx in (6, 30):
        c.glow(dx, -200 + bob, 5, c.acc)
    c.ell(24, -176 + bob, 20, 7, (40, 15, 15))


HERO_DRAW = {"invoker": draw_invoker, "antimage": draw_antimage, "medusa": draw_medusa, "drow": draw_drow,
             "mars": draw_mars, "axe": draw_axe, "pudge": draw_pudge, "hoodwink": draw_hoodwink,
             "grimstroke": draw_grimstroke, "lion": draw_lion, "roshan": draw_roshan}


def blit_hero(surf, assets, key, pos, t, pal, pose=0.0, flip=False, alpha=255, flash=0.0):
    """Рисует героя: либо PNG-модель из image/heroes, либо процедурную «3D»-фигуру."""
    sp = assets.hero_sprite(key)
    if sp:
        img = pygame.transform.flip(sp, True, False) if flip else sp.copy()
        rect = img.get_rect(midbottom=(int(pos[0]), int(pos[1])))
    else:
        img = pygame.Surface((460, 460), pygame.SRCALPHA)
        HERO_DRAW[key](Ctx(img, 230, 400, t, pal, pose))
        if flip:
            img = pygame.transform.flip(img, True, False)
        rect = img.get_rect(topleft=(int(pos[0]) - 230, int(pos[1]) - 400))
    if flash > 0:
        f = int(170 * flash)
        img.fill((f, f, f, 0), special_flags=pygame.BLEND_RGB_ADD)
    if alpha < 255:
        img.set_alpha(alpha)
    surf.blit(img, rect)


# ======================================================================
# РЕСУРСЫ (иконки из папки image + запасные процедурные)
# ======================================================================
class Assets:
    def __init__(self, font_fn):
        self.font = font_fn
        self.files, self.models, self.cache = {}, {}, {}
        base = os.path.dirname(os.path.abspath(__file__))
        for folder in ("image", "images", "assets", "Image"):
            root = os.path.join(base, folder)
            if not os.path.isdir(root):
                continue
            for dp, _, fs in os.walk(root):
                for f in fs:
                    stem, ext = os.path.splitext(f)
                    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                        continue
                    rel = os.path.relpath(dp, root).lower()
                    pool = self.models if any(k in rel for k in ("hero", "model", "sprite", "char")) else self.files
                    pool.setdefault(self.norm(stem), os.path.join(dp, f))
        self.found = len(self.files) + len(self.models)

    @staticmethod
    def norm(s):
        return "".join(ch for ch in s.lower() if ch.isalnum())

    def find(self, key, pool=None, strict=False):
        pool = self.files if pool is None else pool
        key = self.norm(key)
        if key in pool:
            return pool[key]
        for n, p in pool.items():
            if n.endswith(key):
                return p
        if not strict and len(key) >= 6:
            for n, p in pool.items():
                if key in n:
                    return p
        return None

    def load(self, path, size=None, height=None):
        k = (path, size, height)
        if k not in self.cache:
            try:
                im = pygame.image.load(path).convert_alpha()
                if size:
                    im = pygame.transform.smoothscale(im, (size, size))
                elif height:
                    w = int(im.get_width() * height / im.get_height())
                    im = pygame.transform.smoothscale(im, (w, height))
            except Exception:
                im = None
            self.cache[k] = im
        return self.cache[k]

    def hero_sprite(self, key):
        p = self.find(key, self.models, strict=True)
        return self.load(p, height=300) if p else None

    def spell_icon(self, name, size):
        k = ("spell", name, size)
        if k not in self.cache:
            p = self.find(name)
            im = self.load(p, size) if p else None
            self.cache[k] = im or self.make_spell_icon(name, size)
        return self.cache[k]

    def orb_icon(self, o, size):
        k = ("orb", o, size)
        if k not in self.cache:
            p = self.find(ORB_NAME[o], strict=True)
            im = self.load(p, size) if p else None
            if not im:
                im = pygame.Surface((size, size), pygame.SRCALPHA)
                glow(im, ORB_COL[o], (size // 2, size // 2), size * 0.28, 3)
                img = self.font(int(size * 0.42), True).render(o, True, (10, 10, 20))
                im.blit(img, img.get_rect(center=(size // 2, size // 2)))
            self.cache[k] = im
        return self.cache[k]

    def invoke_icon(self, size):
        k = ("invoke", size)
        if k not in self.cache:
            p = self.find("invoke", strict=True)
            im = self.load(p, size) if p else None
            if not im:
                im = pygame.Surface((size, size), pygame.SRCALPHA)
                glow(im, GOLD, (size // 2, size // 2), size * 0.28, 3)
                img = self.font(int(size * 0.42), True).render("R", True, (30, 15, 0))
                im.blit(img, img.get_rect(center=(size // 2, size // 2)))
            self.cache[k] = im
        return self.cache[k]

    def make_spell_icon(self, name, size):
        sp = BY_NAME[name]
        col = sp["col"]
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        for y in range(size):
            pygame.draw.line(s, shade(col, 0.22 + 0.35 * (1 - y / size)), (0, y), (size, y))
        glow(s, col, (size // 2, int(size * 0.38)), size * 0.17, 3)
        img = self.font(max(10, int(size * 0.26)), True).render(sp["abbr"], True, (15, 15, 25))
        s.blit(img, img.get_rect(center=(size // 2, int(size * 0.38))))
        for i, ch in enumerate(KEY_BY_NAME[name]):
            pygame.draw.circle(s, ORB_COL[ch], (int(size * (0.28 + 0.22 * i)), int(size * 0.78)), max(3, int(size * 0.08)))
        pygame.draw.rect(s, shade(col, 1.2), (0, 0, size, size), 2)
        return s


# ======================================================================
# ЭФФЕКТЫ И АНИМАЦИИ ЗАКЛИНАНИЙ
# ======================================================================
class Projectile:
    """Летящий снаряд. style: orb / frost / fire / wind / wave."""

    def __init__(self, start, end, col, on_hit, speed=850, radius=11, arc=45, style="orb"):
        self.start, self.end = pygame.Vector2(start), pygame.Vector2(end)
        self.col, self.on_hit, self.radius, self.arc, self.style = col, on_hit, radius, arc, style
        self.dur = max(0.3, self.start.distance_to(self.end) / speed)
        self.t, self.trail, self.done = 0.0, [], False

    def pos(self):
        p = min(1.0, self.t / self.dur)
        e = p * p * (3 - 2 * p)
        v = self.start.lerp(self.end, e)
        v.y -= math.sin(math.pi * p) * self.arc
        return v

    def update(self, dt):
        self.t += dt
        self.trail = (self.trail + [self.pos()])[-14:]
        if self.t >= self.dur and not self.done:
            self.done = True
            self.on_hit()

    def draw(self, surf):
        n = len(self.trail)
        for i, p in enumerate(self.trail):
            glow(surf, self.col, p, max(2, int(self.radius * (i + 1) / n * 0.7)), 2)
        p = self.pos()
        if self.style == "frost":
            pts = []
            for k in range(8):
                a = self.t * 7 + k * math.pi / 4
                r = self.radius * (2.0 if k % 2 == 0 else 0.8)
                pts.append((p.x + r * math.cos(a), p.y + r * math.sin(a)))
            pygame.draw.polygon(surf, (210, 245, 255), pts)
            glow(surf, self.col, p, self.radius * 0.7)
        elif self.style == "wave":
            for k in range(3):
                r = 30 + k * 16
                pts = [(p.x - k * 22 + r * math.cos(a), p.y + r * math.sin(a)) for a in [-0.9 + 1.8 * i / 10 for i in range(11)]]
                pygame.draw.lines(surf, self.col, False, pts, 5 - k)
        elif self.style == "wind":
            for k in range(3):
                a = self.t * 12 + k * 2.1
                glow(surf, self.col, (p.x + math.cos(a) * 14, p.y + math.sin(a) * 14), 5, 2)
            glow(surf, self.col, p, self.radius * 0.7)
        else:
            glow(surf, self.col, p, self.radius * (1 + 0.15 * math.sin(self.t * 30) if self.style == "fire" else 1))


class MeteorFx:
    """Chaos Meteor: огненный шар падает по диагонали сверху."""

    def __init__(self, dst, on_hit):
        self.start, self.end = pygame.Vector2(dst[0] - 460, -80), pygame.Vector2(dst)
        self.dur, self.t, self.trail, self.done, self.on_hit = 0.9, 0.0, [], False, on_hit

    def pos(self):
        return self.start.lerp(self.end, (min(1.0, self.t / self.dur)) ** 1.5)

    def update(self, dt):
        self.t += dt
        self.trail = (self.trail + [self.pos()])[-22:]
        if self.t >= self.dur and not self.done:
            self.done = True
            self.on_hit()

    def draw(self, surf):
        n = len(self.trail)
        for i, p in enumerate(self.trail):
            k = (i + 1) / n
            glow(surf, mix((255, 60, 20), (255, 210, 80), k), (p.x + random.randint(-4, 4), p.y + random.randint(-4, 4)), 4 + 18 * k, 2)
        p = self.pos()
        glow(surf, (255, 90, 30), p, 26)
        glow(surf, (255, 240, 170), p, 12, 2)


class SunStrikeFx:
    """Sun Strike: предупреждающее кольцо на земле, затем столб света."""

    def __init__(self, x, gy, delay, on_hit):
        self.x, self.gy, self.delay, self.on_hit = x, gy, delay, on_hit
        self.t, self.fired, self.done = 0.0, False, False

    def update(self, dt):
        self.t += dt
        if not self.fired and self.t >= self.delay:
            self.fired = True
            self.on_hit()
        if self.t >= self.delay + 0.5:
            self.done = True

    def draw(self, surf):
        if self.t < self.delay:
            k = self.t / self.delay
            r = int(80 - 30 * k)
            s = pygame.Surface((r * 2 + 8, int(r * 0.7) + 8), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (255, 215, 70, 200), (4, 4, r * 2, int(r * 0.7)), 3)
            pygame.draw.ellipse(s, (255, 215, 70, 60), (4, 4, r * 2, int(r * 0.7)))
            surf.blit(s, (self.x - r - 4, self.gy - int(r * 0.35) - 4))
            return
        k = (self.t - self.delay) / 0.5
        w = int(110 * (1 - k * 0.5))
        a = int(255 * (1 - k))
        s = pygame.Surface((w * 2, self.gy + 20), pygame.SRCALPHA)
        for frac, col in ((1.0, (255, 150, 30)), (0.65, (255, 220, 80)), (0.32, (255, 255, 230))):
            ww = int(w * frac)
            pygame.draw.rect(s, (*col, int(a * 0.55 + 40 * frac)), (w - ww, 0, ww * 2, self.gy + 20))
        surf.blit(s, (self.x - w, 0))
        glow(surf, (255, 230, 120), (self.x, self.gy), 30 * (1 - k) + 6)


class IceWallFx:
    """Ice Wall: ряд ледяных шипов вырастает между героями."""

    def __init__(self, x, gy):
        self.x, self.gy, self.t, self.done = x, gy, 0.0, False
        self.spikes = [(x - 70 + i * 24, random.randint(70, 130), i * 0.05) for i in range(7)]

    def update(self, dt):
        self.t += dt
        if self.t > 3.4:
            self.done = True

    def draw(self, surf):
        fade = 1.0 if self.t < 2.9 else max(0.0, 1 - (self.t - 2.9) / 0.5)
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        for x, hgt, d in self.spikes:
            k = max(0.0, min(1.0, (self.t - d) / 0.25))
            h = hgt * k
            pts = [(x - 14, self.gy), (x + 14, self.gy), (x + 4, self.gy - h)]
            pygame.draw.polygon(s, (150, 225, 255, int(210 * fade)), pts)
            pygame.draw.polygon(s, (235, 250, 255, int(255 * fade)), [(x - 14, self.gy), (x - 2, self.gy), (x + 4, self.gy - h)])
            pygame.draw.polygon(s, (60, 130, 200, int(255 * fade)), pts, 2)
        surf.blit(s, (0, 0))


class TornadoFx:
    """Tornado: воронка вокруг врага, враг подбрасывается."""

    def __init__(self, enemy, x, gy, dur=1.8):
        self.e, self.x, self.gy, self.dur, self.t, self.done = enemy, x, gy, dur, 0.0, False

    def update(self, dt):
        self.t += dt
        self.e.lift = 60 * math.sin(math.pi * min(1.0, self.t / self.dur))
        if self.t >= self.dur:
            self.e.lift = 0
            self.done = True

    def draw(self, surf):
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        a = int(200 * min(1.0, (self.dur - self.t) / 0.3 + 0.0)) if self.t > self.dur - 0.3 else 200
        for i in range(10):
            k = i / 9
            y = self.gy - k * 230
            rx = 16 + k * 52
            off = math.sin(self.t * 9 + i) * 8
            pygame.draw.ellipse(s, (200, 180, 255, max(0, a)), (self.x - rx + off, y - 8, rx * 2, 18), 3)
        surf.blit(s, (0, 0))


class EmpFx:
    """EMP: сходящееся кольцо на земле, затем взрыв."""

    def __init__(self, x, gy, delay, on_hit):
        self.x, self.gy, self.delay, self.on_hit = x, gy, delay, on_hit
        self.t, self.fired, self.done = 0.0, False, False

    def update(self, dt):
        self.t += dt
        if not self.fired and self.t >= self.delay:
            self.fired = True
            self.on_hit()
        if self.t > self.delay + 0.4:
            self.done = True

    def draw(self, surf):
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        col = (210, 110, 255)
        if self.t < self.delay:
            k = self.t / self.delay
            r = int(130 - 70 * k)
            pygame.draw.ellipse(s, (*col, 220), (self.x - r, self.gy - r // 3, r * 2, int(r * 0.66)), 3)
            for i in range(6):
                a = i * math.pi / 3 + self.t * 6
                pygame.draw.line(s, (*col, 160), (self.x + math.cos(a) * r, self.gy + math.sin(a) * r * 0.33), (self.x, self.gy), 2)
        else:
            k = (self.t - self.delay) / 0.4
            r = int(60 + 140 * k)
            a = int(255 * (1 - k))
            pygame.draw.ellipse(s, (*col, a), (self.x - r, self.gy - r // 3, r * 2, int(r * 0.66)), 5)
            for i in range(5):
                x = self.x + random.randint(-60, 60)
                pygame.draw.line(s, (240, 200, 255, a), (x, self.gy), (x + random.randint(-14, 14), self.gy - random.randint(80, 200)), 3)
        surf.blit(s, (0, 0))


class PulseFx:
    """Расширяющееся кольцо (Invoke, Ghost Walk, Alacrity...)."""

    def __init__(self, pos, col, r0=10, r1=90, dur=0.5):
        self.pos, self.col, self.r0, self.r1, self.dur, self.t, self.done = pos, col, r0, r1, dur, 0.0, False

    def update(self, dt):
        self.t += dt
        self.done = self.t >= self.dur

    def draw(self, surf):
        k = min(1.0, self.t / self.dur)
        r = int(self.r0 + (self.r1 - self.r0) * k)
        s = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.col, int(230 * (1 - k))), (r + 4, r + 4), r, 4)
        surf.blit(s, (self.pos[0] - r - 4, self.pos[1] - r - 4))


class Flash:
    """Вспышка при попадании: кольцо + искры."""

    def __init__(self, pos, color, big=False):
        self.pos, self.color = pos, color
        self.life = self.max = 0.5
        self.size = 95 if big else 55
        self.sparks = [(random.uniform(0, 6.28), random.uniform(80, 240)) for _ in range(16 if big else 8)]
        self.done = False

    def update(self, dt):
        self.life -= dt
        self.done = self.life <= 0

    def draw(self, surf):
        p = 1 - self.life / self.max
        r = int(self.size * (0.3 + p))
        s = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
        a = int(255 * (1 - p))
        pygame.draw.circle(s, (*self.color, a // 3), (r + 4, r + 4), r)
        pygame.draw.circle(s, (*self.color, a), (r + 4, r + 4), r, 4)
        surf.blit(s, (int(self.pos[0]) - r - 4, int(self.pos[1]) - r - 4))
        for ang, sp in self.sparks:
            d = sp * p
            pygame.draw.circle(surf, tuple(min(255, v + 60) for v in self.color),
                               (int(self.pos[0] + math.cos(ang) * d), int(self.pos[1] + math.sin(ang) * d)), max(1, int(4 * (1 - p))))


class FloatText:
    def __init__(self, text, pos, color, size=28):
        self.text, self.x, self.y, self.color, self.size, self.life = text, pos[0], pos[1], color, size, 1.3

    def update(self, dt):
        self.life -= dt
        self.y -= 45 * dt

    def draw(self, surf, font):
        f = font(self.size, True)
        a = int(255 * max(0.0, min(1.0, self.life / 0.5)))
        for col, off in (((0, 0, 0), 2), (self.color, 0)):
            img = f.render(self.text, True, col)
            img.set_alpha(a)
            surf.blit(img, img.get_rect(center=(self.x + off, self.y + off)))


class Spirit:
    """Forge Spirit: огненный дух рядом с героем, периодически бьёт врага."""

    def __init__(self, wm):
        self.life, self.nxt, self.wm, self.t = 6.0, 0.7, wm, 0.0

    def update(self, dt, g):
        self.t += dt
        self.life -= dt
        self.nxt -= dt
        if self.nxt <= 0 and g.enemy.alive and g.state == "battle":
            self.nxt = 1.0
            g.spirit_strike(self)

    def pos(self):
        return (PLAYER_POS[0] + 105, PLAYER_POS[1] - 35 + math.sin(self.t * 4) * 6)

    def draw(self, surf):
        x, y = self.pos()
        glow(surf, (255, 110, 40), (x, y), 18)
        for i in range(5):
            h = 24 + 14 * math.sin(self.t * 9 + i * 1.7)
            pygame.draw.polygon(surf, (255, 190 - i * 12, 60), [(x - 14 + i * 7, y - 6), (x - 8 + i * 7, y - 6 - h), (x - 2 + i * 7, y - 6)])
        for dx in (-6, 6):
            pygame.draw.circle(surf, (255, 255, 200), (int(x + dx), int(y - 2)), 3)


# ======================================================================
# ПЕРСОНАЖИ
# ======================================================================
class Player:
    def __init__(self):
        self.max_hp = self.hp = 120
        self.gold = 0
        self.orbs = deque(maxlen=3)
        self.slots = [None, None]      # D и F: призванные заклинания
        self.cd = {}                   # перезарядки заклинаний по названию
        self.invoke_cd = 0.0
        self.skin = 0
        self.evade = self.alacrity = self.silence = self.snare = self.ink = 0.0
        self.pose_t = self.shake = self.flash = 0.0

    def pal(self):
        s = SKINS_PLAYER[self.skin]
        return (s["main"], s["sec"], s["acc"])

    def draw(self, surf, t, assets):
        sh = math.sin(t * 90) * 8 * min(1, self.shake / 0.3) if self.shake > 0 else 0
        pos = (PLAYER_POS[0] + sh, PLAYER_POS[1])
        ghost = self.evade > 0
        blit_hero(surf, assets, "invoker", pos, t, self.pal(), min(1.0, self.pose_t / 0.3),
                  alpha=130 if ghost else 255, flash=self.flash)
        # сферы вращаются вокруг головы
        hc = (PLAYER_POS[0], PLAYER_POS[1] - 128)
        for i, o in enumerate(self.orbs):
            a = t * 2.8 + i * 2 * math.pi / 3
            glow(surf, ORB_COL[o], (hc[0] + math.cos(a) * 52, hc[1] + math.sin(a) * 16), 9)
        # статусы
        if ghost:
            for i in range(5):
                a = t * 3 + i * 1.3
                glow(surf, (170, 225, 245), (PLAYER_POS[0] + math.cos(a) * 55, PLAYER_POS[1] - 60 + math.sin(a * 1.3) * 60), 5, 2)
        if self.alacrity > 0:
            for i in range(6):
                k = (t * 1.2 + i / 6) % 1
                glow(surf, (255, 190, 70), (PLAYER_POS[0] + math.sin(i * 2.3) * 45, PLAYER_POS[1] - k * 170), 4, 2)
        if self.silence > 0:
            pygame.draw.circle(surf, RED, (PLAYER_POS[0], PLAYER_POS[1] - 175), 14, 3)
            pygame.draw.line(surf, RED, (PLAYER_POS[0] - 10, PLAYER_POS[1] - 165), (PLAYER_POS[0] + 10, PLAYER_POS[1] - 185), 3)
        if self.snare > 0:
            pygame.draw.ellipse(surf, (120, 200, 90), (PLAYER_POS[0] - 50, PLAYER_POS[1] - 10, 100, 20), 4)
        if self.ink > 0:
            for i in range(4):
                glow(surf, (150, 80, 220), (PLAYER_POS[0] + math.cos(t + i * 1.6) * 40, PLAYER_POS[1] - 70 + i * 14), 6, 2)


class Enemy:
    def __init__(self, key, wave, skin):
        d = HEROES[key]
        k = wave - 1
        self.key, self.name, self.cls = key, d["name"], d["cls"]
        self.col = d["pal"][2]
        self.max_hp = self.hp = int(d["hp"] * (1 + 0.18 * k))
        self.dmg = int(d["dmg"] * (1 + 0.08 * k))
        self.rt = d["rt"]
        self.shield = self.max_shield = int(d["shield"] * (1 + 0.18 * k))
        self.gold = int(d["gold"] * (1 + 0.1 * k))
        self.weak, self.resist, self.debuff = d["weak"], d["resist"], d["debuff"]
        self.script = [dict(s, done=False) for s in d["script"]]
        self.skin = skin
        self.pal = tint(d["pal"], skin)
        self.progress, self.hits, self.round = 0.0, 0, 1
        self.pause = self.slow = self.burn = self.burn_tick = 0.0
        self.frozen = self.stun_vis = self.lift = 0.0
        self.shake = self.lunge = self.flash = 0.0
        self.dying = 0.0
        self.visible = True

    @property
    def alive(self):
        return self.hp > 0

    def take_damage(self, d):
        absorbed = 0
        if self.shield > 0:
            absorbed = min(self.shield, d)
            self.shield -= absorbed
            d -= absorbed
        self.hp = max(0, self.hp - d)
        self.shake, self.flash = 0.3, 1.0
        return d, absorbed

    def reset_round(self):
        self.progress, self.hits = 0.0, 0
        self.round += 1
        for s in self.script:
            s["done"] = False

    def draw(self, surf, t, assets):
        if not self.visible:
            return
        sh = math.sin(t * 90) * 8 * min(1, self.shake / 0.3) if self.shake > 0 else 0
        p = 1 - self.lunge / 0.6 if self.lunge > 0 else 0
        x = ENEMY_POS[0] + sh - 70 * math.sin(math.pi * p)
        y = ENEMY_POS[1] - self.lift
        alpha = int(255 * min(1.0, self.dying / 1.2)) if self.dying > 0 else 255
        blit_hero(surf, assets, self.key, (x, y), t, self.pal, min(1.0, self.lunge / 0.4),
                  flip=True, alpha=alpha, flash=self.flash)
        if self.dying > 0:
            return
        cx, cy = x, y - 100
        if self.shield > 0:  # Mana Shield
            pygame.draw.circle(surf, CYAN, (int(cx), int(cy)), 118, 3)
            glow(surf, CYAN, (cx + 118 * math.cos(t * 2), cy + 118 * math.sin(t * 2)), 5, 2)
        if self.frozen > 0:  # лёд
            s = pygame.Surface((300, 300), pygame.SRCALPHA)
            for i in range(9):
                a = i * 2 * math.pi / 9
                bx, by = 150 + math.cos(a) * 70, 150 + math.sin(a) * 100
                pygame.draw.polygon(s, (170, 230, 255, 170), [(bx - 9, by + 14), (bx + 9, by + 14), (bx, by - 30)])
                pygame.draw.polygon(s, (240, 252, 255, 220), [(bx - 9, by + 14), (bx, by + 14), (bx, by - 30)])
            surf.blit(s, (int(cx) - 150, int(cy) - 150))
        if self.stun_vis > 0:  # звёздочки
            for i in range(3):
                a = t * 5 + i * 2.1
                pygame.draw.circle(surf, GOLD, (int(cx + math.cos(a) * 30), int(y - 250 + math.sin(a) * 8)), 6)
        if self.burn > 0:  # огонь
            for i in range(7):
                fx = cx - 50 + i * 17
                h = 30 + 18 * math.sin(t * 11 + i * 1.3)
                pygame.draw.polygon(surf, (255, 120, 30), [(fx - 8, cy + 40), (fx, cy + 40 - h), (fx + 8, cy + 40)])
                pygame.draw.polygon(surf, (255, 220, 90), [(fx - 4, cy + 40), (fx, cy + 40 - h * 0.6), (fx + 4, cy + 40)])


# ======================================================================
# МАГАЗИН (ОТЛОЖЕН)
# ======================================================================
class Item:
    def __init__(self, kind, name, cost, category):
        self.kind, self.name, self.cost, self.category = kind, name, cost, category


class Shop:
    """ЗАГЛУШКА. Магазин и предметы сделаем в самом конце (SHOP_ENABLED = False)."""
    enabled = SHOP_ENABLED
    items = []


# ======================================================================
# ИГРА
# ======================================================================
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Invoker: Procast Trainer (прототип v2)")
        self.clock = pygame.time.Clock()
        self._fonts = {}
        self.assets = Assets(self.font)
        self.bg = self.make_background()
        self.shop = Shop()
        self.t = 0.0
        self.reset()

    # ---------- служебное ----------
    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = pygame.font.SysFont("segoeui,arial,dejavusans,verdana", size, bold=bold)
        return self._fonts[key]

    def text(self, s, size, color, pos, anchor="topleft", bold=False):
        img = self.font(size, bold).render(s, True, color)
        r = img.get_rect(**{anchor: pos})
        self.screen.blit(img, r)
        return r

    def make_background(self):
        bg = pygame.Surface((W, H))
        for y in range(H):
            k = y / H
            pygame.draw.line(bg, (int(8 + 16 * k), int(8 + 8 * k), int(22 + 26 * k)), (0, y), (W, y))
        for i in range(12):
            yy = 420 + i * i * 0.9 + i * 6
            pygame.draw.line(bg, (30, 30, 64), (0, yy), (W, yy))
        for x in range(-400, W + 400, 90):
            pygame.draw.line(bg, (26, 26, 56), (W // 2, 380), (x, 590))
        for pos, col in ((PLAYER_POS, (90, 60, 200)), (ENEMY_POS, (200, 60, 90))):  # платформы
            s = pygame.Surface((260, 70), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (*col, 60), (0, 0, 260, 70))
            pygame.draw.ellipse(s, (*col, 160), (0, 0, 260, 70), 3)
            bg.blit(s, (pos[0] - 130, pos[1] - 28))
        return bg

    def hit(self, rect, cb):
        self.buttons.append((rect, cb))

    def schedule(self, delay, fn):
        self.queue.append([delay, fn])

    def say(self, s, t=2.5):
        self.msg, self.msg_t = s, t

    def float_at(self, pos, s, color, size=28):
        self.texts.append(FloatText(s, (pos[0] + random.randint(-25, 25), pos[1] - 70), color, size))

    def flash(self, pos, color, big=False):
        self.fx.append(Flash(pos, color, big))

    # ---------- состояние ----------
    def reset(self):
        self.player = Player()
        self.wave = 1
        self.state = "battle"        # battle / victory / gameover
        self.fx, self.texts, self.spirits, self.queue, self.buttons = [], [], [], [], []
        self.acting = False
        self.show_help = False
        self.banner = None
        self.last_hero = None
        self.msg, self.msg_t = "Собери 3 сферы (Q/W/E) → R (Invoke) → кастуй D/F в подсвеченные окна!", 7
        self.spawn_enemy()

    def spawn_enemy(self):
        if self.wave % 5 == 0:
            key = "roshan"
        else:
            key = random.choice([k for k, h in HEROES.items() if h["cls"] != "boss" and k != self.last_hero])
        self.last_hero = key
        self.enemy = Enemy(key, self.wave, random.randrange(len(ENEMY_SKINS)))
        self.acting = False
        self.spirits = []
        info = CLASS_INFO[self.enemy.cls]
        self.banner = (f"{self.enemy.name} — {info['label']}", info["col"], 2.2)

    # ---------- ввод ----------
    def combo_key(self):
        seq = "".join(self.player.orbs)
        if sorted(seq) == ["E", "Q", "W"]:
            return "QWE"
        if STRICT_ORDER:
            return seq
        cnt = Counter(seq).most_common()
        return cnt[0][0] * 3 if len(cnt) == 1 else cnt[0][0] * 2 + cnt[1][0]

    def add_orb(self, k):
        if self.state == "gameover":
            return
        self.player.orbs.append(k)

    def invoke(self):
        p = self.player
        if self.state == "gameover":
            return
        if p.snare > 0:
            self.say("Корни! Invoke недоступен")
            return
        if p.invoke_cd > 0:
            self.say(f"Invoke перезаряжается: {p.invoke_cd:.1f}с")
            return
        if len(p.orbs) < 3:
            self.say("Нужно 3 сферы!")
            return
        sp = SPELLS.get(self.combo_key())
        if not sp:
            self.say(f"Нет заклинания {''.join(p.orbs)} — проверь порядок сфер")
            return
        name = sp["name"]
        rest = [s for s in p.slots if s != name]
        p.slots = ([name] + rest[:1] + [None, None])[:2]
        p.invoke_cd = INVOKE_CD
        p.pose_t = 0.3
        self.fx.append(PulseFx((PLAYER_POS[0] + 40, PLAYER_POS[1] - 110), sp["col"], 8, 70, 0.45))
        self.say(f"Invoke: {name}", 1.2)

    def cast_slot(self, i):
        p, e = self.player, self.enemy
        if self.state != "battle":
            return
        if p.silence > 0:
            self.say("Безмолвие! Нельзя кастовать")
            return
        name = p.slots[i]
        if not name:
            self.say("Слот пуст — сделай Invoke (R)")
            return
        if p.cd.get(name, 0) > 0:
            self.say(f"{name} на перезарядке: {p.cd[name]:.1f}с")
            return
        sp = BY_NAME[name]
        p.cd[name] = sp["cd"]
        p.pose_t = 0.45
        inwin = self.check_window(name)
        self.launch(sp, 1.0 if inwin else OFF_WINDOW_MULT)

    def check_window(self, name):
        """Попал ли каст в тайминг-окно подходящим заклинанием."""
        e = self.enemy
        if self.acting or not e.alive:
            return False
        for st in e.script:
            if st["a"] <= e.progress <= st["b"]:
                if not st["done"] and name in st["spells"]:
                    st["done"] = True
                    e.hits += 1
                    self.float_at(ENEMY_C, f"ТАЙМИНГ {e.hits}/{len(e.script)}!", GREEN, 32)
                    self.flash((ENEMY_C[0], ENEMY_C[1] - 30), GREEN)
                    return True
                return False
        return False

    # ---------- запуск и результат заклинаний ----------
    def hand(self):
        return (PLAYER_POS[0] + 75, PLAYER_POS[1] - 112)

    def launch(self, sp, wm):
        n, col, p, e = sp["name"], sp["col"], self.player, self.enemy
        src = self.hand()
        if n == "Cold Snap":
            self.fx.append(Projectile(src, ENEMY_C, col, lambda: self.on_cold_snap(sp, wm), style="frost"))
        elif n == "Ghost Walk":
            p.evade = 8.0
            self.fx.append(PulseFx((PLAYER_C[0], PLAYER_C[1]), col, 20, 120, 0.7))
            self.float_at(PLAYER_C, "Ghost Walk", col, 26)
        elif n == "Ice Wall":
            self.fx.append(IceWallFx(ENEMY_POS[0] - 170, GROUND_Y))
            self.schedule(0.35, lambda: self.on_ice_wall(sp, wm))
        elif n == "EMP":
            self.fx.append(EmpFx(ENEMY_POS[0], GROUND_Y, 0.55, lambda: self.on_emp(sp, wm)))
        elif n == "Tornado":
            self.fx.append(Projectile(src, ENEMY_C, col, lambda: self.on_tornado(sp, wm), style="wind", speed=950))
        elif n == "Alacrity":
            p.alacrity = 6.0
            self.fx.append(PulseFx(PLAYER_C, col, 20, 110, 0.6))
            self.float_at(PLAYER_C, "+40% урона", col, 26)
        elif n == "Sun Strike":
            self.fx.append(SunStrikeFx(ENEMY_POS[0], GROUND_Y, 0.8, lambda: self.on_sun_strike(sp, wm)))
        elif n == "Forge Spirit":
            self.spirits = [Spirit(wm)]
            self.fx.append(PulseFx((PLAYER_POS[0] + 105, PLAYER_POS[1] - 35), col, 10, 80, 0.5))
        elif n == "Chaos Meteor":
            self.fx.append(MeteorFx(ENEMY_C, lambda: self.on_meteor(sp, wm)))
        elif n == "Deafening Blast":
            self.fx.append(Projectile(src, ENEMY_C, col, lambda: self.on_blast(sp, wm), style="wave", speed=700, arc=10))

    def dmg_enemy(self, base, name, col, wm=1.0, big=False):
        e, p = self.enemy, self.player
        if not e.alive or self.state != "battle":
            return
        mult = e.weak.get(name, 1.0) * e.resist.get(name, 1.0) * wm * (ALACRITY_MULT if p.alacrity > 0 else 1.0)
        d, absorbed = e.take_damage(max(1, int(base * mult)))
        if absorbed:
            self.float_at(ENEMY_C, f"-{absorbed}", CYAN, 24)
        if d:
            note = " ▲" if e.weak.get(name, 1) > 1 else (" ▼" if e.resist.get(name, 1) < 1 else "")
            self.float_at(ENEMY_C, f"-{d}{note}", col, 40 if big else 30)
        self.check_dead()

    def on_cold_snap(self, sp, wm):
        e = self.enemy
        self.flash(ENEMY_C, sp["col"], True)
        e.frozen, e.pause = 1.4, max(e.pause, 1.2)
        self.dmg_enemy(26, sp["name"], sp["col"], wm, True)

    def on_ice_wall(self, sp, wm):
        self.flash((ENEMY_POS[0] - 170, GROUND_Y - 40), sp["col"])
        self.enemy.slow = 5.0
        self.float_at(ENEMY_C, "Замедление", sp["col"], 24)
        self.dmg_enemy(14, sp["name"], sp["col"], wm)

    def on_emp(self, sp, wm):
        e = self.enemy
        self.flash(ENEMY_C, sp["col"], True)
        if e.shield > 0:
            e.shield = 0
            self.float_at(ENEMY_C, "Щит сожжён!", CYAN, 28)
        self.dmg_enemy(18, sp["name"], sp["col"], wm, True)

    def on_tornado(self, sp, wm):
        e = self.enemy
        self.flash(ENEMY_C, sp["col"])
        e.pause = max(e.pause, 1.8)
        self.fx.append(TornadoFx(e, ENEMY_POS[0], GROUND_Y))
        self.float_at(ENEMY_C, "Подброс!", sp["col"], 26)
        self.dmg_enemy(12, sp["name"], sp["col"], wm)

    def on_sun_strike(self, sp, wm):
        self.flash((ENEMY_POS[0], GROUND_Y - 60), sp["col"], True)
        self.dmg_enemy(48, sp["name"], sp["col"], wm, True)

    def on_meteor(self, sp, wm):
        e = self.enemy
        self.flash(ENEMY_C, sp["col"], True)
        self.flash((ENEMY_C[0], GROUND_Y - 20), (255, 220, 100), True)
        e.burn, e.burn_tick = 4.0, 1.0
        self.dmg_enemy(34, sp["name"], sp["col"], wm, True)

    def on_blast(self, sp, wm):
        e = self.enemy
        self.flash(ENEMY_C, sp["col"], True)
        e.pause, e.stun_vis = max(e.pause, 2.6), 2.6
        self.float_at(ENEMY_C, "Оглушён!", sp["col"], 28)
        self.dmg_enemy(18, sp["name"], sp["col"], wm, True)

    def spirit_strike(self, sp):
        pos = sp.pos()
        self.fx.append(Projectile(pos, ENEMY_C, (255, 140, 50),
                                  lambda: (self.flash(ENEMY_C, (255, 140, 50)),
                                           self.dmg_enemy(8, "Forge Spirit", (255, 160, 70), sp.wm)),
                                  speed=900, radius=8, arc=20, style="fire"))

    # ---------- раунд врага ----------
    def check_dead(self):
        e = self.enemy
        if e.hp > 0 or self.state != "battle":
            return
        self.state = "victory"
        e.dying = 1.2
        self.acting = False
        self.spirits = []
        self.flash(ENEMY_C, GOLD, True)
        p = self.player
        p.gold += e.gold
        heal = int(p.max_hp * 0.25)
        p.hp = min(p.max_hp, p.hp + heal)
        self.float_at(ENEMY_C, f"+{e.gold} ★", GOLD, 38)
        self.float_at(PLAYER_C, f"+{heal} HP", GREEN, 28)
        self.say(f"{e.name} повержен! Пробел — дальше", 3)
        self.schedule(2.6, self.next_wave)

    def next_wave(self):
        if self.state != "victory":
            return
        self.wave += 1
        self.state = "battle"
        self.spawn_enemy()

    def enemy_act(self):
        """Конец раунда: итог прокаста решает, что сделает враг."""
        e = self.enemy
        self.acting = True
        steps, hits = len(e.script), e.hits
        if hits == steps:
            self.banner = ("ИДЕАЛЬНЫЙ ПРОКАСТ!", GOLD, 2.0)
            mode = CLASS_INFO[e.cls]["perfect"]
            if mode == "kill":
                self.say("Враг не успел ничего сделать — убит прокастом!", 3)
                self.flash(ENEMY_C, GOLD, True)
                e.hp, e.shake = 0, 0.3
                self.check_dead()
                return
            if e.cls in ("tank", "boss"):  # бонус за идеальный прокаст: 20% от макс. HP
                self.dmg_enemy(int(e.max_hp * 0.2), "bonus", GOLD, 1.0, True)
                if self.state != "battle":
                    return
            if mode == "weaken":  # враг всё же бьёт, но на 80% слабее
                self.float_at(ENEMY_C, "УДАР ОСЛАБЛЕН −80%", GOLD, 28)
                e.lunge = 0.6
                dmg = int(e.dmg * 0.2)
                self.schedule(0.35, lambda: self.enemy_fire(dmg, False))
                return
            self.float_at(ENEMY_C, "ПРОПУСК ХОДА", GOLD, 30)
            self.schedule(1.0, self.next_round)
            return
        red = 0.55 * hits / steps
        dmg = int(e.dmg * (1 - red))
        self.say(f"Прокаст {hits}/{steps}: урон по тебе −{int(red * 100)}%", 2.5)
        e.lunge = 0.6
        self.schedule(0.35, lambda: self.enemy_fire(dmg, hits < steps))

    def enemy_fire(self, dmg, with_debuff):
        e = self.enemy
        if not e.alive or self.state != "battle":
            return
        self.fx.append(Projectile((ENEMY_POS[0] - 60, ENEMY_POS[1] - 110), (PLAYER_C[0] + 20, PLAYER_C[1]),
                                  e.col, lambda: self.hit_player(dmg, e.debuff if with_debuff else None),
                                  speed=700, radius=13))

    def hit_player(self, dmg, debuff):
        p = self.player
        self.flash(PLAYER_C, RED)
        if p.evade > 0:
            p.evade = 0
            self.float_at(PLAYER_C, "Уклонение!", CYAN, 30)
        else:
            p.hp -= dmg
            p.shake, p.flash = 0.3, 1.0
            self.float_at(PLAYER_C, f"-{dmg}", RED, 36)
            if debuff:
                txt, dur = DEBUFF_TEXT[debuff]
                setattr(p, debuff, dur)
                self.say(txt, 3)
        if p.hp <= 0:
            p.hp = 0
            self.state = "gameover"
            return
        self.schedule(0.5, self.next_round)

    def next_round(self):
        e = self.enemy
        if self.state != "battle" or not e.alive:
            return
        e.reset_round()
        self.acting = False
        self.banner = (f"Раунд {e.round}", WHITE, 1.0)

    # ---------- обновление ----------
    def update(self, dt):
        self.t += dt
        p, e = self.player, self.enemy
        rate = 0.5 if p.ink > 0 else 1.0
        for k in list(p.cd):
            p.cd[k] = max(0.0, p.cd[k] - dt * rate)
        p.invoke_cd = max(0.0, p.invoke_cd - dt * rate)
        for a in ("evade", "alacrity", "silence", "snare", "ink", "pose_t", "shake", "flash"):
            setattr(p, a, max(0.0, getattr(p, a) - dt))
        for a in ("shake", "flash", "lunge", "frozen", "stun_vis"):
            setattr(e, a, max(0.0, getattr(e, a) - dt * (3 if a == "flash" else 1)))
        if e.dying > 0:
            e.dying = max(0.0, e.dying - dt)
            if e.dying == 0:
                e.visible = False
        if self.state == "battle" and e.alive:
            if e.burn > 0:  # поджог
                e.burn -= dt
                e.burn_tick -= dt
                if e.burn_tick <= 0:
                    e.burn_tick += 1.0
                    self.dmg_enemy(5, "Chaos Meteor", (255, 130, 50), 1.0)
            for sp in self.spirits:
                sp.update(dt, self)
            self.spirits = [s for s in self.spirits if s.life > 0]
            if self.state == "battle" and not self.acting:
                if e.pause > 0:
                    e.pause -= dt
                else:
                    e.progress += dt / e.rt * (0.55 if e.slow > 0 else 1.0)
                if e.slow > 0:
                    e.slow -= dt
                if e.progress >= 1.0:
                    e.progress = 1.0
                    self.enemy_act()
        for item in self.queue[:]:
            item[0] -= dt
            if item[0] <= 0:
                self.queue.remove(item)
                item[1]()
        for f in self.fx[:]:
            f.update(dt)
        self.fx = [f for f in self.fx if not f.done]
        for tx in self.texts:
            tx.update(dt)
        self.texts = [tx for tx in self.texts if tx.life > 0]
        self.msg_t = max(0.0, self.msg_t - dt)
        if self.banner:
            n, c, tt = self.banner
            self.banner = (n, c, tt - dt) if tt - dt > 0 else None

    # ---------- отрисовка: интерфейс ----------
    def draw_bar(self, rect, ratio, color, label):
        pygame.draw.rect(self.screen, (30, 10, 20), rect, border_radius=8)
        fw = int(rect.w * max(0, min(1, ratio)))
        if fw > 0:
            pygame.draw.rect(self.screen, color, pygame.Rect(rect.x, rect.y, fw, rect.h), border_radius=8)
            pygame.draw.rect(self.screen, tuple(min(255, v + 80) for v in color), (rect.x + 4, rect.y + 3, max(0, fw - 8), rect.h // 3), border_radius=4)
        pygame.draw.rect(self.screen, tuple(min(255, v + 40) for v in color), rect, 2, border_radius=8)
        self.text(label, 16, WHITE, rect.center, "center", True)

    def draw_hud(self):
        p, e = self.player, self.enemy
        r = p.hp / p.max_hp
        self.draw_bar(pygame.Rect(20, 16, 360, 26), r, (int(255 * (1 - r) + 60 * r), int(70 * (1 - r) + 220 * r), 90), f"HP {p.hp}/{p.max_hp}")
        self.text(f"ИНВОКЕР · {SKINS_PLAYER[p.skin]['name']}", 15, (190, 130, 255), (22, 46), "topleft", True)
        st = []
        if p.evade > 0:
            st.append(f"уклонение {p.evade:.0f}с")
        if p.alacrity > 0:
            st.append(f"Alacrity {p.alacrity:.0f}с")
        if p.silence > 0:
            st.append(f"безмолвие {p.silence:.1f}с")
        if p.snare > 0:
            st.append(f"корни {p.snare:.1f}с")
        if p.ink > 0:
            st.append(f"чернила {p.ink:.1f}с")
        if st:
            self.text(", ".join(st), 15, (255, 220, 120), (22, 66))
        self.text(f"Волна {self.wave}", 22, WHITE, (W // 2, 10), "midtop", True)
        self.text(f"★ {p.gold}", 22, GOLD, (W // 2, 38), "midtop", True)
        er = e.hp / e.max_hp
        self.draw_bar(pygame.Rect(W - 380, 16, 360, 26), er, (230, 60, 80), f"HP {e.hp}/{e.max_hp}")
        if e.max_shield > 0:
            pygame.draw.rect(self.screen, (10, 30, 40), (W - 380, 46, 360, 7), border_radius=3)
            pygame.draw.rect(self.screen, CYAN, (W - 380, 46, int(360 * e.shield / e.max_shield), 7), border_radius=3)
        info = CLASS_INFO[e.cls]
        badge = self.text(f" {info['label']} ", 14, (10, 10, 20), (W - 22, 58), "topright", True)
        pygame.draw.rect(self.screen, info["col"], badge.inflate(6, 2), border_radius=5)
        self.text(f" {info['label']} ", 14, (10, 10, 20), badge.topleft, "topleft", True)
        self.text(f"{e.name} · {ENEMY_SKINS[e.skin]}", 20, WHITE, (badge.left - 10, 55), "topright", True)
        if SHOW_HINTS:
            w = ", ".join(f"{k}×{v}" for k, v in e.weak.items())
            rs = ", ".join(f"{k}×{v}" for k, v in e.resist.items())
            self.text("Слабость: " + (w or "—"), 14, (255, 170, 80), (W - 22, 82), "topright")
            if rs:
                self.text("Резист: " + rs, 14, (150, 170, 220), (W - 22, 98), "topright")
            self.text(info["text"], 13, (140, 140, 170), (22, 86), "topleft")

    def draw_timeline(self):
        e, s = self.enemy, self.screen
        x0, x1, y, h = 190, 910, 122, 32
        w = x1 - x0
        pygame.draw.rect(s, (18, 18, 36), (x0 - 4, y - 4, w + 8, h + 8), border_radius=8)
        for st in e.script:
            r = pygame.Rect(int(x0 + st["a"] * w), y, int((st["b"] - st["a"]) * w), h)
            col = BY_NAME[st["spells"][0]]["col"]
            active = st["a"] <= e.progress <= st["b"] and not st["done"] and not self.acting
            if st["done"]:
                fill, bd = (40, 150, 80), GREEN
            elif e.progress > st["b"]:
                fill, bd = (60, 25, 30), (130, 50, 60)
            elif active:
                fill, bd = shade(col, 0.6), WHITE
            else:
                fill, bd = shade(col, 0.33), col
            pygame.draw.rect(s, fill, r, border_radius=6)
            pygame.draw.rect(s, bd, r, 3 if active else 2, border_radius=6)
            for i, nm in enumerate(st["spells"][:3]):
                if r.w >= (i + 1) * 30 + 6:
                    s.blit(self.assets.spell_icon(nm, 26), (r.x + 4 + i * 30, r.y + 3))
        pygame.draw.rect(s, (70, 70, 120), (x0 - 4, y - 4, w + 8, h + 8), 2, border_radius=8)
        cx = int(x0 + e.progress * w)
        pygame.draw.line(s, WHITE, (cx, y - 8), (cx, y + h + 8), 3)
        pygame.draw.polygon(s, WHITE, [(cx - 6, y - 12), (cx + 6, y - 12), (cx, y - 3)])
        self.text(f"Раунд {e.round} · прокаст {e.hits}/{len(e.script)}", 15, GOLD, (x0 - 8, y + 8), "topright", True)
        if self.acting:
            hint = "Враг атакует..."
        elif SHOW_HINTS:
            nxt = next((st for st in e.script if not st["done"] and e.progress <= st["b"]), None)
            hint = (f"▶ {nxt['label']}: " + " / ".join(nxt["spells"])) if nxt else "Прокаст выполнен — ждём удар"
        else:
            hint = ""
        self.text(hint, 16, (255, 230, 150), (W // 2, y + h + 10), "midtop", True)
        if e.pause > 0:
            self.text("⏸ зарядка остановлена", 14, CYAN, (x1 + 12, y + 8))
        elif e.slow > 0:
            self.text("замедлен", 14, CYAN, (x1 + 12, y + 8))

    def cd_sweep(self, rect, frac):
        surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        c, n = (rect.w // 2, rect.h // 2), 40
        pts = [c] + [(c[0] + math.cos(-math.pi / 2 + 2 * math.pi * frac * i / n) * rect.w,
                      c[1] + math.sin(-math.pi / 2 + 2 * math.pi * frac * i / n) * rect.w) for i in range(n + 1)]
        pygame.draw.polygon(surf, (0, 0, 0, 175), pts)
        self.screen.blit(surf, rect.topleft)

    def draw_cell(self, rect, hotkey, icon, cd, cd_max, col, cb):
        s = self.screen
        hover = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(s, (8, 8, 18), rect, border_radius=8)
        if icon:
            s.blit(icon, icon.get_rect(center=rect.center))
        if cd > 0:
            self.cd_sweep(rect, cd / cd_max)
            self.text(f"{cd:.1f}" if cd < 10 else str(int(cd)), 22, WHITE, rect.center, "center", True)
        pygame.draw.rect(s, col if cd <= 0 else (80, 80, 105), rect, 3 if hover else 2, border_radius=8)
        pygame.draw.rect(s, (0, 0, 0), (rect.x + 3, rect.bottom - 22, 22, 18), border_radius=4)
        self.text(hotkey, 15, WHITE, (rect.x + 7, rect.bottom - 21), "topleft", True)
        self.hit(rect, cb)

    def draw_panel(self):
        s, p = self.screen, self.player
        pygame.draw.rect(s, (14, 14, 26), (0, 596, W, 104))
        pygame.draw.line(s, (170, 130, 50), (0, 596), (W, 596), 2)
        cell, gap, gg = 76, 8, 26
        x0 = (W - (6 * cell + 3 * gap + 2 * gg)) // 2
        y = 608
        xs, x = [], x0
        for grp in (3, 2, 1):
            for _ in range(grp):
                xs.append(x)
                x += cell + gap
            x += gg - gap
        icon = cell - 6
        for i, k in enumerate("QWE"):
            self.draw_cell(pygame.Rect(xs[i], y, cell, cell), k, self.assets.orb_icon(k, icon), 0, 1, ORB_COL[k], lambda k=k: self.add_orb(k))
        for i, hk in enumerate("DF"):
            name = p.slots[i]
            cd = p.cd.get(name, 0.0) if name else 0.0
            col = BY_NAME[name]["col"] if name else (60, 60, 90)
            self.draw_cell(pygame.Rect(xs[3 + i], y, cell, cell), hk, self.assets.spell_icon(name, icon) if name else None,
                           cd, BY_NAME[name]["cd"] if name else 1, col, lambda i=i: self.cast_slot(i))
        self.draw_cell(pygame.Rect(xs[5], y, cell, cell), "R", self.assets.invoke_icon(icon), p.invoke_cd, INVOKE_CD, GOLD, self.invoke)
        # очередь сфер над QWE
        gx = xs[0] + (3 * cell + 2 * gap) // 2
        for i in range(3):
            pos = (gx - 34 + i * 34, 578)
            if i < len(p.orbs):
                glow(s, ORB_COL[p.orbs[i]], pos, 11)
            else:
                pygame.draw.circle(s, (60, 60, 90), pos, 11, 2)
        if SHOW_HINTS and len(p.orbs) == 3:
            sp = SPELLS.get(self.combo_key())
            self.text(f"→ {sp['name']}" if sp else "→ нет такого заклинания", 15, sp["col"] if sp else (130, 130, 150), (gx, 548), "midtop", True)
        self.text("D / F — каст  ·  R — Invoke", 14, (150, 150, 180), (22, 612))
        self.text("K — сменить скин  ·  H — справка", 14, (150, 150, 180), (22, 632))
        self.text(f"Иконок найдено: {self.assets.found}", 13, (100, 100, 130), (22, 676))
        self.text("Магазин — позже", 14, (100, 100, 130), (W - 22, 612), "topright")

    def draw_help(self):
        s = self.screen
        r = pygame.Rect(W // 2 - 400, 160, 800, 420)
        ov = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(ov, (8, 8, 20, 240), ov.get_rect(), border_radius=14)
        s.blit(ov, r)
        pygame.draw.rect(s, CYAN, r, 2, border_radius=14)
        self.text("ЗАКЛИНАНИЯ  (комбо · КД · эффект)", 22, CYAN, (r.centerx, r.y + 8), "midtop", True)
        for i, (k, sp) in enumerate(SPELLS.items()):
            yy = r.y + 44 + i * 33
            s.blit(self.assets.spell_icon(sp["name"], 28), (r.x + 14, yy))
            self.text(k, 16, WHITE, (r.x + 52, yy + 5), "topleft", True)
            self.text(sp["name"], 16, sp["col"], (r.x + 110, yy + 5), "topleft", True)
            self.text(f"{sp['cd']:.0f}с", 15, GOLD, (r.x + 270, yy + 5))
            self.text(sp["desc"], 14, (190, 190, 215), (r.x + 320, yy + 6))
        self.text("Каст в правильное окно = полный урон (иначе ×0.6). Все окна = идеальный прокаст.", 14, (255, 170, 80), (r.centerx, r.bottom - 34), "midtop")
        self.text("КОР умирает, ТАНК/САППОРТ пропускает ход. ▲ слабость  ▼ резист.", 14, (255, 170, 80), (r.centerx, r.bottom - 18), "midtop")

    def draw(self):
        self.buttons.clear()
        s, t = self.screen, self.t
        s.blit(self.bg, (0, 0))
        for sp in self.spirits:
            sp.draw(s)
        self.player.draw(s, t, self.assets)
        self.enemy.draw(s, t, self.assets)
        for f in self.fx:
            f.draw(s)
        for tx in self.texts:
            tx.draw(s, self.font)
        if self.banner:
            n, c, tt = self.banner
            img = self.font(42, True).render(n, True, c)
            img.set_alpha(int(255 * min(1, tt / 0.5)))
            s.blit(img, img.get_rect(center=(W // 2, 215)))
        if self.msg_t > 0:
            self.text(self.msg, 18, WHITE, (W // 2, 520), "midtop")
        self.draw_hud()
        self.draw_timeline()
        self.draw_panel()
        if self.show_help:
            self.draw_help()
        if self.state == "gameover":
            self.buttons.clear()
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 190))
            s.blit(ov, (0, 0))
            self.text("GAME OVER", 72, RED, (W // 2, 200), "midtop", True)
            self.text(f"Ты дошёл до волны {self.wave}", 30, WHITE, (W // 2, 300), "midtop")
            rect = pygame.Rect(W // 2 - 150, 380, 300, 60)
            pygame.draw.rect(s, (24, 24, 44), rect, border_radius=10)
            pygame.draw.rect(s, CYAN, rect, 2, border_radius=10)
            self.text("Перезапуск (Пробел)", 24, WHITE, rect.center, "center", True)
            self.hit(rect, self.reset)

    # ---------- ввод и главный цикл ----------
    def press(self, ch):
        if ch == "H":
            self.show_help = not self.show_help
            return
        if ch == "K":
            self.player.skin = (self.player.skin + 1) % len(SKINS_PLAYER)
            self.say(f"Скин: {SKINS_PLAYER[self.player.skin]['name']}", 2)
            return
        if self.state == "gameover":
            if ch in ("SPACE", "R"):
                self.reset()
            return
        if self.state == "victory" and ch == "SPACE":
            self.queue = [q for q in self.queue if q[1] != self.next_wave]
            self.next_wave()
            return
        if ch in ("Q", "W", "E"):
            self.add_orb(ch)
        elif ch == "R":
            self.invoke()
        elif ch == "D":
            self.cast_slot(0)
        elif ch == "F":
            self.cast_slot(1)

    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif ev.type == pygame.KEYDOWN:
                    ch = key_char(ev)
                    if ch == "ESC":
                        pygame.quit()
                        sys.exit()
                    self.press(ch)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    for rect, cb in reversed(self.buttons):
                        if rect.collidepoint(ev.pos):
                            cb()
                            break
            self.update(dt)
            self.draw()
            pygame.display.flip()


if __name__ == "__main__":
    Game().run()