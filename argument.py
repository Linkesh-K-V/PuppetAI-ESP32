# ================================================================
#  Puppet Dataset Generator — Updated for Mixed Servo Setup
#  Built by Aiko
# ================================================================
#  LS:angle         = Left Shoulder  (180° positional, 0-180)
#  RS:CW/CCW:ms     = Right Shoulder (360° continuous)
#  LIFT:UP/DOWN:ms  = Lift           (360° continuous)
#  LH:CW/CCW:ms     = Hand Left      (360° continuous)
#  RH:CW/CCW:ms     = Hand Right     (360° continuous)
#  WAIT:ms          = pause
#  HOME             = go home
# ================================================================

import json, os

OUTPUT = "E:\\puppet_ai\\puppet_dataset.jsonl"

# ── Base motions ───────────────────────────────────────────────
BASE = {
    # Wave right hand
    "wave":         "RH:CW:400,RH:STOP,RH:CW:300,RH:STOP",
    "wave_slow":    "RH:CW:150,RH:STOP,RH:CW:150,RH:STOP",
    "wave_fast":    "RH:CW:700,RH:STOP,RH:CW:600,RH:STOP",

    # Left shoulder raise (positional — goes to angle)
    "ls_raise":     "LS:140,WAIT:1500,LS:90",
    "ls_raise_both":"LS:140,RS:CW:400,RS:STOP,WAIT:1500,LS:90,RS:CCW:400,RS:STOP",

    # Namaste — both shoulders inward
    "namaste":      "LS:130,WAIT:1500,LS:90",

    # Bow — lift goes down
    "bow":          "LIFT:DOWN:700,LIFT:STOP,WAIT:600,LIFT:UP:700,LIFT:STOP",

    # Goodbye wave
    "goodbye":      "RH:CW:400,RH:STOP,RH:CCW:400,RH:STOP,RH:CW:300,RH:STOP",
    "goodbye_slow": "RH:CW:200,RH:STOP,RH:CCW:200,RH:STOP",

    # Lift up (raise whole puppet)
    "lift_up":      "LIFT:UP:600,LIFT:STOP",
    "lift_down":    "LIFT:DOWN:600,LIFT:STOP",

    # Wave left hand
    "wave_left":    "LH:CW:400,LH:STOP,LH:CW:300,LH:STOP",

    # Both hands wave
    "wave_both":    "LH:CW:400,RH:CW:400,LH:STOP,RH:STOP",

    # Home
    "home":         "HOME",
}

# ── Phrase variations per motion ──────────────────────────────
PHRASES = {
    "wave": [
        "say hi","wave hello","wave hand","greet",
        "hello wave","say hello","wave at camera",
        "hi wave","give a wave","wave to audience",
        "greet the audience","greet someone","greet everyone",
    ],
    "wave_slow": [
        "wave slowly","slow wave","wave gently",
        "gentle wave","slow hello","wave softly",
    ],
    "wave_fast": [
        "wave fast","fast wave","wave quickly","quick wave",
    ],
    "namaste": [
        "do namaste","perform namaste","namaste gesture",
        "prayer hands","join hands","folded hands",
        "show namaste","greet with namaste",
        "traditional greeting","indian greeting",
    ],
    "bow": [
        "bow down","take a bow","bend down",
        "bow to audience","do a bow","theatrical bow",
        "show respect","curtsy",
    ],
    "goodbye": [
        "wave goodbye","say bye","farewell wave",
        "bye bye","wave bye","say goodbye",
        "goodbye wave","see you later","farewell",
    ],
    "goodbye_slow": [
        "wave goodbye slowly","slow goodbye",
        "gentle farewell","wave bye slowly",
    ],
    "ls_raise": [
        "raise left shoulder","lift left arm",
        "move left shoulder up","left shoulder up",
    ],
    "ls_raise_both": [
        "raise both shoulders","lift both arms",
        "arms up","hands up","raise hands",
        "put hands up","both arms up",
    ],
    "lift_up": [
        "lift up","go up","rise up","puppet up",
    ],
    "lift_down": [
        "lift down","go down","lower down","puppet down",
    ],
    "wave_left": [
        "wave left hand","left hand wave",
        "move left hand","wave with left",
    ],
    "wave_both": [
        "wave both hands","both hands wave",
        "wave with both hands","two hand wave",
    ],
    "home": [
        "go home","reset","stand straight",
        "neutral position","reset position",
        "return home","starting position","initial position",
    ],
}

# ── Combined multi-action phrases ─────────────────────────────
COMBOS = [
    ("say hi and bow",
     BASE["wave"] + ",WAIT:300," + BASE["bow"]),

    ("say hello and bow",
     BASE["wave"] + ",WAIT:300," + BASE["bow"]),

    ("greet and bow",
     BASE["wave"] + ",WAIT:200," + BASE["bow"]),

    ("wave and bow",
     BASE["wave"] + ",WAIT:200," + BASE["bow"]),

    ("namaste and bow",
     BASE["namaste"] + ",WAIT:300," + BASE["bow"]),

    ("do namaste and bow",
     BASE["namaste"] + ",WAIT:300," + BASE["bow"]),

    ("say hi do namaste and bow",
     BASE["wave"] + ",WAIT:200," + BASE["namaste"] + ",WAIT:200," + BASE["bow"]),

    ("say hello and goodbye",
     BASE["wave"] + ",WAIT:500," + BASE["goodbye"]),

    ("greet and wave goodbye",
     BASE["wave"] + ",WAIT:400," + BASE["goodbye"]),

    ("greet with namaste",
     BASE["wave"] + ",WAIT:200," + BASE["namaste"]),

    ("farewell sequence",
     BASE["wave"] + ",WAIT:200," + BASE["bow"] + ",WAIT:200," + BASE["goodbye"]),

    ("full greeting",
     BASE["wave"] + ",WAIT:200," + BASE["namaste"] + ",WAIT:200," + BASE["bow"]),

    ("wave slowly then bow",
     BASE["wave_slow"] + ",WAIT:300," + BASE["bow"]),

    ("raise hands and wave",
     BASE["ls_raise_both"] + ",WAIT:200," + BASE["wave"]),

    ("welcome the audience",
     BASE["ls_raise_both"] + ",WAIT:500," + BASE["namaste"]),

    ("perform a greeting",
     BASE["wave"] + ",WAIT:200," + BASE["namaste"]),

    ("show appreciation",
     BASE["bow"] + ",WAIT:300," + BASE["namaste"]),

    ("wave and lift up",
     BASE["wave"] + ",WAIT:200," + BASE["lift_up"]),

    ("say goodbye and bow",
     BASE["goodbye"] + ",WAIT:300," + BASE["bow"]),
]

# ── Build dataset ─────────────────────────────────────────────
examples = []

for motion_key, phrases in PHRASES.items():
    for phrase in phrases:
        examples.append({
            "input" : phrase,
            "output": BASE[motion_key]
        })

for inp, out in COMBOS:
    examples.append({"input": inp, "output": out})

# Auto-generate phrase variations
prefixes  = ["please ", "can you ", "now ", ""]
suffixes  = [" now", " please", ""]
extra = []
for ex in examples[:40]:   # only vary first 40 to avoid dataset bloat
    for p in prefixes:
        for s in suffixes:
            var = f"{p}{ex['input']}{s}".strip()
            if var != ex["input"]:
                extra.append({"input": var, "output": ex["output"]})

examples += extra[:60]   # add max 60 variations

# Save
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, "w") as f:
    for ex in examples:
        f.write(json.dumps(ex) + "\n")

print(f"Dataset created: {len(examples)} examples")
print(f"Saved to: {OUTPUT}")
print()
print("Motion language used:")
print("  LS:angle          Left Shoulder (180° positional)")
print("  RS:CW/CCW:ms      Right Shoulder (360° continuous)")
print("  LIFT:UP/DOWN:ms   Lift (360° continuous)")
print("  LH:CW/CCW:ms      Hand Left (360° continuous)")
print("  RH:CW/CCW:ms      Hand Right (360° continuous)")
print("  WAIT:ms           Pause")
print("  HOME              Return to home")