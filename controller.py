# ================================================================
#  Puppet AI Controller
#  Connects TinyLlama LLM → ESP32 Puppet via WebSocket
#  Built by Aiko
# ================================================================
#  Servo types:
#    GPIO 18  Lift           360° continuous  → LIFT:UP/DOWN:ms
#    GPIO 19  Left Shoulder  180° positional  → LS:angle
#    GPIO 21  Right Shoulder 360° continuous  → RS:CW/CCW:ms
#    GPIO 22  Hand Left      360° continuous  → LH:CW/CCW:ms
#    GPIO 23  Hand Right     360° continuous  → RH:CW/CCW:ms
# ================================================================

import os, sys, asyncio, time, threading

os.environ["HF_HOME"]            = "E:\\huggingface_cache"
os.environ["TRANSFORMERS_CACHE"] = "E:\\huggingface_cache"

import torch
import websockets
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

# ── Config ────────────────────────────────────────────────────
MODEL_NAME   = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
FINAL_DIR    = "E:\\puppet_ai\\puppet_llm_final"
ESP32_IP     = "192.168.4.1"
ESP32_WS     = f"ws://{ESP32_IP}:81"
SETTLE_TIME  = 0.3   # seconds between commands

# ── Load LLM ──────────────────────────────────────────────────
print("Loading puppet LLM...")
tokenizer = AutoTokenizer.from_pretrained(FINAL_DIR)
base      = AutoModelForCausalLM.from_pretrained(
                MODEL_NAME, dtype=torch.float16, device_map="auto")
model     = PeftModel.from_pretrained(base, FINAL_DIR)
model.eval()
print("LLM ready!\n")

# ── Generate Motion from Command ──────────────────────────────
def generate_motion(command: str) -> str:
    prompt = (
        f"<|system|>\n"
        f"You are a puppet motion controller. "
        f"Convert natural language commands into motion sequences.\n"
        f"</s>\n"
        f"<|user|>\n{command}\n</s>\n"
        f"<|assistant|>\n"
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens = 80,
            temperature    = 0.2,
            do_sample      = True,
            pad_token_id   = tokenizer.eos_token_id,
            eos_token_id   = tokenizer.eos_token_id,
        )
    result = tokenizer.decode(out[0], skip_special_tokens=True)
    motion = result.split("<|assistant|>")[-1].strip()
    if motion.endswith(","):
        motion = motion[:-1]
    return motion

# ── Parse Motion String into Command List ─────────────────────
def parse_motion(motion_str: str) -> list:
    commands = []
    for part in motion_str.split(","):
        part = part.strip()
        if part:
            commands.append(part.split(":"))
    return commands

# ── Execute One Command on ESP32 ──────────────────────────────
async def execute_command(ws, parts: list):
    if not parts:
        return

    token = parts[0].upper()

    # ── Left Shoulder — 180° positional ───────────────────────
    # Format: LS:angle  (e.g. LS:130)
    if token == "LS":
        if len(parts) >= 2:
            angle = max(0, min(180, int(parts[1])))
            await ws.send(f"SHOULDER_L:{angle}")
            await asyncio.sleep(0.6)   # wait for servo to reach angle

    # ── Right Shoulder — 360° continuous ──────────────────────
    # Format: RS:CW:ms  or  RS:CCW:ms  or  RS:STOP
    elif token == "RS":
        if len(parts) >= 2:
            direction = parts[1].upper()
            if direction in ("CW", "CCW") and len(parts) >= 3:
                ms  = int(parts[2])
                key = "Q" if direction == "CW" else "W"
                await ws.send(f"KD:{key}")
                await asyncio.sleep(ms / 1000)
                await ws.send(f"KU:{key}")
            elif direction == "STOP":
                await ws.send("KU:Q")
                await ws.send("KU:W")

    # ── Lift — 360° continuous ────────────────────────────────
    # Format: LIFT:UP:ms  or  LIFT:DOWN:ms  or  LIFT:STOP
    elif token == "LIFT":
        if len(parts) >= 2:
            direction = parts[1].upper()
            if direction in ("UP", "DOWN") and len(parts) >= 3:
                ms  = int(parts[2])
                key = "UP" if direction == "UP" else "DOWN"
                await ws.send(f"KD:{key}")
                await asyncio.sleep(ms / 1000)
                await ws.send(f"KU:{key}")
            elif direction == "STOP":
                await ws.send("KU:UP")
                await ws.send("KU:DOWN")

    # ── Hand Left — 360° continuous ───────────────────────────
    # Format: LH:CW:ms  or  LH:CCW:ms  or  LH:STOP
    elif token == "LH":
        if len(parts) >= 2:
            direction = parts[1].upper()
            if direction in ("CW", "CCW") and len(parts) >= 3:
                ms  = int(parts[2])
                key = "K" if direction == "CW" else "L"
                await ws.send(f"KD:{key}")
                await asyncio.sleep(ms / 1000)
                await ws.send(f"KU:{key}")
            elif direction == "STOP":
                await ws.send("KU:K")
                await ws.send("KU:L")

    # ── Hand Right — 360° continuous ──────────────────────────
    # Format: RH:CW:ms  or  RH:CCW:ms  or  RH:STOP
    elif token == "RH":
        if len(parts) >= 2:
            direction = parts[1].upper()
            if direction in ("CW", "CCW") and len(parts) >= 3:
                ms  = int(parts[2])
                key = "A" if direction == "CW" else "S"
                await ws.send(f"KD:{key}")
                await asyncio.sleep(ms / 1000)
                await ws.send(f"KU:{key}")
            elif direction == "STOP":
                await ws.send("KU:A")
                await ws.send("KU:S")

    # ── Wait / Pause ──────────────────────────────────────────
    elif token == "WAIT":
        if len(parts) >= 2:
            await asyncio.sleep(int(parts[1]) / 1000)

    # ── Home ──────────────────────────────────────────────────
    elif token == "HOME":
        await ws.send("HOME")
        await asyncio.sleep(1.5)

    # ── Stop all ──────────────────────────────────────────────
    elif token == "STOP":
        for key in ["UP","DOWN","Q","W","K","L","A","S"]:
            await ws.send(f"KU:{key}")

# ── Stop all servos safely ────────────────────────────────────
async def stop_all_servos(ws):
    for key in ["UP","DOWN","Q","W","K","L","A","S"]:
        await ws.send(f"KU:{key}")

# ── Execute Full Motion Sequence ──────────────────────────────
async def execute_on_esp32(motion_str: str):
    commands = parse_motion(motion_str)
    if not commands:
        print("  No valid commands parsed")
        return

    print(f"  Connecting to ESP32 at {ESP32_WS} ...")
    try:
        async with websockets.connect(
            ESP32_WS,
            ping_interval=None,
            open_timeout=5
        ) as ws:
            print(f"  Connected — executing {len(commands)} commands")
            for i, parts in enumerate(commands):
                cmd_str = ":".join(parts)
                print(f"    [{i+1}/{len(commands)}] {cmd_str}")
                await execute_command(ws, parts)
                await asyncio.sleep(SETTLE_TIME)

            await stop_all_servos(ws)
            print("  Done ✅")

    except ConnectionRefusedError:
        print(f"  ERROR: Cannot connect to {ESP32_IP}")
        print("  → Make sure PC is connected to ESP32_Puppet WiFi")
        print("  → Make sure home position is set on the puppet UI first")
    except asyncio.TimeoutError:
        print("  ERROR: Connection timed out — ESP32 not reachable")
    except Exception as e:
        print(f"  ERROR: {e}")

# ── Set Home via WebSocket ────────────────────────────────────
async def send_set_home():
    try:
        async with websockets.connect(ESP32_WS, ping_interval=None, open_timeout=5) as ws:
            await ws.send("SET_HOME")
            await asyncio.sleep(0.5)
            print("  Home set on ESP32 ✅")
    except Exception as e:
        print(f"  Could not set home: {e}")

# ── Demo Sequence ─────────────────────────────────────────────
async def run_demo():
    demo = [
        ("say hi",        None),
        ("do namaste",    None),
        ("bow down",      None),
        ("wave goodbye",  None),
    ]
    print("\n  Running demo sequence...\n")
    for command, _ in demo:
        print(f"Command : {command}")
        motion = generate_motion(command)
        print(f"Motion  : {motion}")
        await execute_on_esp32(motion)
        await asyncio.sleep(1.5)
        print()

# ── Main Loop ─────────────────────────────────────────────────
async def main():
    print("=" * 55)
    print("  Puppet AI Controller")
    print(f"  ESP32  : {ESP32_IP}")
    print(f"  Model  : TinyLlama 1.1B (fine-tuned)")
    print("=" * 55)
    print()
    print("  Commands:")
    print("    any text     → LLM generates + executes on puppet")
    print("    'offline'    → test LLM output without ESP32")
    print("    'sethome'    → send SET_HOME to ESP32")
    print("    'demo'       → run 4-action demo sequence")
    print("    'test'       → test LLM on 10 sample commands")
    print("    'quit'       → exit")
    print()
    print("  IMPORTANT: Set home position on web UI (192.168.4.1)")
    print("             before running any puppet commands!")
    print("=" * 55 + "\n")

    offline_mode = False

    while True:
        try:
            raw = input("Command: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if not raw:
            continue

        command = raw.lower()

        if command in ("quit", "exit", "q"):
            break

        # ── Offline mode toggle ────────────────────────────────
        elif command == "offline":
            offline_mode = not offline_mode
            print(f"  Offline mode: {'ON — LLM only, no ESP32' if offline_mode else 'OFF — sending to ESP32'}\n")

        # ── Set home on ESP32 ──────────────────────────────────
        elif command == "sethome":
            print("  Sending SET_HOME to ESP32...")
            await send_set_home()
            print()

        # ── Demo sequence ──────────────────────────────────────
        elif command == "demo":
            await run_demo()

        # ── Test LLM on 10 commands ───────────────────────────
        elif command == "test":
            test_cmds = [
                "say hi", "wave hello", "do namaste",
                "bow down", "wave goodbye", "raise hands",
                "say hi and bow", "greet the audience",
                "wave slowly", "go home",
            ]
            print("\n  LLM Test Results:")
            print("  " + "-"*50)
            for tc in test_cmds:
                motion = generate_motion(tc)
                print(f"  [{tc}]")
                print(f"    → {motion}")
            print()

        # ── Normal LLM command ─────────────────────────────────
        else:
            print("  Generating motion...")
            t0     = time.time()
            motion = generate_motion(raw)
            elapsed = time.time() - t0

            print(f"  Motion  : {motion}")
            print(f"  LLM time: {elapsed:.2f}s")

            if offline_mode:
                print("  [OFFLINE — not sent to ESP32]\n")
            else:
                await execute_on_esp32(motion)

            print()

asyncio.run(main())

# ================================================================
#  MOTION LANGUAGE REFERENCE
# ================================================================
#
#  Left Shoulder  (180° positional):
#    LS:90          → move to 90°
#    LS:130         → move to 130° (raise)
#    LS:50          → move to 50°  (lower)
#
#  Right Shoulder  (360° continuous):
#    RS:CW:500      → spin CW for 500ms then stop
#    RS:CCW:400     → spin CCW for 400ms then stop
#    RS:STOP        → stop immediately
#
#  Lift  (360° continuous):
#    LIFT:UP:800    → spin up for 800ms then stop
#    LIFT:DOWN:600  → spin down for 600ms then stop
#    LIFT:STOP      → stop immediately
#
#  Hand Left  (360° continuous):
#    LH:CW:400      → spin CW for 400ms then stop
#    LH:CCW:300     → spin CCW for 300ms then stop
#    LH:STOP        → stop immediately
#
#  Hand Right  (360° continuous):
#    RH:CW:400      → spin CW for 400ms then stop
#    RH:CCW:300     → spin CCW for 300ms then stop
#    RH:STOP        → stop immediately
#
#  Wait:
#    WAIT:1000      → pause for 1000ms
#
#  Special:
#    HOME           → go to home position
#    STOP           → stop all servos
#
#  Combined example:
#    LS:130,RS:CW:500,WAIT:300,LS:90,RS:STOP
#    = raise left shoulder, spin right shoulder, wait, return both
#
# ================================================================