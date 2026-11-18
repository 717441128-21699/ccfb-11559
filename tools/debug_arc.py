import sys
sys.path.insert(0, ".")
from levelcheck.level import load_level
from levelcheck.simulate import make_spawn_state, step, JumpInput

level = load_level("levels/level_1_1_basic.json")
cfg = level.physics
st = make_spawn_state(level)
print("spawn", st.x, st.y)

# 向右满跑 + 满跳(第 1 帧起跳)
for f in range(60):
    jump = f == 0
    ev = step(level, st, JumpInput(move=1, jump_pressed=jump, jump_held=True))
    if f <= 46 and (f % 2 == 0 or ev.landed or ev.deaths):
        print(f"f={f} x={st.x:.3f} y={st.y:.3f} vx={st.vx:.3f} vy={st.vy:.3f} "
              f"grounded={st.grounded} landed={[l.kind for l in ev.landed]} dead={st.dead}")
    if st.dead:
        print("DEAD", st.death_reason)
        break
print("full jump height:", cfg.full_jump_height(), "flight frames:", cfg.full_jump_frames())
