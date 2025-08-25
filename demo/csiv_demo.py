print("=== CSIV DEMO V7.2 NO TREES, CLEAN/ROGUE NEIGHBOR ISOLATION STARTED ===")

"""
CSIV Interactive Demo Sandbox Game v7.2
- Clean vs Rogue neighbor isolation: clean towers only see clean neighbors; rogue towers have empty neighbor lists.
- Trees removed.
- Coherent infinite city-block background with subtle checker pattern + grid.
- Throttled chunk/tower generation.
- Vicinity-gated CSIV evaluation.
- Toggleable expensive SIB broadcasting (T).
- State transitions with fade, probation, recovery.
- ESC requires double-press to exit (single press toggles menu), early stray ESCs ignored.
Requirements: Python 3.8+, pygame
Run: python3 csiv_demo_v7_2.py
"""

import pygame
import math
import time
import random
import statistics
import sys
from collections import deque

# ---------------- Configuration ----------------
DEBUG_MODE = False  # verbose output

# CSIV weights / thresholds
W_DVER = 1.5
W_PVER = 1.0
W_SPVER = 1.0
THETA_SUSPECT = 0.5
THETA_BARRED = 1.0
T_HALF = 5.0
BARRED_BASE = 5.0
BARRED_MAX = 30.0
PROBATION_DURATION = 3.0
M_CLEAN = 2
COMBO_PRIORITY_LOCATION_BOOST = 0.5

# Recovery/cooldown/range
OUT_OF_RANGE_CLEAR_DISTANCE = 300.0
OUT_OF_RANGE_CLEAR_TIME = 3.0
MIN_BARRED_RECOVERY_TIME = 8.0
COOLDOWN_AFTER_CLEAN = 2.0

# Vicinity gating
CSIV_VICINITY_RADIUS = 250.0

# Fade transition
STATE_TRANSITION_FADE = 1.5

# Procedural generation
CHUNK_SIZE = 200
TOWERS_PER_CHUNK_MIN = 1
TOWERS_PER_CHUNK_MAX = 2
NEIGHBOR_RADIUS = 150
MAX_NEIGHBORS = 3
ROGUE_PROBABILITY = 0.02
MIN_TOWER_SPACING = 50
BUILDINGS_PER_CHUNK = 3

# Chunk generation pacing
PREFETCH_RADIUS = 1
MAX_CHUNKS_PER_FRAME = 1
MAX_TOTAL_TOWERS = 150

# SIB tuning
SIB_INTERVAL_MIN = 5.0
SIB_INTERVAL_MAX = 12.0
MAX_ACTIVE_SIB_MSGS = 40
SIB_DRAW_DISTANCE = 300.0

# Tower update throttling
TOWER_UPDATE_INTERVAL = 0.25

# SIB generation toggle (user-controlled)
generate_sib_traffic = False  # only generate when True

# Colors
COLOR_ROAD = (60, 60, 60)
COLOR_BUILDING = (80, 80, 100)
COLOR_BUILDING_OUTLINE = (120, 120, 160)
COLOR_CAR = (200, 200, 255)
COLORS_STATE = {
    "CLEAN": (100, 180, 255),
    "SUSPECT": (255, 215, 100),
    "BARRED": (255, 100, 100),
    "PROBATION": (100, 255, 150),
}

FONT_NAME = "consolas"

def now():
    return time.time()

# ---------------- Entities ----------------

class Tower:
    def __init__(self, tid, pos, priority=3, neighbors=None, identity=None, is_rogue=False):
        self.id = tid
        self.pos = pos
        self.priority = priority
        self.neighbors = neighbors if neighbors is not None else []
        self.identity = identity if identity is not None else f"ID_{tid}"
        self.TAC = f"0x{random.randint(0, 0xFFFF):04X}"
        self.S = 0.0
        self.last_update = now()
        self.state = "CLEAN"
        self.prev_state = "CLEAN"
        self.last_state_change_time = now()
        self.recent_bar_count = 0
        self.barred_expiry = 0
        self.barred_start_time = 0
        self.probation_expiry = 0
        self.clean_streak = 0
        self.out_of_range_since = None
        self.cooldown_until = 0.0
        self.mu = None
        self.v = None
        self.next_sib_time = now() + random.uniform(1.0, 3.0)
        self.next_state_update = now()
        self.is_rogue = is_rogue
        if self.is_rogue and not self.identity.endswith("_ROGUE"):
            self.identity += "_ROGUE"

    def distance_to(self, point):
        return math.hypot(self.pos[0] - point[0], self.pos[1] - point[1])

    def measure_signal(self, ue_pos):
        d = max(0.1, self.distance_to(ue_pos))
        base = 1.0 / d
        noise = random.gauss(0, 0.05 * base)
        return max(0.0, base + noise)

    def compute_pVer_deviation(self, towers):
        neighbor_prios = []
        for nid in self.neighbors:
            t = towers.get(nid)
            if t:
                neighbor_prios.append(t.priority)
        median_prio = statistics.median(neighbor_prios) if neighbor_prios else 3
        crp = self.priority
        if crp > median_prio and (7 - median_prio) > 0:
            d_p = (crp - median_prio) / (7 - median_prio)
        else:
            d_p = 0.0
        high_priority_flag = (crp - median_prio) >= 1
        return d_p, high_priority_flag

    def compute_dVer_duplicate_identity(self, towers):
        dup = any((t.identity == self.identity) for t in towers.values() if t is not self)
        return (1.0 if dup else 0.0), dup

    def compute_spVer_deviation(self, ue_pos):
        x_t = self.measure_signal(ue_pos)
        beta = 0.2
        if self.mu is None:
            self.mu = x_t
            self.v = 0.0
        else:
            self.mu = (1 - beta) * self.mu + beta * x_t
            self.v = (1 - beta) * self.v + beta * ((x_t - self.mu) ** 2)
        sigma = math.sqrt(max(self.v, 1e-6))
        z = abs(x_t - self.mu) / sigma if sigma > 0 else 0.0
        cv = sigma / max(self.mu, 1e-6)
        z_base = 2.0
        alpha_cv = 0.5
        z_threshold = z_base * (1 + alpha_cv * cv)
        if z > z_threshold:
            dev = min(1.0, (z - z_threshold) / z_threshold)
        else:
            dev = 0.0
        return dev

    def set_state(self, new_state, current):
        if new_state != self.state:
            self.prev_state = self.state
            self.last_state_change_time = current
            self.state = new_state
            if new_state == "BARRED":
                self.barred_start_time = current

    def update_state(self, ue_pos, towers):
        global W_DVER, W_PVER, W_SPVER, THETA_SUSPECT, THETA_BARRED
        current = now()
        dist = self.distance_to(ue_pos)

        if dist > CSIV_VICINITY_RADIUS:
            if self.state != "CLEAN":
                self.set_state("CLEAN", current)
                self.S = 0.0
                self.last_update = current
                self.cooldown_until = current + COOLDOWN_AFTER_CLEAN
                self.out_of_range_since = None
            return

        dt = current - self.last_update
        lam = math.log(2) / T_HALF
        self.S *= math.exp(-lam * dt)
        self.last_update = current

        d_pVer, high_priority_flag = self.compute_pVer_deviation(towers)
        d_dVer, dup_flag = self.compute_dVer_duplicate_identity(towers)
        d_spVer = self.compute_spVer_deviation(ue_pos)

        delta_S = W_DVER * d_dVer + W_PVER * d_pVer + W_SPVER * d_spVer
        if high_priority_flag and dup_flag:
            delta_S *= (1 + COMBO_PRIORITY_LOCATION_BOOST)

        if dup_flag and (not self.neighbors):
            self.set_state("BARRED", current)
            self.recent_bar_count += 1
            dur = min(BARRED_BASE * (2 ** (self.recent_bar_count - 1)), BARRED_MAX)
            self.barred_expiry = current + dur
            self.S = delta_S
            self.out_of_range_since = None
            self.cooldown_until = current + COOLDOWN_AFTER_CLEAN
            return

        self.S += delta_S

        if self.state == "CLEAN":
            effective_threshold = THETA_SUSPECT
            if current < self.cooldown_until:
                effective_threshold = THETA_SUSPECT * 1.5
            if self.S >= effective_threshold:
                self.set_state("SUSPECT", current)
        elif self.state == "SUSPECT":
            if self.S >= THETA_BARRED:
                self.set_state("BARRED", current)
                self.recent_bar_count += 1
                dur = min(BARRED_BASE * (2 ** (self.recent_bar_count - 1)), BARRED_MAX)
                self.barred_expiry = current + dur
                self.out_of_range_since = None
        elif self.state == "BARRED":
            if dist > OUT_OF_RANGE_CLEAR_DISTANCE:
                if self.out_of_range_since is None:
                    self.out_of_range_since = current
                elif current - self.out_of_range_since >= OUT_OF_RANGE_CLEAR_TIME:
                    self.set_state("CLEAN", current)
                    self.S = 0.0
                    self.last_update = current
                    self.cooldown_until = current + COOLDOWN_AFTER_CLEAN
                    self.out_of_range_since = None
                    return
            else:
                self.out_of_range_since = None
            if current >= self.barred_expiry:
                self.set_state("PROBATION", current)
                self.probation_expiry = current + PROBATION_DURATION
                self.clean_streak = 0
        elif self.state == "PROBATION":
            if d_dVer < 0.1 and d_pVer < 0.1 and d_spVer < 0.1:
                self.clean_streak += 1
                if self.clean_streak >= M_CLEAN:
                    self.set_state("CLEAN", current)
                    self.S = 0.0
                    self.last_update = current
                    self.cooldown_until = current + COOLDOWN_AFTER_CLEAN
            else:
                self.set_state("BARRED", current)
                self.recent_bar_count += 1
                dur = min(BARRED_BASE * (2 ** (self.recent_bar_count - 1)), BARRED_MAX)
                self.barred_expiry = current + dur
                self.out_of_range_since = None

        if self.state == "BARRED":
            if (current - self.barred_start_time) >= MIN_BARRED_RECOVERY_TIME and self.S < (THETA_SUSPECT * 0.5):
                self.set_state("CLEAN", current)
                self.S = 0.0
                self.last_update = current
                self.cooldown_until = current + COOLDOWN_AFTER_CLEAN
                self.out_of_range_since = None

    def get_status(self):
        return self.state, self.S

    def get_display_color(self, current_time):
        if self.prev_state == "SUSPECT" and self.state == "BARRED":
            elapsed = current_time - self.last_state_change_time
            fade = min(1.0, elapsed / STATE_TRANSITION_FADE)
            c1 = COLORS_STATE["SUSPECT"]
            c2 = COLORS_STATE["BARRED"]
            blended = tuple(int(c1[i] * (1 - fade) + c2[i] * fade) for i in range(3))
            return blended
        return COLORS_STATE.get(self.state, (255, 255, 255))

    def generate_sib_info(self):
        if self.state == "BARRED":
            access_barring = {"barringFactor": "high", "accessCategory": "default"}
        else:
            access_barring = {"barringFactor": random.choice(["low", "medium"]), "accessCategory": "default"}

        random_access = {
            "preambleInitialReceivedTargetPower": -100 + random.randint(0, 5),
            "powerRampingStep": 2,
        }
        si_periodicity = random.choice(["rf8", "rf16", "rf32"])
        si_window_length = random.choice(["ms1", "ms2"])

        sib = {
            "plmn_list": ["00101"],
            "TAC": self.TAC,
            "cellBarred": self.state in ("BARRED",),
            "cellReselectionPriority": self.priority,
            "intraFreqReselectionAllowed": True,
            "si_periodicity": si_periodicity,
            "si_window_length": si_window_length,
            "randomAccessConfig": random_access,
            "accessBarring": access_barring,
            "neighbors": self.neighbors.copy(),
            "identity": self.identity,
        }
        return sib

class UE:
    def __init__(self, pos):
        self.pos = list(pos)

# ---------------- Utilities & Rendering ----------------

def chunk_coords(pos):
    return (int(math.floor(pos[0] / CHUNK_SIZE)), int(math.floor(pos[1] / CHUNK_SIZE)))

def generate_non_overlapping_position(existing_positions, base_x, base_y, size, min_spacing, max_tries=100):
    for _ in range(max_tries):
        x = random.uniform(base_x + 20, base_x + size - 20)
        y = random.uniform(base_y + 20, base_y + size - 20)
        if all(math.hypot(x - ex, y - ey) >= min_spacing for (ex, ey) in existing_positions):
            return x, y
    return random.uniform(base_x + 20, base_x + size - 20), random.uniform(base_y + 20, base_y - 20)

def generate_towers_buildings(chunk_x, chunk_y, towers, buildings, next_id):
    existing_positions = [t.pos for t in towers.values()]
    base_x = chunk_x * CHUNK_SIZE
    base_y = chunk_y * CHUNK_SIZE
    rogue_created = False
    count = random.randint(TOWERS_PER_CHUNK_MIN, TOWERS_PER_CHUNK_MAX)
    for _ in range(count):
        is_rogue = random.random() < ROGUE_PROBABILITY and len(towers) > 0 and not rogue_created
        if is_rogue:
            existing = random.choice(list(towers.values()))
            identity = existing.identity.replace("_ROGUE", "")
            priority = 7
            rogue_created = True
            pos = generate_non_overlapping_position(existing_positions, base_x, base_y, CHUNK_SIZE, MIN_TOWER_SPACING)
            t = Tower(next_id, pos, priority=priority, neighbors=[], identity=identity, is_rogue=True)
        else:
            identity = None
            priority = random.randint(2, 5)
            pos = generate_non_overlapping_position(existing_positions, base_x, base_y, CHUNK_SIZE, MIN_TOWER_SPACING)
            t = Tower(next_id, pos, priority=priority, neighbors=[], identity=identity, is_rogue=False)
        existing_positions.append(t.pos)
        towers[next_id] = t
        next_id += 1

    all_towers = list(towers.values())
    for t in all_towers:
        if t.is_rogue:
            t.neighbors = []
        else:
            candidates = [other for other in all_towers if other is not t and not other.is_rogue]
            dists = sorted([(t.distance_to(other.pos), other.id) for other in candidates])
            t.neighbors = [tid for dist, tid in dists if dist <= NEIGHBOR_RADIUS][:MAX_NEIGHBORS]

    bld_list = []
    for _ in range(BUILDINGS_PER_CHUNK):
        w = random.randint(40, 80)
        h = random.randint(40, 80)
        x = random.uniform(base_x + 10, base_x + CHUNK_SIZE - w - 10)
        y = random.uniform(base_y + 10, base_y + CHUNK_SIZE - h - 10)
        rect = pygame.Rect(int(x), int(y), int(w), int(h))
        bld_list.append(rect)
    buildings[(chunk_x, chunk_y)] = bld_list

    return next_id

def draw_city_block_background(surface, camera_offset, screen_size):
    width, height = screen_size
    start_chunk_x = int(math.floor(camera_offset[0] / CHUNK_SIZE)) - 1
    end_chunk_x = int(math.ceil((camera_offset[0] + width) / CHUNK_SIZE)) + 1
    start_chunk_y = int(math.floor(camera_offset[1] / CHUNK_SIZE)) - 1
    end_chunk_y = int(math.ceil((camera_offset[1] + height) / CHUNK_SIZE)) + 1
    for cx in range(start_chunk_x, end_chunk_x):
        for cy in range(start_chunk_y, end_chunk_y):
            block_x = cx * CHUNK_SIZE - camera_offset[0]
            block_y = cy * CHUNK_SIZE - camera_offset[1]
            rect = pygame.Rect(block_x, block_y, CHUNK_SIZE, CHUNK_SIZE)
            base = 40
            delta = 8
            shade = base + delta if ((cx + cy) % 2 == 0) else base
            pygame.draw.rect(surface, (shade, shade, shade), rect)
    grid_color = (55, 55, 70)
    for vx in range(start_chunk_x * CHUNK_SIZE, (end_chunk_x + 1) * CHUNK_SIZE, CHUNK_SIZE):
        x = vx - camera_offset[0]
        pygame.draw.line(surface, grid_color, (x, 0), (x, height), 1)
    for hy in range(start_chunk_y * CHUNK_SIZE, (end_chunk_y + 1) * CHUNK_SIZE, CHUNK_SIZE):
        y = hy - camera_offset[1]
        pygame.draw.line(surface, grid_color, (0, y), (width, y), 1)

def draw_roads(surface, camera_offset, screen_size):
    width, height = screen_size
    road_thickness = 40
    world_left = camera_offset[0]
    world_top = camera_offset[1]
    start_x = int(math.floor(world_left / CHUNK_SIZE)) * CHUNK_SIZE
    end_x = int(math.ceil((world_left + width) / CHUNK_SIZE)) * CHUNK_SIZE
    for vx in range(start_x, end_x + 1, CHUNK_SIZE):
        rect = pygame.Rect(vx - road_thickness // 2 - camera_offset[0],
                           -camera_offset[1],
                           road_thickness,
                           height + 2 * road_thickness)
        pygame.draw.rect(surface, COLOR_ROAD, rect)
    start_y = int(math.floor(world_top / CHUNK_SIZE)) * CHUNK_SIZE
    end_y = int(math.ceil((world_top + height) / CHUNK_SIZE)) * CHUNK_SIZE
    for hy in range(start_y, end_y + 1, CHUNK_SIZE):
        rect = pygame.Rect(-camera_offset[0],
                           hy - road_thickness // 2 - camera_offset[1],
                           width + 2 * road_thickness,
                           road_thickness)
        pygame.draw.rect(surface, COLOR_ROAD, rect)

def draw_buildings(surface, buildings, camera_offset):
    for bld_list in buildings.values():
        for rect in bld_list:
            draw_rect = pygame.Rect(rect.x - camera_offset[0],
                                    rect.y - camera_offset[1],
                                    rect.width,
                                    rect.height)
            pygame.draw.rect(surface, COLOR_BUILDING, draw_rect)
            pygame.draw.rect(surface, COLOR_BUILDING_OUTLINE, draw_rect, 2)

def format_tower_snapshot(towers):
    return [f"[{t.id}] {t.identity} P:{t.priority} State:{t.get_status()[0]} S:{t.get_status()[1]:.2f}" for t in towers.values()]

def format_sib_summary(sib):
    return " | ".join([
        f"PLMN={','.join(sib['plmn_list'])}",
        f"TAC={sib['TAC']}",
        f"Barred={sib['cellBarred']}",
        f"CRP={sib['cellReselectionPriority']}",
        f"intraReSel={int(sib['intraFreqReselectionAllowed'])}",
        f"SI={sib['si_periodicity']}/{sib['si_window_length']}",
        f"RA=pIRP{sib['randomAccessConfig']['preambleInitialReceivedTargetPower']}+step{sib['randomAccessConfig']['powerRampingStep']}",
        f"AB={sib['accessBarring']['barringFactor']}",
        f"Nei={sib['neighbors']}",
    ])

def draw_menu(surface, font, screen_size):
    global W_DVER, W_PVER, W_SPVER, THETA_SUSPECT, THETA_BARRED, COMBO_PRIORITY_LOCATION_BOOST, generate_sib_traffic
    width, height = screen_size
    overlay_w = 420
    overlay_h = 340
    x = 16
    y = 16
    bg = pygame.Surface((overlay_w, overlay_h), pygame.SRCALPHA)
    bg.fill((10, 10, 10, 220))
    surface.blit(bg, (x, y))
    title_surf = font.render("CSIV Demo Menu / Parameters", True, (255, 255, 255))
    surface.blit(title_surf, (x + 10, y + 10))
    small = pygame.font.SysFont(FONT_NAME, 14)
    param_lines = [
        f"1/2: W_DVER (dup identity)     = {W_DVER:.2f}",
        f"3/4: W_PVER (priority dev)     = {W_PVER:.2f}",
        f"5/6: W_SPVER (signal dev)      = {W_SPVER:.2f}",
        f"7/8: THETA_SUSPECT             = {THETA_SUSPECT:.2f}",
        f"9/0: THETA_BARRED              = {THETA_BARRED:.2f}",
        f"Q/A: Combo boost              = {COMBO_PRIORITY_LOCATION_BOOST:.2f}",
        f"T: SIB generation             = {'ON' if generate_sib_traffic else 'OFF'}",
        f"Y: SIB display overlay        = {'ON' if True else 'OFF'}",
        "",
        "M: toggle menu",
        "H: toggle help",
        "L: log/toggle",
        "C: clear log",
        "R: rogue nearest toggle",
        "F/F11: fullscreen",
        "ESC: double-press to exit (single toggles menu)",
    ]
    for i, line in enumerate(param_lines):
        surf = small.render(line, True, (220, 220, 220))
        surface.blit(surf, (x + 10, y + 40 + i * 18))

def draw_log_panel(surface, log_entries, font, screen_size):
    width, height = screen_size
    panel_w = 380
    x = width - panel_w - 10
    y = 10
    bg = pygame.Surface((panel_w, height - 20), pygame.SRCALPHA)
    bg.fill((5, 5, 5, 220))
    surface.blit(bg, (x, y))
    header = font.render("Tower Status Log (latest)", True, (255, 255, 255))
    surface.blit(header, (x + 8, y + 8))
    max_lines = (height - 70) // 16
    for i, line in enumerate(log_entries[-max_lines:]):
        txt = font.render(line, True, (200, 200, 200))
        surface.blit(txt, (x + 8, y + 32 + i * 16))

def draw_help_overlay(surface, font, screen_size):
    width, height = screen_size
    overlay_w = 440
    overlay_h = 400
    x = (width - overlay_w) // 2
    y = (height - overlay_h) // 2
    bg = pygame.Surface((overlay_w, overlay_h), pygame.SRCALPHA)
    bg.fill((15, 15, 25, 230))
    surface.blit(bg, (x, y))
    title = font.render("Help / Controls", True, (255, 255, 255))
    surface.blit(title, (x + 16, y + 16))
    small = pygame.font.SysFont(FONT_NAME, 14)
    help_lines = [
        "Movement: Arrow keys",
        "R: Toggle rogue identity on nearest tower",
        "L: Snapshot & toggle log panel",
        "C: Clear log buffer",
        "M: Toggle menu",
        "H: Toggle help",
        "Y: Toggle SIB display overlay",
        "T: Toggle SIB generation (expensive)",
        "F/F11: Fullscreen",
        "1/2: W_DVER +/-",
        "3/4: W_PVER +/-",
        "5/6: W_SPVER +/-",
        "7/8: THETA_SUSPECT +/-",
        "9/0: THETA_BARRED +/-",
        "Q/A: Combo boost +/-",
        "ESC: Double-press to exit (single toggles menu)",
    ]
    for i, line in enumerate(help_lines):
        txt = small.render(line, True, (200, 200, 200))
        surface.blit(txt, (x + 16, y + 50 + i * 20))

# ---------------- Main Loop ----------------

def run_game():
    global W_DVER, W_PVER, W_SPVER, THETA_SUSPECT, THETA_BARRED, COMBO_PRIORITY_LOCATION_BOOST, generate_sib_traffic
    pygame.init()
    try:
        screen = pygame.display.set_mode((1000, 700))
    except Exception as e:
        print("Failed to create display:", e)
        input("Display init failed. Press Enter to exit.")
        sys.exit(1)
    pygame.display.set_caption("CSIV Demo v7.2 - Clean/Rogue Neighbor Isolation")
    clock = pygame.time.Clock()
    font_status = pygame.font.SysFont(FONT_NAME, 16)
    font_log = pygame.font.SysFont(FONT_NAME, 14)
    font_menu = pygame.font.SysFont(FONT_NAME, 18)
    font_help = pygame.font.SysFont(FONT_NAME, 20)
    font_small = pygame.font.SysFont(FONT_NAME, 14)
    ue = UE((100.0, 100.0))
    towers = {}
    buildings = {}
    seen_chunks = set()
    pending_chunks = deque()
    next_tower_id = 1
    show_menu = True
    show_help = False
    show_log = False
    show_sib = True
    log_entries = []
    active_sib_msgs = []
    fullscreen = False

    last_escape_time = 0.0
    ESC_GRACE = 0.4  # seconds between presses to actually exit

    if DEBUG_MODE:
        print(">> run_game entered")

    running = True
    exit_reason = None
    while running:
        if DEBUG_MODE:
            print("tick")
        dt = clock.tick(60) / 1000.0
        current = now()

        for event in pygame.event.get():
            if DEBUG_MODE:
                print("EVENT:", event)
            if event.type == pygame.QUIT:
                exit_reason = "QUIT"
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if current < 0.5:
                        if DEBUG_MODE:
                            print("Ignored early ESC event")
                    else:
                        now_time = now()
                        if now_time - last_escape_time < ESC_GRACE:
                            exit_reason = "ESC"
                            running = False
                        else:
                            last_escape_time = now_time
                            show_menu = not show_menu
                            if DEBUG_MODE:
                                print("ESC pressed once; press again quickly to exit.")
                elif event.key in (pygame.K_F11, pygame.K_f):
                    fullscreen = not fullscreen
                    if fullscreen:
                        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                    else:
                        screen = pygame.display.set_mode((1000, 700))
                elif event.key == pygame.K_m:
                    show_menu = not show_menu
                elif event.key == pygame.K_h:
                    show_help = not show_help
                elif event.key == pygame.K_l:
                    snapshot = format_tower_snapshot(towers)
                    timestamp = time.strftime("%H:%M:%S")
                    log_entries.append(f"---- {timestamp} ----")
                    log_entries.extend(snapshot)
                    show_log = not show_log
                elif event.key == pygame.K_c:
                    log_entries.clear()
                elif event.key == pygame.K_r:
                    if towers:
                        nearest = min(towers.values(), key=lambda t: t.distance_to(ue.pos))
                        if nearest.is_rogue:
                            nearest.is_rogue = False
                            nearest.identity = nearest.identity.replace("_ROGUE", "")
                        else:
                            nearest.is_rogue = True
                            if not nearest.identity.endswith("_ROGUE"):
                                nearest.identity += "_ROGUE"
                        # recompute neighbors with segregation rules
                        all_towers = list(towers.values())
                        for t in all_towers:
                            if t.is_rogue:
                                t.neighbors = []
                            else:
                                candidates = [other for other in all_towers if other is not t and not other.is_rogue]
                                dists = sorted([(t.distance_to(other.pos), other.id) for other in candidates])
                                t.neighbors = [tid for dist, tid in dists if dist <= NEIGHBOR_RADIUS][:MAX_NEIGHBORS]
                elif event.key == pygame.K_1:
                    W_DVER += 0.1
                elif event.key == pygame.K_2:
                    W_DVER = max(0.0, W_DVER - 0.1)
                elif event.key == pygame.K_3:
                    W_PVER += 0.1
                elif event.key == pygame.K_4:
                    W_PVER = max(0.0, W_PVER - 0.1)
                elif event.key == pygame.K_5:
                    W_SPVER += 0.1
                elif event.key == pygame.K_6:
                    W_SPVER = max(0.0, W_SPVER - 0.1)
                elif event.key == pygame.K_7:
                    THETA_SUSPECT = min(1.0, THETA_SUSPECT + 0.05)
                elif event.key == pygame.K_8:
                    THETA_SUSPECT = max(0.0, THETA_SUSPECT - 0.05)
                elif event.key == pygame.K_9:
                    THETA_BARRED = min(1.0, THETA_BARRED + 0.05)
                elif event.key == pygame.K_0:
                    THETA_BARRED = max(0.0, THETA_BARRED - 0.05)
                elif event.key == pygame.K_q:
                    COMBO_PRIORITY_LOCATION_BOOST += 0.1
                elif event.key == pygame.K_a:
                    COMBO_PRIORITY_LOCATION_BOOST = max(0.0, COMBO_PRIORITY_LOCATION_BOOST - 0.1)
                elif event.key == pygame.K_y:
                    show_sib = not show_sib
                elif event.key == pygame.K_t:
                    generate_sib_traffic = not generate_sib_traffic
                    if DEBUG_MODE:
                        print(f"SIB traffic generation {'enabled' if generate_sib_traffic else 'disabled'}")

        # Movement
        keys = pygame.key.get_pressed()
        speed = 180 * dt
        if keys[pygame.K_LEFT]:
            ue.pos[0] -= speed
        if keys[pygame.K_RIGHT]:
            ue.pos[0] += speed
        if keys[pygame.K_UP]:
            ue.pos[1] -= speed
        if keys[pygame.K_DOWN]:
            ue.pos[1] += speed

        # Enqueue nearby chunks
        current_chunk = chunk_coords(ue.pos)
        for dx in range(-PREFETCH_RADIUS, PREFETCH_RADIUS + 1):
            for dy in range(-PREFETCH_RADIUS, PREFETCH_RADIUS + 1):
                chunk = (current_chunk[0] + dx, current_chunk[1] + dy)
                if chunk not in seen_chunks and chunk not in pending_chunks:
                    pending_chunks.append(chunk)

        # Throttled chunk creation
        chunks_done = 0
        while pending_chunks and chunks_done < MAX_CHUNKS_PER_FRAME and len(towers) < MAX_TOTAL_TOWERS:
            chunk = pending_chunks.popleft()
            if chunk in seen_chunks:
                continue
            seen_chunks.add(chunk)
            next_tower_id = generate_towers_buildings(
                chunk[0], chunk[1], towers, buildings, next_tower_id
            )
            chunks_done += 1

        # Update towers (throttled)
        for t in towers.values():
            if now() >= t.next_state_update:
                t.update_state(ue.pos, towers)
                t.next_state_update = now() + TOWER_UPDATE_INTERVAL

        # Generate SIBs only if enabled
        if generate_sib_traffic:
            for t in list(towers.values()):
                if now() >= t.next_sib_time:
                    sib = t.generate_sib_info()
                    text = format_sib_summary(sib)
                    active_sib_msgs.append({
                        "tower": t,
                        "text": text,
                        "created": now(),
                        "duration": 2.5
                    })
                    t.next_sib_time = now() + random.uniform(SIB_INTERVAL_MIN, SIB_INTERVAL_MAX)

        if len(active_sib_msgs) > MAX_ACTIVE_SIB_MSGS:
            active_sib_msgs = active_sib_msgs[-MAX_ACTIVE_SIB_MSGS:]

        # Camera
        screen_size = screen.get_size()
        width, height = screen_size
        camera_offset = (ue.pos[0] - width / 2, ue.pos[1] - height / 2)

        # Draw background/grid
        draw_city_block_background(screen, camera_offset, screen_size)

        # Draw roads & buildings & towers
        draw_roads(screen, camera_offset, screen_size)
        draw_buildings(screen, buildings, camera_offset)

        for t in towers.values():
            st, sc = t.get_status()
            color = t.get_display_color(now())
            screen_pos = (int(t.pos[0] - camera_offset[0]), int(t.pos[1] - camera_offset[1]))
            pygame.draw.circle(screen, color, screen_pos, 16)
            id_surf = font_small.render(f"{t.identity}", True, (220, 220, 220))
            screen.blit(id_surf, (screen_pos[0] - 25, screen_pos[1] - 35))
            pr_surf = font_small.render(f"P:{t.priority}", True, (255, 255, 0))
            screen.blit(pr_surf, (screen_pos[0] - 25, screen_pos[1] + 20))
            s_surf = font_small.render(f"{st}", True, (0, 0, 0))
            screen.blit(s_surf, (screen_pos[0] - 25, screen_pos[1] - 8))

        # Draw UE
        ue_screen = (int(ue.pos[0] - camera_offset[0]), int(ue.pos[1] - camera_offset[1]))
        pygame.draw.rect(screen, COLOR_CAR, pygame.Rect(ue_screen[0] - 10, ue_screen[1] - 10, 20, 20))
        ue_surf = pygame.font.SysFont(FONT_NAME, 16).render("UE", True, (0, 0, 0))
        screen.blit(ue_surf, (ue_screen[0] - 10, ue_screen[1] - 30))

        # Nearest tower HUD
        if towers:
            distances = [(t.distance_to(ue.pos), t) for t in towers.values()]
            distances.sort(key=lambda x: x[0])
            nearest = distances[0][1]
            st, sc = nearest.get_status()
            panel_w = 360
            panel_h = 160
            panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
            panel.fill((15, 15, 25, 230))
            screen.blit(panel, (10, 10))
            lines = [
                f"Nearest Tower ID: {nearest.id}",
                f"Identity: {nearest.identity}",
                f"Priority: {nearest.priority}",
                f"State: {st}",
                f"Suspicion Score: {sc:.2f}",
                f"SIB Summary: {format_sib_summary(nearest.generate_sib_info())}",
            ]
            for i, line in enumerate(lines):
                txt = font_status.render(line, True, (240, 240, 240))
                screen.blit(txt, (15, 15 + i * 18))

        # Active SIB overlays (nearby only)
        if show_sib:
            new_sib_msgs = []
            for msg in active_sib_msgs:
                age = now() - msg["created"]
                if age > msg["duration"]:
                    continue
                tower = msg["tower"]
                if tower.distance_to(ue.pos) > SIB_DRAW_DISTANCE:
                    continue
                new_sib_msgs.append(msg)
                screen_pos = (int(tower.pos[0] - camera_offset[0]), int(tower.pos[1] - camera_offset[1]))
                x = screen_pos[0]
                y = screen_pos[1] - 55
                alpha = 255
                if age > msg["duration"] * 0.7:
                    fade_factor = (msg["duration"] - age) / (msg["duration"] * 0.3)
                    alpha = int(255 * max(0.1, fade_factor))
                sib_bg = pygame.Surface((260, 28), pygame.SRCALPHA)
                sib_bg.fill((30, 30, 40, alpha))
                screen.blit(sib_bg, (x - 130, y))
                txt = pygame.font.SysFont(FONT_NAME, 14).render(msg["text"], True, (200, 200, 200))
                screen.blit(txt, (x - 125, y + 4))
            active_sib_msgs = new_sib_msgs

        # Footer
        footer = [
            "M:menu H:help Y:SIB L:log C:clear R:rogue T:toggle-SIB-gen F:fullscreen ESC:exit",
            f"W_DVER={W_DVER:.2f} W_PVER={W_PVER:.2f} W_SPVER={W_SPVER:.2f} THETA_SUSPECT={THETA_SUSPECT:.2f} THETA_BARRED={THETA_BARRED:.2f}"
        ]
        for i, text in enumerate(footer):
            foot_bg = pygame.Surface((width - 20, 22), pygame.SRCALPHA)
            foot_bg.fill((10, 10, 10, 180))
            screen.blit(foot_bg, (10, height - (i + 1) * 24 - 2))
            txt = font_status.render(text, True, (200, 200, 200))
            screen.blit(txt, (15, height - (i + 1) * 24 + 2))

        # Overlays
        if show_log:
            draw_log_panel(screen, log_entries, font_log, screen_size)
        if show_menu:
            draw_menu(screen, font_menu, screen_size)
        if show_help:
            draw_help_overlay(screen, font_help, screen_size)

        pygame.display.flip()

    if DEBUG_MODE:
        print(f"Exiting run_game reason: {exit_reason}")
    pygame.quit()

# ---------------- Entry Point ----------------

if __name__ == "__main__":
    try:
        run_game()
    except Exception:
        import traceback, datetime
        tb = traceback.format_exc()
        with open("csiv_demo_error.log", "a") as f:
            f.write(f"{datetime.datetime.now()}\n{tb}\n{'-'*60}\n")
        print("Unhandled exception occurred. Traceback written to csiv_demo_error.log")
        print(tb)
        input("Error occurred; press Enter to exit.")
    else:
        try:
            input("Demo exited normally. Press Enter to close.")
        except Exception:
            pass

