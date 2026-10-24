# -*- coding: utf-8 -*-
"""
INVOKER: NEON DUEL — прототип пошаговой рогалик-головоломки на Pygame.
 
Архитектура:
    Spell-таблица (SPELLS)  — данные заклинаний
    Item / Shop             — предметы и магазин
    Player / Enemy          — персонажи (логика + отрисовка геометрией)
    Projectile / Flash / FloatText — анимации и эффекты
    Game                    — главный цикл, ввод, ход боя, интерфейс
 
Запуск:  pip install pygame   затем   python main.py
"""
import math
import random
import sys
from collections import deque
 
import pygame
 
# ======================================================================
# КОНСТАНТЫ И ДАННЫЕ
# ======================================================================
W, H = 1100, 700
FPS = 60
 
BG = (10, 10, 20)
PANEL = (16, 16, 32)
WHITE = (235, 235, 245)
GOLD = (255, 205, 70)
RED = (255, 70, 90)
GREEN = (90, 230, 130)
CYAN = (80, 220, 255)
PINK = (255, 120, 200)
 
# Неоновые цвета сфер: Quas — синий, Wex — фиолетовый, Exort — оранжевый
ORB_COL = {"Q": (60, 170, 255), "W": (200, 90, 255), "E": (255, 150, 40)}
ORB_NAME = {"Q": "Quas", "W": "Wex", "E": "Exort"}
 
PLAYER_POS = (190, 300)
ENEMY_POS = (910, 300)
 
# Показывать ли игроку уязвимости врага и подсказку по комбинации
SHOW_WEAKNESS = True
SHOW_PREVIEW = True
 
# Заклинания: ключ — комбинация сфер (порядок важен, кроме QWE)
SPELLS = {
    "QQQ": dict(name="Cold Snap", dmg=28, kind="atk", col=(90, 200, 255), desc="Урон"),
    "QQW": dict(name="Ghost Walk", dmg=0, kind="self", col=(170, 210, 235), desc="Уклонение от следующей атаки"),
    "QQE": dict(name="Ice Wall", dmg=15, kind="atk", col=(140, 230, 255), desc="Урон + замедление врага на 3 хода"),
    "WWW": dict(name="EMP", dmg=18, kind="atk", col=(210, 110, 255), desc="Урон + сжигание щита (маны)"),
    "WWQ": dict(name="Tornado", dmg=15, kind="atk", col=(170, 140, 255), desc="Подброс: враг пропускает ход"),
    "WWE": dict(name="Alacrity", dmg=0, kind="self", col=(255, 190, 70), desc="+50% урона на 2 заклинания"),
    "EEE": dict(name="Sun Strike", dmg=50, kind="atk", col=(255, 200, 60), desc="Большой урон"),
    "EEQ": dict(name="Forge Spirit", dmg=12, kind="atk", col=(255, 130, 50), desc="Призыв духа: бьёт 3 хода"),
    "EEW": dict(name="Chaos Meteor", dmg=35, kind="atk", col=(255, 90, 40), desc="Урон + поджог на 2 хода"),
    "QWE": dict(name="Deafening Blast", dmg=20, kind="atk", col=(220, 220, 255), desc="Оглушение (порядок не важен)"),
}
 
# Типы врагов: hp, dmg, слабости (названия заклинаний), щит, золото
ENEMY_TYPES = [
    dict(kind="pudge", name="Pudge", hp=130, dmg=12, shield=0, gold=25, col=(110, 170, 70),
         weak=["Cold Snap", "Ice Wall"]),
    dict(kind="medusa", name="Medusa", hp=90, dmg=11, shield=70, gold=30, col=(70, 200, 170),
         weak=["EMP", "Tornado"]),
    dict(kind="am", name="Anti-Mage", hp=100, dmg=14, shield=0, gold=28, col=(150, 110, 255),
         weak=["Forge Spirit", "Deafening Blast"]),
    dict(kind="zeus", name="Zeus", hp=85, dmg=16, shield=0, gold=30, col=(90, 150, 255),
         weak=["Sun Strike", "Chaos Meteor"]),
]
BOSS_TYPE = dict(kind="roshan", name="ROSHAN (БОСС)", hp=330, dmg=20, shield=0, gold=120,
                 col=(175, 115, 60), weak=["Sun Strike", "Chaos Meteor", "Deafening Blast"], boss=True)
 
ACTIVE_ORDER = ["salve", "blink", "bkb", "mek"]  # слоты активных предметов (клавиши 1-4)
ACTIVE_SHORT = {"salve": "Salve", "blink": "Blink", "bkb": "BKB", "mek": "Mekansm"}
 
 
# ======================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ======================================================================
def lighter(c, v=70):
    return tuple(min(255, x + v) for x in c)
 
 
def darker(c, k=3):
    return tuple(x // k for x in c)
 
 
def glow(surf, color, pos, r, layers=4):
    """Неоновое свечение: несколько полупрозрачных кругов + яркое ядро."""
    size = int(r * 5)
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size // 2
    for i in range(layers, 0, -1):
        pygame.draw.circle(s, (*color, 26 * (layers - i + 1)), (c, c), int(r * (1 + 0.35 * i)))
    pygame.draw.circle(s, (*color, 255), (c, c), int(r))
    pygame.draw.circle(s, (255, 255, 255, 190), (c, c), max(1, int(r // 3)))
    surf.blit(s, (int(pos[0]) - c, int(pos[1]) - c))
 
 
def wrap_text(font, text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
 
 
# ======================================================================
# ЭФФЕКТЫ: СНАРЯД, ВСПЫШКА, ВСПЛЫВАЮЩИЙ ТЕКСТ
# ======================================================================
class Projectile:
    """Снаряд, плавно летящий по дуге от start к end; по прилёту вызывает on_hit."""
 
    def __init__(self, start, end, color, on_hit, speed=750, radius=12, arc=50):
        self.start, self.end = pygame.Vector2(start), pygame.Vector2(end)
        self.color, self.on_hit, self.radius, self.arc = color, on_hit, radius, arc
        self.dur = max(0.3, self.start.distance_to(self.end) / speed)
        self.t = 0.0
        self.trail = []
        self.done = False
 
    def pos(self):
        p = min(1.0, self.t / self.dur)
        e = p * p * (3 - 2 * p)  # плавное ускорение/замедление
        v = self.start.lerp(self.end, e)
        v.y -= math.sin(math.pi * p) * self.arc
        return v
 
    def update(self, dt):
        self.t += dt
        self.trail.append(self.pos())
        self.trail = self.trail[-14:]
        if self.t >= self.dur and not self.done:
            self.done = True
            self.on_hit()
 
    def draw(self, surf):
        for i, p in enumerate(self.trail):
            glow(surf, self.color, p, max(2, int(self.radius * (i + 1) / len(self.trail) * 0.7)), 2)
        glow(surf, self.color, self.pos(), self.radius)
 
 
class Flash:
    """Вспышка при попадании: расширяющееся кольцо + искры."""
 
    def __init__(self, pos, color, big=False):
        self.pos, self.color = pos, color
        self.life = self.max = 0.5
        self.size = 90 if big else 55
        self.sparks = [(random.uniform(0, 6.28), random.uniform(80, 220)) for _ in range(14 if big else 8)]
 
    def update(self, dt):
        self.life -= dt
 
    def draw(self, surf):
        p = 1 - self.life / self.max
        r = int(self.size * (0.3 + p))
        s = pygame.Surface((r * 2 + 8, r * 2 + 8), pygame.SRCALPHA)
        a = int(255 * (1 - p))
        pygame.draw.circle(s, (*self.color, a // 3), (r + 4, r + 4), r)
        pygame.draw.circle(s, (*self.color, a), (r + 4, r + 4), r, 4)
        surf.blit(s, (self.pos[0] - r - 4, self.pos[1] - r - 4))
        for ang, sp in self.sparks:
            d = sp * p
            x, y = self.pos[0] + math.cos(ang) * d, self.pos[1] + math.sin(ang) * d
            pygame.draw.circle(surf, lighter(self.color, 60), (int(x), int(y)), max(1, int(4 * (1 - p))))
 
 
class FloatText:
    """Всплывающий текст (урон, лечение, статусы)."""
 
    def __init__(self, text, pos, color, size=28):
        self.text, self.x, self.y, self.color, self.size = text, pos[0], pos[1], color, size
        self.life = 1.3
 
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
 
 
# ======================================================================
# ПРЕДМЕТЫ И МАГАЗИН
# ======================================================================
class Item:
    def __init__(self, kind, name, desc, cost, category, color, stackable=False):
        self.kind, self.name, self.desc = kind, name, desc
        self.cost, self.category, self.color, self.stackable = cost, category, color, stackable
 
 
class Shop:
    """Магазин: бесплатные предметы, предметы за золото и за рекламу (заглушка)."""
 
    def __init__(self):
        self.items = [
            Item("hp", "Iron Branch", "+10 к максимальному HP (1 раз за посещение)", 0, "free", GREEN, True),
            Item("salve", "Healing Salve", "Расходник [1]: лечит 35 HP", 35, "gold", GOLD, True),
            Item("scepter", "Aghanim's Scepter", "Пассивно: +30% к урону заклинаний", 120, "gold", GOLD),
            Item("blink", "Blink Dagger", "Активно [2]: уклонение от следующей атаки (1 раз за бой)", 90, "gold", GOLD),
            Item("bkb", "Black King Bar", "Расходник [3]: иммунитет к атакам на 3 хода", 0, "ad", PINK, True),
            Item("mek", "Mekansm", "Расходник [4]: лечит 60 HP", 0, "ad", PINK, True),
        ]
        self.taken = set()
        self.msg = ""
 
    def open(self):
        self.taken.clear()
        self.msg = ""
 
    def grant(self, p, item):
        if item.kind == "hp":
            p.max_hp += 10
            p.hp += 10
        else:
            p.inv[item.kind] = p.inv.get(item.kind, 0) + 1
 
    def buy(self, g, item):
        p = g.player
        if not item.stackable and p.inv.get(item.kind, 0) > 0:
            self.msg = "Уже куплено"
            return
        if item.category == "free":
            if item.kind in self.taken:
                self.msg = "Уже взято в этом посещении"
                return
            self.taken.add(item.kind)
            self.grant(p, item)
            self.msg = f"Получено: {item.name}"
        elif item.category == "gold":
            if p.gold < item.cost:
                self.msg = "Не хватает золота"
                return
            p.gold -= item.cost
            self.grant(p, item)
            self.msg = f"Куплено: {item.name}"
        else:  # реклама — заглушка под Yandex SDK
            g.request_ad(lambda: (self.grant(p, item), setattr(self, "msg", f"Награда за рекламу: {item.name}")))
 
    def draw_card(self, g, it, rect, col):
        p = g.player
        s = g.screen
        hover = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(s, darker(col, 5) if hover else (22, 22, 40), rect, border_radius=12)
        pygame.draw.rect(s, col, rect, 2, border_radius=12)
        g.text(it.name, 20, WHITE, (rect.x + 12, rect.y + 8), "topleft", True)
        n = p.inv.get(it.kind, 0)
        if n and it.kind != "hp":
            g.text(f"x{n}", 18, col, (rect.right - 12, rect.y + 10), "topright", True)
        f = g.font(15)
        for i, line in enumerate(wrap_text(f, it.desc, rect.w - 24)[:3]):
            g.text(line, 15, (170, 170, 200), (rect.x + 12, rect.y + 38 + i * 18))
        if it.category == "free":
            label, lc = "Взять бесплатно", GREEN
        elif it.category == "gold":
            label, lc = f"Цена: {it.cost} ★", (GOLD if p.gold >= it.cost else RED)
        else:
            label, lc = "Получить за рекламу ▶", PINK
        g.text(label, 17, lc, (rect.x + 12, rect.bottom - 26), "topleft", True)
        g.hit(rect, lambda: self.buy(g, it))
 
    def draw(self, g):
        s = g.screen
        s.blit(g.bg, (0, 0))
        g.text("МАГАЗИН", 44, CYAN, (W // 2, 24), "midtop", True)
        g.text(f"★ Золото: {g.player.gold}", 26, GOLD, (W // 2, 84), "midtop", True)
        cols = [("free", "БЕСПЛАТНО", GREEN), ("gold", "ЗА ЗОЛОТО", GOLD), ("ad", "ЗА РЕКЛАМУ", PINK)]
        for ci, (cat, title, col) in enumerate(cols):
            x = 50 + ci * 350
            g.text(title, 24, col, (x + 160, 134), "midtop", True)
            y = 172
            for it in [i for i in self.items if i.category == cat]:
                self.draw_card(g, it, pygame.Rect(x, y, 320, 118), col)
                y += 128
        if self.msg:
            g.text(self.msg, 20, WHITE, (W // 2, 572), "midtop")
        g.button(pygame.Rect(W // 2 - 140, 618, 280, 54), "Продолжить (Enter)", CYAN, g.close_shop, size=22)
 
 
# ======================================================================
# ИГРОК
# ======================================================================
class Player:
    def __init__(self):
        self.max_hp = self.hp = 100
        self.gold = 0
        self.orbs = deque(maxlen=3)  # новая сфера вытесняет самую старую
        self.inv = {}
        self.evade = False       # уклонение от след. атаки (Ghost Walk / Blink)
        self.alacrity = 0        # сколько заклинаний осталось с баффом
        self.bkb = 0             # ходов иммунитета
        self.spirit = 0          # ходов жизни Forge Spirit
        self.blink_ready = True
        self.shake = 0.0
 
    def dmg_mult(self, with_alacrity=True):
        m = 1.3 if self.inv.get("scepter", 0) > 0 else 1.0
        if with_alacrity and self.alacrity > 0:
            m *= 1.5
        return m
 
    def draw(self, surf, pos, t):
        sh = math.sin(t * 90) * 8 * min(1, self.shake / 0.3) if self.shake > 0 else 0
        x, y = int(pos[0] + sh), int(pos[1] + math.sin(t * 2) * 5)
        # Мантия
        pygame.draw.polygon(surf, (50, 20, 90), [(x - 48, y + 72), (x + 48, y + 72), (x + 24, y - 12), (x - 24, y - 12)])
        pygame.draw.polygon(surf, (150, 80, 230), [(x - 48, y + 72), (x + 48, y + 72), (x + 24, y - 12), (x - 24, y - 12)], 3)
        pygame.draw.polygon(surf, (255, 190, 70), [(x - 8, y + 72), (x + 8, y + 72), (x + 5, y - 6), (x - 5, y - 6)])
        # Капюшон и глаза
        pygame.draw.circle(surf, (70, 30, 120), (x, y - 34), 27)
        pygame.draw.circle(surf, (170, 100, 240), (x, y - 34), 27, 3)
        pygame.draw.circle(surf, (10, 5, 20), (x, y - 32), 17)
        for dx in (-7, 7):
            glow(surf, (255, 180, 60), (x + dx, y - 33), 3, 2)
        # Посох
        pygame.draw.line(surf, (200, 170, 90), (x + 55, y + 70), (x + 62, y - 40), 4)
        glow(surf, (255, 220, 120), (x + 62, y - 44), 6, 2)
        # Вращающиеся сферы
        for i, o in enumerate(self.orbs):
            a = t * 2.5 + i * 2 * math.pi / 3
            glow(surf, ORB_COL[o], (x + math.cos(a) * 62, y - 20 + math.sin(a) * 24), 9)
        # Статусы
        if self.evade:
            pygame.draw.circle(surf, (170, 220, 240), (x, y + 10), 92, 2)
        if self.bkb > 0:
            pygame.draw.circle(surf, GOLD, (x, y + 10), 98, 4)
        if self.alacrity > 0:
            pygame.draw.circle(surf, (255, 170, 60), (x, y + 10), 86, 1)
        if self.spirit > 0:  # дух-спутник
            glow(surf, (255, 130, 50), (x + 95, y + 45 + math.sin(t * 4) * 6), 14)
 
 
# ======================================================================
# ВРАГ
# ======================================================================
class Enemy:
    def __init__(self, data, wave):
        k = wave - 1
        self.kind, self.name, self.col = data["kind"], data["name"], data["col"]
        self.weak = data["weak"]
        self.boss = data.get("boss", False)
        self.max_hp = self.hp = int(data["hp"] * (1 + 0.22 * k))
        self.dmg = int(data["dmg"] * (1 + 0.10 * k))
        self.shield = self.max_shield = int(data["shield"] * (1 + 0.22 * k))
        self.gold = int(data["gold"] * (1 + 0.10 * k))
        self.stun = self.slow = self.burn = 0
        self.stagger = False
        self.visible = True
        self.shake = 0.0
 
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
        self.shake = 0.3
        return d, absorbed
 
    def draw(self, surf, pos, t):
        if not self.visible:
            return
        sh = math.sin(t * 90) * 8 * min(1, self.shake / 0.3) if self.shake > 0 else 0
        x, y = int(pos[0] + sh), int(pos[1] + math.sin(t * 2 + 1) * 6)
        c, li, dk = self.col, lighter(self.col), darker(self.col)
        eye = (255, 60, 60)
        k = self.kind
        if k == "pudge":
            pygame.draw.circle(surf, dk, (x, y), 66)
            pygame.draw.circle(surf, c, (x, y), 62)
            pygame.draw.circle(surf, li, (x, y), 62, 3)
            pygame.draw.ellipse(surf, dk, (x - 34, y - 5, 68, 60))
            pygame.draw.circle(surf, c, (x, y - 64), 26)
            pygame.draw.circle(surf, li, (x, y - 64), 26, 3)
            for dx in (-9, 9):
                pygame.draw.circle(surf, eye, (x + dx, y - 68), 4)
            pygame.draw.line(surf, (190, 190, 205), (x - 60, y + 10), (x - 118, y - 40), 6)
            pygame.draw.arc(surf, (190, 190, 205), (x - 150, y - 80, 56, 56), 3.4, 6.0, 5)
            pygame.draw.polygon(surf, (205, 205, 220), [(x + 58, y - 8), (x + 108, y - 52), (x + 124, y - 36), (x + 74, y + 10)])
        elif k == "medusa":
            pygame.draw.polygon(surf, dk, [(x - 34, y + 5), (x + 34, y + 5), (x + 12, y + 88), (x - 12, y + 88)])
            pygame.draw.polygon(surf, li, [(x - 34, y + 5), (x + 34, y + 5), (x + 12, y + 88), (x - 12, y + 88)], 3)
            pygame.draw.ellipse(surf, c, (x - 42, y - 40, 84, 84))
            pygame.draw.circle(surf, c, (x, y - 62), 24)
            pygame.draw.circle(surf, li, (x, y - 62), 24, 3)
            for i in range(7):  # змеи-волосы
                a = math.pi + i * math.pi / 6
                ex = x + math.cos(a) * 44 + math.sin(t * 3 + i) * 6
                ey = y - 62 + math.sin(a) * 44
                pygame.draw.line(surf, li, (x + math.cos(a) * 20, y - 62 + math.sin(a) * 20), (ex, ey), 4)
            for dx in (-8, 8):
                pygame.draw.circle(surf, (255, 240, 80), (x + dx, y - 62), 4)
            pygame.draw.arc(surf, (210, 190, 120), (x - 100, y - 70, 70, 130), 1.6, 4.7, 4)
            if self.shield > 0:
                pygame.draw.circle(surf, CYAN, (x, y), 100, 3)
                glow(surf, CYAN, (x + 100 * math.cos(t * 2), y + 100 * math.sin(t * 2)), 5, 2)
        elif k == "am":
            pts = [(x, y - 90), (x + 40, y), (x, y + 85), (x - 40, y)]
            pygame.draw.polygon(surf, dk, pts)
            pygame.draw.polygon(surf, c, pts, 4)
            pygame.draw.polygon(surf, c, [(x, y - 50), (x + 18, y), (x, y + 40), (x - 18, y)])
            pygame.draw.circle(surf, dk, (x, y - 70), 18)
            for dx in (-6, 6):
                pygame.draw.circle(surf, (120, 255, 255), (x + dx, y - 72), 3)
            for s_ in (-1, 1):  # клинки
                pygame.draw.line(surf, (200, 160, 255), (x + s_ * 36, y + 10), (x + s_ * 96, y - 60), 5)
                glow(surf, (200, 150, 255), (x + s_ * 96, y - 60), 5, 2)
        elif k == "zeus":
            pygame.draw.polygon(surf, dk, [(x, y - 70), (x + 62, y + 80), (x - 62, y + 80)])
            pygame.draw.polygon(surf, c, [(x, y - 70), (x + 62, y + 80), (x - 62, y + 80)], 4)
            pygame.draw.circle(surf, (230, 215, 190), (x, y - 72), 24)
            pygame.draw.polygon(surf, (240, 240, 255), [(x - 20, y - 60), (x + 20, y - 60), (x, y - 20)])
            for dx in (-8, 8):
                pygame.draw.circle(surf, (80, 160, 255), (x + dx, y - 78), 3)
            bx, by = x + 80, y - 40
            pts = [(bx, by)]
            for i in range(1, 6):
                pts.append((bx + random.randint(-14, 14), by + i * 18))
            pygame.draw.lines(surf, (255, 240, 100), False, pts, 4)
            glow(surf, (255, 240, 100), pts[-1], 6, 2)
        else:  # roshan
            pygame.draw.circle(surf, dk, (x, y + 5), 98)
            pygame.draw.circle(surf, c, (x, y + 5), 92)
            pygame.draw.circle(surf, li, (x, y + 5), 92, 4)
            pygame.draw.ellipse(surf, lighter(c, 40), (x - 50, y - 5, 100, 80))
            pygame.draw.circle(surf, c, (x, y - 72), 42)
            pygame.draw.circle(surf, li, (x, y - 72), 42, 4)
            for s_ in (-1, 1):
                pygame.draw.polygon(surf, (235, 225, 200), [(x + s_ * 30, y - 100), (x + s_ * 62, y - 150), (x + s_ * 48, y - 94)])
                pygame.draw.circle(surf, eye, (x + s_ * 15, y - 78), 6)
                pygame.draw.polygon(surf, (235, 225, 200), [(x + s_ * 80, y + 30), (x + s_ * 115, y + 60), (x + s_ * 70, y + 55)])
            pygame.draw.rect(surf, GOLD, (x - 22, y - 38, 44, 10), border_radius=3)
 
 
# ======================================================================
# ИГРА
# ======================================================================
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Invoker: Neon Duel (прототип)")
        self.clock = pygame.time.Clock()
        self._fonts = {}
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
        for y in range(H):  # вертикальный градиент
            k = y / H
            pygame.draw.line(bg, (int(8 + 14 * k), int(8 + 8 * k), int(20 + 24 * k)), (0, y), (W, y))
        for i in range(0, 12):  # «пол» арены
            yy = 380 + i * i * 1.0 + i * 6
            pygame.draw.line(bg, (28, 28, 60), (0, yy), (W, yy))
        for x in range(-400, W + 400, 90):
            pygame.draw.line(bg, (24, 24, 52), (W // 2, 330), (x, 500))
        return bg
 
    def hit(self, rect, cb):
        self.buttons.append((rect, cb))
 
    def button(self, rect, label, color, cb, enabled=True, size=18):
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        fill = darker(color, 4) if hover else (24, 24, 44)
        pygame.draw.rect(self.screen, fill, rect, border_radius=10)
        pygame.draw.rect(self.screen, color if enabled else (70, 70, 90), rect, 2, border_radius=10)
        self.text(label, size, WHITE if enabled else (110, 110, 130), rect.center, "center", True)
        if enabled:
            self.hit(rect, cb)
 
    def schedule(self, delay, fn):
        self.queue.append([delay, fn])
 
    def say(self, s, t=2.5):
        self.msg, self.msg_t = s, t
 
    def float_at(self, pos, s, color, size=28):
        self.texts.append(FloatText(s, (pos[0] + random.randint(-25, 25), pos[1] - 70), color, size))
 
    def flash(self, pos, color, big=False):
        self.effects.append(Flash(pos, color, big))
 
    def request_ad(self, on_reward):
        # ЗАГЛУШКА: на Яндекс Играх здесь будет ysdk.adv.showRewardedVideo(...)
        on_reward()
 
    # ---------- состояние ----------
    def reset(self):
        self.player = Player()
        self.wave = 1
        self.state = "battle"   # battle / gameover
        self.shop_open = False
        self.need_next = False
        self.busy = False
        self.show_help = False
        self.projectiles, self.effects, self.texts, self.queue, self.buttons = [], [], [], [], []
        self.msg, self.msg_t = "Собери 3 сферы (Q/W/E) и нажми R (Invoke)", 6
        self.banner = None
        self.spawn_enemy()
 
    def spawn_enemy(self):
        data = BOSS_TYPE if self.wave % 5 == 0 else random.choice(ENEMY_TYPES)
        self.enemy = Enemy(data, self.wave)
        self.player.blink_ready = True
        self.player.spirit = 0
        self.busy = False
 
    def open_shop(self):
        self.shop.open()
        self.shop_open = True
 
    def close_shop(self):
        self.shop_open = False
        if self.need_next:
            self.need_next = False
            self.spawn_enemy()
 
    # ---------- ввод ----------
    def add_orb(self, k):
        if self.busy or self.state != "battle" or self.shop_open:
            return
        self.player.orbs.append(k)
 
    def invoke(self):
        if self.busy or self.state != "battle" or self.shop_open:
            return
        p = self.player
        seq = "".join(p.orbs)
        if len(seq) < 3:
            self.say("Нужно 3 сферы!")
            return
        key = "QWE" if sorted(seq) == ["E", "Q", "W"] else seq
        sp = SPELLS.get(key)
        if not sp:
            self.say(f"Неизвестная комбинация {seq} — сферы сброшены")
            p.orbs.clear()
            return
        p.orbs.clear()
        self.cast(sp)
 
    def use_item(self, idx):
        if self.busy or self.state != "battle" or self.shop_open:
            return
        kind = ACTIVE_ORDER[idx]
        p = self.player
        if p.inv.get(kind, 0) <= 0:
            self.say("Предмета нет — купи в магазине")
            return
        if kind in ("salve", "mek"):
            if p.hp >= p.max_hp:
                self.say("HP уже полное")
                return
            heal = 35 if kind == "salve" else 60
            p.hp = min(p.max_hp, p.hp + heal)
            p.inv[kind] -= 1
            self.float_at(PLAYER_POS, f"+{heal}", GREEN, 32)
        elif kind == "bkb":
            p.bkb = 3
            p.inv[kind] -= 1
            self.float_at(PLAYER_POS, "BKB!", GOLD, 32)
        elif kind == "blink":
            if not p.blink_ready:
                self.say("Blink Dagger уже использован в этом бою")
                return
            p.blink_ready = False
            p.evade = True
            self.float_at(PLAYER_POS, "Blink!", CYAN, 32)
 
    def handle_key(self, key):
        if key == pygame.K_h:
            self.show_help = not self.show_help
            return
        if self.state == "gameover":
            if key in (pygame.K_r, pygame.K_RETURN):
                self.reset()
            return
        if self.shop_open:
            if key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_s, pygame.K_ESCAPE):
                self.close_shop()
            return
        if self.busy:
            return
        if key == pygame.K_q:
            self.add_orb("Q")
        elif key == pygame.K_w:
            self.add_orb("W")
        elif key == pygame.K_e:
            self.add_orb("E")
        elif key == pygame.K_r:
            self.invoke()
        elif key == pygame.K_s:
            self.open_shop()
        elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
            self.use_item(key - pygame.K_1)
 
    # ---------- ход боя ----------
    def cast(self, sp):
        self.busy = True
        self.banner = (sp["name"], sp["col"], 1.4)
        if sp["kind"] == "self":
            self.flash(PLAYER_POS, sp["col"])
            self.schedule(0.45, lambda: self.resolve_spell(sp))
        else:
            self.projectiles.append(Projectile(
                (PLAYER_POS[0] + 60, PLAYER_POS[1] - 40), (ENEMY_POS[0] - 40, ENEMY_POS[1]),
                sp["col"], lambda: self.resolve_spell(sp)))
 
    def hit_enemy(self, dmg, color, big=False):
        e = self.enemy
        d, absorbed = e.take_damage(dmg)
        if absorbed:
            self.float_at(ENEMY_POS, f"-{absorbed}", CYAN, 26)
        if d:
            self.float_at(ENEMY_POS, f"-{d}", color, 40 if big else 30)
 
    def resolve_spell(self, sp):
        p, e = self.player, self.enemy
        name = sp["name"]
        weak = name in e.weak and sp["kind"] == "atk"
        dmg = 0
        if sp["dmg"] > 0:
            dmg = max(1, int(sp["dmg"] * p.dmg_mult() * (1.5 if weak else 0.3)))
            if p.alacrity > 0:
                p.alacrity -= 1
        if sp["kind"] == "atk":
            self.flash(ENEMY_POS, sp["col"], weak)
            if name == "EMP" and e.shield > 0:
                e.shield = 0
                self.float_at(ENEMY_POS, "Щит сожжён!", CYAN, 26)
            if name == "Ice Wall":
                e.slow = 3
            elif name == "Tornado":
                e.stun = max(e.stun, 1)
                self.float_at(ENEMY_POS, "Подброс!", sp["col"], 26)
            elif name == "Deafening Blast":
                e.stun = max(e.stun, 1 if e.boss else 2)
                self.float_at(ENEMY_POS, "Оглушён!", sp["col"], 26)
            elif name == "Forge Spirit":
                p.spirit = 3
            elif name == "Chaos Meteor":
                e.burn = 2
            if dmg:
                self.hit_enemy(dmg, sp["col"], weak)
            if weak:
                e.stagger = True
                self.say("УЯЗВИМОСТЬ! Враг сбит с ритма и не атакует", 2.5)
            else:
                self.say("Враг устойчив — урон снижен, он контратакует", 2.5)
        else:
            if name == "Ghost Walk":
                p.evade = True
                self.float_at(PLAYER_POS, "Призрачный шаг", sp["col"], 24)
            elif name == "Alacrity":
                p.alacrity = 2
                self.float_at(PLAYER_POS, "+50% урона", sp["col"], 24)
        if not e.alive:
            self.schedule(0.5, self.victory)
        else:
            self.schedule(0.7, self.enemy_phase)
 
    def enemy_phase(self):
        p, e = self.player, self.enemy
        # Тики эффектов: дух и поджог
        if p.spirit > 0:
            p.spirit -= 1
            self.flash(ENEMY_POS, (255, 130, 50))
            self.hit_enemy(int(10 * p.dmg_mult(False)), (255, 150, 60))
        if e.burn > 0:
            e.burn -= 1
            self.flash(ENEMY_POS, (255, 90, 40))
            self.hit_enemy(8, (255, 100, 40))
        if not e.alive:
            self.schedule(0.5, self.victory)
            return
        if e.stagger:
            e.stagger = False
            self.schedule(0.5, self.end_turn)
        elif e.stun > 0:
            e.stun -= 1
            self.float_at(ENEMY_POS, "Пропуск хода", WHITE, 24)
            self.schedule(0.5, self.end_turn)
        else:
            dmg = int(e.dmg * (0.5 if e.slow > 0 else 1.0))
            if e.slow > 0:
                e.slow -= 1
            self.projectiles.append(Projectile(
                (ENEMY_POS[0] - 50, ENEMY_POS[1]), (PLAYER_POS[0] + 30, PLAYER_POS[1] - 10),
                RED, lambda: self.hit_player(dmg), speed=650, radius=14))
            return
        # (при пропуске хода tick уже запланирован)
 
    def hit_player(self, dmg):
        p = self.player
        self.flash((PLAYER_POS[0], PLAYER_POS[1] - 10), RED)
        if p.bkb > 0:
            self.float_at(PLAYER_POS, "Иммунитет!", GOLD, 28)
        elif p.evade:
            p.evade = False
            self.float_at(PLAYER_POS, "Уклонение!", CYAN, 30)
        else:
            p.hp -= dmg
            p.shake = 0.3
            self.float_at(PLAYER_POS, f"-{dmg}", RED, 36)
        if p.hp <= 0:
            p.hp = 0
            self.state = "gameover"
            return
        self.schedule(0.45, self.end_turn)
 
    def end_turn(self):
        if self.player.bkb > 0:
            self.player.bkb -= 1
        self.busy = False
 
    def victory(self):
        e = self.enemy
        e.visible = False
        self.flash(ENEMY_POS, GOLD, True)
        self.player.gold += e.gold
        self.float_at(ENEMY_POS, f"+{e.gold} ★", GOLD, 38)
        self.wave += 1
        self.need_next = True
        self.say(f"Враг повержен! Волна {self.wave}", 3)
        self.schedule(1.1, self.open_shop)
 
    # ---------- обновление ----------
    def update(self, dt):
        self.t += dt
        for item in self.queue[:]:
            item[0] -= dt
            if item[0] <= 0:
                self.queue.remove(item)
                item[1]()
        for pr in self.projectiles[:]:
            pr.update(dt)
        self.projectiles = [pr for pr in self.projectiles if not pr.done]
        for ef in self.effects:
            ef.update(dt)
        self.effects = [ef for ef in self.effects if ef.life > 0]
        for tx in self.texts:
            tx.update(dt)
        self.texts = [tx for tx in self.texts if tx.life > 0]
        self.enemy.shake = max(0, self.enemy.shake - dt)
        self.player.shake = max(0, self.player.shake - dt)
        self.msg_t = max(0, self.msg_t - dt)
        if self.banner:
            n, c, tt = self.banner
            self.banner = (n, c, tt - dt) if tt - dt > 0 else None
 
    # ---------- отрисовка ----------
    def draw_bar(self, rect, ratio, color, label):
        pygame.draw.rect(self.screen, (30, 10, 20), rect, border_radius=8)
        fw = int(rect.w * max(0, min(1, ratio)))
        if fw > 0:
            fill = pygame.Rect(rect.x, rect.y, fw, rect.h)
            pygame.draw.rect(self.screen, color, fill, border_radius=8)
            pygame.draw.rect(self.screen, lighter(color, 80), (rect.x + 4, rect.y + 3, max(0, fw - 8), rect.h // 3), border_radius=4)
        pygame.draw.rect(self.screen, lighter(color, 40), rect, 2, border_radius=8)
        self.text(label, 16, WHITE, rect.center, "center", True)
 
    def draw_hud(self):
        p, e = self.player, self.enemy
        r = p.hp / p.max_hp
        pc = (int(255 * (1 - r) + 60 * r), int(70 * (1 - r) + 220 * r), 90)
        self.text("ИНВОКЕР", 18, (190, 130, 255), (20, 52), "topleft", True)
        self.draw_bar(pygame.Rect(20, 16, 340, 28), r, pc, f"HP {p.hp}/{p.max_hp}")
        self.text(f"Волна {self.wave}", 22, WHITE, (W // 2, 12), "midtop", True)
        self.text(f"★ {p.gold}", 26, GOLD, (W // 2, 40), "midtop", True)
        self.draw_bar(pygame.Rect(W - 360, 16, 340, 28), e.hp / e.max_hp, (230, 60, 80), f"HP {e.hp}/{e.max_hp}")
        if e.max_shield > 0:
            pygame.draw.rect(self.screen, (10, 30, 40), (W - 360, 48, 340, 8), border_radius=4)
            pygame.draw.rect(self.screen, CYAN, (W - 360, 48, int(340 * e.shield / e.max_shield), 8), border_radius=4)
        self.text(e.name, 24, GOLD if e.boss else WHITE, (W - 20, 60), "topright", True)
        if SHOW_WEAKNESS:
            self.text("Уязвим: " + ", ".join(e.weak), 16, (255, 170, 80), (W - 20, 92), "topright")
        st = []
        if e.stun > 0:
            st.append("оглушён")
        if e.slow > 0:
            st.append(f"замедлен({e.slow})")
        if e.burn > 0:
            st.append("горит")
        if st:
            self.text(", ".join(st), 16, CYAN, (W - 20, 112), "topright")
        ps = []
        if p.evade:
            ps.append("уклонение")
        if p.bkb > 0:
            ps.append(f"BKB({p.bkb})")
        if p.alacrity > 0:
            ps.append(f"Alacrity({p.alacrity})")
        if p.spirit > 0:
            ps.append(f"дух({p.spirit})")
        if ps:
            self.text(", ".join(ps), 16, (255, 220, 120), (20, 76), "topleft")
 
    def draw_panel(self):
        s, p = self.screen, self.player
        pygame.draw.rect(s, PANEL, (0, 500, W, 200))
        pygame.draw.line(s, (90, 60, 200), (0, 500), (W, 500), 2)
        # Слоты текущего комбо
        self.text("Сферы:", 16, (150, 150, 180), (20, 520))
        orbs = list(p.orbs)
        for i in range(3):
            pos = (100 + i * 40, 530)
            if i < len(orbs):
                glow(s, ORB_COL[orbs[i]], pos, 13)
            else:
                pygame.draw.circle(s, (60, 60, 90), pos, 13, 2)
        if SHOW_PREVIEW and len(orbs) == 3:
            seq = "".join(orbs)
            key = "QWE" if sorted(seq) == ["E", "Q", "W"] else seq
            sp = SPELLS.get(key)
            if sp:
                self.text(f"→ {sp['name']}: {sp['desc']}", 16, sp["col"], (180, 520), "topleft", True)
            else:
                self.text("→ нет такого заклинания", 16, (130, 130, 150), (180, 520))
        # Кнопки сфер Q W E
        for i, k in enumerate("QWE"):
            c = (80 + i * 100, 612)
            col = ORB_COL[k]
            hov = pygame.Rect(c[0] - 38, c[1] - 38, 76, 76).collidepoint(pygame.mouse.get_pos())
            glow(s, col, c, 38 if hov else 34)
            self.text(k, 34, (10, 10, 20), c, "center", True)
            self.text(ORB_NAME[k], 14, col, (c[0], c[1] + 44), "midtop")
            self.hit(pygame.Rect(c[0] - 38, c[1] - 38, 76, 76), lambda k=k: self.add_orb(k))
        # Кнопка Invoke
        c = (410, 612)
        glow(s, GOLD, c, 36)
        self.text("R", 34, (20, 10, 0), c, "center", True)
        self.text("Invoke", 14, GOLD, (c[0], c[1] + 44), "midtop")
        self.hit(pygame.Rect(c[0] - 38, c[1] - 38, 76, 76), self.invoke)
        # Предметы
        for i, kind in enumerate(ACTIVE_ORDER):
            rect = pygame.Rect(520 + i * 105, 552, 98, 96)
            n = p.inv.get(kind, 0)
            ok = n > 0 and (kind != "blink" or p.blink_ready)
            self.button(rect, ACTIVE_SHORT[kind], GOLD if ok else (70, 70, 90), lambda i=i: self.use_item(i), True, 16)
            self.text(f"[{i + 1}]", 14, (150, 150, 180), (rect.x + 6, rect.y + 4))
            self.text(f"x{n}", 22, WHITE if n else (80, 80, 100), (rect.centerx, rect.bottom - 30), "midtop", True)
        self.button(pygame.Rect(950, 552, 130, 44), "Магазин (S)", GOLD, self.open_shop, not self.busy)
        self.button(pygame.Rect(950, 604, 130, 44), "Справка (H)", CYAN, lambda: setattr(self, "show_help", not self.show_help))
        self.text("Q W E — сферы · R — Invoke · 1-4 — предметы", 14, (110, 110, 140), (W // 2, 676), "midtop")
 
    def draw_help(self):
        s = self.screen
        r = pygame.Rect(W // 2 - 330, 100, 660, 390)
        ov = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(ov, (8, 8, 20, 235), ov.get_rect(), border_radius=14)
        s.blit(ov, r)
        pygame.draw.rect(s, CYAN, r, 2, border_radius=14)
        self.text("ЗАКЛИНАНИЯ", 26, CYAN, (r.centerx, r.y + 12), "midtop", True)
        for i, (k, sp) in enumerate(SPELLS.items()):
            y = r.y + 54 + i * 29
            x = r.x + 20
            for j, ch in enumerate(k):
                glow(s, ORB_COL[ch], (x + 10 + j * 26, y + 11), 8, 2)
            self.text(sp["name"], 18, sp["col"], (r.x + 120, y), "topleft", True)
            self.text(sp["desc"], 16, (190, 190, 215), (r.x + 320, y + 2), "topleft")
        self.text("Попал в уязвимость — полный урон, враг не атакует. Иначе — урон ×0.3 и контратака.",
                  14, (255, 170, 80), (r.centerx, r.bottom - 26), "midtop")
 
    def draw(self):
        self.buttons.clear()
        if self.shop_open:
            self.shop.draw(self)
            return
        s = self.screen
        s.blit(self.bg, (0, 0))
        for pos in (PLAYER_POS, ENEMY_POS):  # тени
            sh = pygame.Surface((150, 30), pygame.SRCALPHA)
            pygame.draw.ellipse(sh, (0, 0, 0, 110), sh.get_rect())
            s.blit(sh, (pos[0] - 75, pos[1] + 82))
        self.player.draw(s, PLAYER_POS, self.t)
        self.enemy.draw(s, ENEMY_POS, self.t)
        for pr in self.projectiles:
            pr.draw(s)
        for ef in self.effects:
            ef.draw(s)
        for tx in self.texts:
            tx.draw(s, self.font)
        if self.banner:
            n, c, tt = self.banner
            img = self.font(40, True).render(n, True, c)
            img.set_alpha(int(255 * min(1, tt / 0.5)))
            s.blit(img, img.get_rect(center=(W // 2, 150)))
        if self.msg_t > 0:
            self.text(self.msg, 20, WHITE, (W // 2, 455), "midtop")
        self.draw_hud()
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
            self.text(f"Золота накоплено: {self.player.gold}", 24, GOLD, (W // 2, 345), "midtop")
            self.button(pygame.Rect(W // 2 - 150, 420, 300, 60), "Перезапуск (R)", CYAN, self.reset, size=24)
 
    # ---------- главный цикл ----------
    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE and not self.shop_open:
                        pygame.quit()
                        sys.exit()
                    self.handle_key(ev.key)
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