# Drives the MLB app's update() on the badge with simulated buttons; RLE screenshots go to /state/shots.
import sys, os, time, gc, builtins
from array import array
DEV = '/state/dev_mlb'
captured = []
class Result:
    result = None
builtins.run = lambda fn: (captured.append(fn), Result())[1]
real_pressed, real_held = badge.pressed, badge.held
held_now = set(); pressed_now = set()
badge.pressed = lambda b=None: (b in pressed_now) if b is not None else set(pressed_now)
badge.held = lambda b=None: (b in held_now) if b is not None else set(held_now)
for d in ('/state/shots', '/state/mlb'):
    try: os.mkdir(d)
    except OSError: pass
for d in ('/state/shots', '/state/mlb'):
    for n in os.listdir(d): os.remove(d + '/' + n)
# seed caches: a fabricated live slate as "today", real standings, and a live linescore for the first game
for src, dst in (('/state/seed/app_live.json', '/state/mlb/schedule.json'), ('/state/seed/app_standings.json', '/state/mlb/standings.json'), ('/state/seed/app_line_live.json', '/state/mlb/game_822679.json')):
    with open(src) as s, open(dst, 'w') as d: d.write(s.read())
sys.path.insert(0, DEV); os.chdir(DEV)
src = open(DEV + '/__init__.py').read().replace('APP_DIR = "/system/apps/mlb"', 'APP_DIR = "%s"' % DEV)
g = {'__name__': 'mlb_dev'}
t = time.ticks_ms(); exec(src, g); print('import took', time.ticks_diff(time.ticks_ms(), t), 'ms; today', g['today'], 'games', len(g['board'].games), 'offset', g['OFFSET'])
update = captured[0]
def rle(raw):
    pixels = array('H', raw); out = array('H'); prev = pixels[0]; count = 0
    for value in pixels:
        if value == prev and count < 65535: count += 1
        else: out.append(count); out.append(prev); prev = value; count = 1
    out.append(count); out.append(prev); return out
shots = 0
def step(buttons):
    global pressed_now, held_now
    buttons = set(buttons); pressed_now = buttons - held_now; held_now = buttons
    t = time.ticks_ms(); update(); cost = time.ticks_diff(time.ticks_ms(), t)
    raw = bytes(screen.raw); badge.update(); return cost, raw
def frames(n, buttons=(), label=None):
    global shots
    worst = 0
    for i in range(n):
        cost, raw = step(buttons if i == 0 else ()); worst = max(worst, cost)
    if label is None:
        return
    with open('/state/shots/%d.rle' % shots, 'wb') as f: f.write(rle(raw))
    print('SHOT %d [%s] worst %d ms mode %d sel %d' % (shots, label, worst, g['mode'], g['board'].selected)); shots += 1
badge.update()
frames(3, label='splash')
time.sleep_ms(1700); badge.update()
frames(1, (BUTTON_SELECT,)); frames(6, label='board with logos')
t = time.ticks_ms(); frames(1); print('board frame after logos cached', time.ticks_diff(time.ticks_ms(), t), 'ms')
frames(1, (BUTTON_DOWN,)); frames(1); frames(1, (BUTTON_DOWN,)); frames(1); frames(1, (BUTTON_DOWN,)); frames(2, label='board sel 3')
frames(1, (BUTTON_UP,)); frames(1); frames(1, (BUTTON_UP,)); frames(1); frames(1, (BUTTON_UP,)); frames(1)
frames(1, (BUTTON_SELECT,)); frames(3, label='game live with logos')
frames(1, (BUTTON_RIGHT,)); frames(3, label='game preview with logos')
frames(1, (BUTTON_RIGHT,)); frames(1); frames(1, (BUTTON_RIGHT,)); frames(3, label='game final with logos')
frames(1, (BUTTON_BACK,)); frames(1); frames(1, (BUTTON_MENU,)); frames(3, label='standings with logos')
frames(1, (BUTTON_RIGHT,)); frames(1); frames(1, (BUTTON_RIGHT,)); frames(3, label='standings AL West')
frames(1, (BUTTON_BACK,)); frames(2)
stalls = []
for i in range(200):
    cost, _ = step((BUTTON_DOWN,) if i % 2 else ())
    if cost > 60: stalls.append((i, cost))
print('stalls over 60ms in 200 frames:', stalls)
g['on_exit']()
badge.pressed, badge.held = real_pressed, real_held
gc.collect(); print('DONE', shots, 'free', gc.mem_free(), 'lights', badge._case_light_values)
