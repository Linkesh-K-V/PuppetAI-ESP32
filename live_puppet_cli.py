import torch
import asyncio
import re
import json
import websockets
from transformers import AutoModelForCausalLM, AutoTokenizer

class LivePuppetCLI:
    # Actions the LLM classifier may return (whitelist - anything else
    # is rejected as hallucination and falls back to keywords/default)
    INTENT_ACTIONS = ["WAVE", "NAMASTE", "DANCE", "RAISE_L", "RAISE_R", "LOWER", "HOME"]

    def __init__(self):
        self.model_path = r"E:\puppet_ai\puppet_llm_final"
        self.dataset_path = r"E:\puppet_ai\puppet_dataset.jsonl"
        self.esp32_uri = "ws://192.168.4.1:81"
        self.device = "cuda"

        # ============================================================
        # AI MODE SWITCHES
        #   USE_GENERATION  : try to let the LLM COMPOSE a brand-new
        #                     motion sequence for unfamiliar commands.
        #                     NOTE: works poorly until you retrain with
        #                     build_generation_dataset.py merged into
        #                     puppet_dataset.jsonl (see that file).
        #   LOG_GENERATIONS : save every executed AI-generated sequence
        #                     to the training dataset
        # ============================================================
        self.USE_GENERATION = True
        self.LOG_GENERATIONS = True

        # ============================================================
        # MOTION BRICKS the generator may use (whitelist):
        #   UP:RH:<t> / DOWN:RH:<t>   right hand up / down pulse
        #   UP:LH:<t> / DOWN:LH:<t>   left hand up / down pulse
        #   WAG:RH:<t> / WAG:LH:<t>   hand wag (net movement = 0)
        #   SHL:<angle>               left shoulder angle 90-140 (positional)
        #   RSF:<t> / RSB:<t>         right shoulder fwd / back pulse
        #   PRAYER                    full namaste prayer-hands sequence
        #   WAIT:<t>                  pause
        #   HOME                      firmware home command
        # Safety: times clamped 0.1-2.0s, max 12 ops, missing DOWNs are
        # auto-inserted so the puppet ALWAYS returns home.
        # ============================================================
        self.MAX_OPS = 12
        self.MIN_T, self.MAX_T = 0.1, 2.0
        self.MIN_ANG, self.MAX_ANG = 90, 140

        # ============================================================
        # WAVE TUNING
        # ============================================================
        self.WAVE_RAISE_T = 0.9
        self.WAVE_WAGS = 3
        self.WAG_T = 0.22

        # ============================================================
        # NAMASTE (prayer hands) TUNING
        #   NAMASTE_SHOULDER_L : LEFT shoulder angle bringing the left palm
        #     CLOSEST to the right palm. 90 = home.
        #     HARDWARE-CALIBRATED: 110 moved the arm AWAY from the right
        #     hand on this puppet -> inward direction is BELOW 90 (70).
        #     Run calibrate_shoulder.py to fine-tune this number.
        #   If right shoulder moves backward, swap NAMASTE_RS_KEY "Q" <-> "W".
        # ============================================================
        self.NAMASTE_HANDS_T = 0.6
        self.NAMASTE_SHOULDER_L = 70
        self.NAMASTE_RS_KEY = "Q"
        self.NAMASTE_RS_T = 0.5
        self.NAMASTE_PRAYER_HOLD = 1.0

        # ============================================================
        # DANCE TUNING
        # ============================================================
        self.DANCE_HOLD = 1.5
        self.DANCE_PHASES = 4
        self.DANCE_SPEED = 25

        print("Loading fine-tuned TinyLlama model...")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype=torch.bfloat16,
            device_map=self.device
        )
        # Silence "Both max_new_tokens and max_length set" warning:
        # max_new_tokens always governs anyway.
        self.model.generation_config.max_length = None
        print("Model loaded successfully. Ready for advanced choreography!")

    # ================================================================
    # 1. INTENT CLASSIFIER (keyword fast path -> LLM -> default)
    # ================================================================
    def _keyword_intent(self, cmd):
        """Fast path: exact-word keyword match. Returns intent or None."""
        words = set(cmd.replace(",", " ").split())
        if words & {"wave", "hello", "hi", "hey", "bye", "bye!", "goodbye", "tata"}:
            return "WAVE"
        if "namaste" in cmd or words & {"prayer", "namaskar"}:
            return "NAMASTE"
        if "dance" in cmd or words & {"dancing", "bhangra"}:
            return "DANCE"
        if "lower" in cmd or "down" in cmd:
            return "LOWER"
        if words & {"home", "rest", "original", "position"}:
            return "HOME"
        if words & {"right"} and words & {"hand", "hand?", "arm", "up", "raise", "raise?", "lift"}:
            return "RAISE_R"
        if words & {"left", "raise", "lift", "arm", "hand"}:
            return "RAISE_L"
        return None

    def _llm_chat(self, prompt, max_new_tokens=6, do_sample=False):
        """Single helper for all LLM calls. Returns decoded continuation.
        Note: temperature is only valid when sampling, otherwise
        transformers logs 'generation flags not valid' noise."""
        inputs = self.tokenizer(prompt, return_tensors="pt",
                                add_special_tokens=False).to(self.device)
        kwargs = dict(max_new_tokens=max_new_tokens, do_sample=do_sample,
                      pad_token_id=self.tokenizer.eos_token_id)
        if do_sample:
            kwargs["temperature"] = 0.3
        outputs = self.model.generate(**inputs, **kwargs)
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)

    def _llm_intent(self, command_text):
        """LLM few-shot intent classification. Returns (intent|None, raw)."""
        examples = (
            "<s>[INST] say hello to the guests [/INST] WAVE </s>\n"
            "<s>[INST] greet them [/INST] WAVE </s>\n"
            "<s>[INST] do namaste [/INST] NAMASTE </s>\n"
            "<s>[INST] join your hands [/INST] NAMASTE </s>\n"
            "<s>[INST] dance opposite [/INST] DANCE </s>\n"
            "<s>[INST] perform bhangra [/INST] DANCE </s>\n"
            "<s>[INST] raise left hand [/INST] RAISE_L </s>\n"
            "<s>[INST] lift your right arm [/INST] RAISE_R </s>\n"
            "<s>[INST] lower your hands [/INST] LOWER </s>\n" \
            "<s>[INST] go to your rest position [/INST] HOME </s>\n"
        )
        prompt = examples + f"<s>[INST] {command_text} [/INST] "
        try:
            raw = self._llm_chat(prompt)
            tail = raw.split("[/INST]")[-1].strip().upper()
            for action in self.INTENT_ACTIONS:
                if action in tail:
                    return action, tail
            return None, tail
        except Exception as e:
            print(f"[LLM classifier error: {e}]")
            return None, ""

    def classify_intent(self, command_text):
        cmd = command_text.lower()
        intent = self._keyword_intent(cmd)
        if intent:
            return intent, "keyword"
        intent, raw = self._llm_intent(command_text)
        if intent:
            return intent, f"LLM (raw: {raw!r})"
        return "RAISE_L", "default"

    # ================================================================
    # 2. MOTION GENERATOR (LLM composes NEW sequences from bricks)
    # ================================================================
    def _clean_generation(self, text):
        """Strip chat-template artifacts the model likes to add
        (<|ASSISTANT|>, <|USER|>, <s>, </s>, and any new [INST] turn)."""
        text = re.sub(r"<\|[^>]*\|>", " ", text)      # <|ASSISTANT|> etc.
        text = text.replace("</s>", " ").replace("<s>", " ")
        text = text.split("[INST]")[0]                # model starts a new turn -> cut
        return text.strip()

    def _try_generate(self, context_text):
        """Ask the LLM to compose a sequence of motion bricks for this
        context. Returns a VALIDATED op list, or None (fallback)."""
        examples = (
            "<s>[INST] welcome the chief guest with respect [/INST] "
            "UP:RH:0.7 THEN WAG:RH:0.2 THEN WAG:RH:0.2 THEN DOWN:RH:0.7 THEN PRAYER THEN HOME </s>\n"
            "<s>[INST] celebrate the victory [/INST] "
            "UP:LH:0.8 THEN UP:RH:0.8 THEN WAIT:0.5 THEN DOWN:LH:0.8 THEN DOWN:RH:0.8 THEN HOME </s>\n"
            "<s>[INST] greet them the traditional way [/INST] PRAYER THEN HOME </s>\n"
            "<s>[INST] say bye bye to everyone [/INST] "
            "UP:RH:0.6 THEN WAG:RH:0.25 THEN WAG:RH:0.25 THEN DOWN:RH:0.6 THEN HOME </s>\n"
            "<s>[INST] point upward energetically [/INST] "
            "UP:RH:0.9 THEN WAIT:0.3 THEN DOWN:RH:0.9 THEN HOME </s>\n"
        )
        prompt = examples + f"<s>[INST] {context_text} [/INST] "
        try:
            raw = self._llm_chat(prompt, max_new_tokens=60, do_sample=True)
            tail = self._clean_generation(raw.split("[/INST]")[-1])
            return self._parse_sequence(tail)
        except Exception as e:
            print(f"[LLM generator error: {e}]")
            return None

    def _parse_sequence(self, text):
        """Strict validator/parser for generated sequences.
        Any unknown token -> whole sequence rejected (None).
        Returns safe op list or None."""
        ops = []
        net = {"RH": 0.0, "LH": 0.0}   # +up / -down travel per 360 hand

        for token in text.split("THEN"):
            token = token.strip().upper()
            if not token:
                continue

            m = re.fullmatch(r"(UP|DOWN):(RH|LH):(\d+(?:\.\d+)?)", token)
            if m:
                t = max(self.MIN_T, min(float(m.group(3)), self.MAX_T))
                limb = m.group(2)
                ops.append((m.group(1), limb, t))
                net[limb] += t if m.group(1) == "UP" else -t
                continue

            m = re.fullmatch(r"WAG:(RH|LH):(\d+(?:\.\d+)?)", token)
            if m:
                t = max(self.MIN_T, min(float(m.group(2)), self.MAX_T))
                ops.append(("WAG", m.group(1), t))   # net 0 by design
                continue

            m = re.fullmatch(r"SHL:(\d{2,3})", token)
            if m:
                ang = max(self.MIN_ANG, min(int(m.group(1)), self.MAX_ANG))
                ops.append(("SHL", ang))
                continue

            m = re.fullmatch(r"(RSF|RSB):(\d+(?:\.\d+)?)", token)
            if m:
                t = max(self.MIN_T, min(float(m.group(2)), self.MAX_T))
                ops.append((m.group(1), t))
                continue

            m = re.fullmatch(r"WAIT:(\d+(?:\.\d+)?)", token)
            if m:
                t = max(self.MIN_T, min(float(m.group(1)), self.MAX_T))
                ops.append(("WAIT", t))
                continue

            if token == "PRAYER":
                ops.append(("PRAYER",))
                continue

            if token == "HOME":
                ops.append(("HOME",))
                continue

            # ANY unknown token -> hallucination -> reject everything
            print(f"[Generator] Rejected: unknown token {token!r}")
            return None

        if not ops or len(ops) > self.MAX_OPS:
            return None

        # Remove a trailing HOME (if any) so balance pulses land before it
        had_home = bool(ops) and ops[-1][0] == "HOME"
        if had_home:
            ops.pop()

        # AUTO-BALANCE: append missing DOWN/UP pulses so every limb
        # returns where it started (+2% friction margin).
        for limb, n in net.items():
            if n > 0.01:
                ops.append(("DOWN", limb, min(n * 1.02, self.MAX_T)))
            elif n < -0.01:
                ops.append(("UP", limb, min(-n * 1.02, self.MAX_T)))

        ops.append(("HOME",))
        return ops

    @staticmethod
    def _op_str(op):
        return {"UP": lambda: f"UP:{op[1]}:{op[2]}",
                "DOWN": lambda: f"DOWN:{op[1]}:{op[2]}",
                "WAG": lambda: f"WAG:{op[1]}:{op[2]}",
                "SHL": lambda: f"SHOULDER_L:{op[1]}",
                "RSF": lambda: f"R-SHOULDER-FWD:{op[1]}s",
                "RSB": lambda: f"R-SHOULDER-BACK:{op[1]}s",
                "PRAYER": lambda: "PRAYER(namaste)",
                "WAIT": lambda: f"WAIT:{op[1]}s",
                "HOME": lambda: "HOME"}[op[0]]()

    @staticmethod
    def _dsl_str(op):
        """Convert an op tuple back to DSL text (for dataset logging)."""
        kind = op[0]
        if kind in ("UP", "DOWN", "WAG"):
            return f"{kind}:{op[1]}:{op[2]}"
        if kind in ("RSF", "RSB", "WAIT"):
            return f"{kind}:{op[1]}"
        if kind == "SHL":
            return f"SHL:{op[1]}"
        return kind   # PRAYER / HOME

    def _log_generation(self, context_text, ops):
        """Append a verified generation to the training dataset so the
        next fine-tune teaches the model what actually worked."""
        if not self.LOG_GENERATIONS:
            return
        try:
            dsl = " THEN ".join(self._dsl_str(o) for o in ops)
            entry = {"text": f"<s>[INST] {context_text} [/INST] {dsl} </s>"}
            with open(self.dataset_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            print(f"[DATASET UPDATED] Logged verified generation for: '{context_text}'")
        except Exception as e:
            print(f"[Dataset log skipped: {e}]")

    # ================================================================
    # 3. LOW-LEVEL MOTOR HELPERS
    # ================================================================
    async def _drive(self, ws, key, hold_time):
        """Drive ONE 360 servo for hold_time seconds."""
        await ws.send(f"KD:{key}")
        await asyncio.sleep(hold_time)
        await ws.send(f"KU:{key}")
        await asyncio.sleep(0.1)

    async def _drive_pair(self, ws, key_a, key_b, hold_time):
        """Drive two 360 servos simultaneously."""
        await ws.send(f"KD:{key_a}")
        await ws.send(f"KD:{key_b}")
        await asyncio.sleep(hold_time)
        await ws.send(f"KU:{key_a}")
        await ws.send(f"KU:{key_b}")
        await asyncio.sleep(0.2)

    async def _shoulder_left(self, ws, angle, settle=0.6):
        """Positional left shoulder (MG90S): absolute angle 0-180."""
        cmd = f"SHOULDER_L:{int(angle)}"
        await ws.send(cmd)
        print(f"-> {cmd}")
        await asyncio.sleep(settle)

    # ================================================================
    # 4. REUSABLE CHOREOGRAPHY BLOCKS
    # ================================================================
    async def _prayer_pose(self, ws):
        """Namaste = prayer hands: both hands up, both shoulders forward
        (palms come closer), hold, then fully return."""
        # 1. Both hands UP together (L = left up, S = right up)
        await self._drive_pair(ws, "L", "S", self.NAMASTE_HANDS_T)

        # 2. Shoulders move FORWARD so the palms come closer
        await self._shoulder_left(ws, self.NAMASTE_SHOULDER_L)
        reverse_key = "W" if self.NAMASTE_RS_KEY == "Q" else "Q"
        print(f"-> Right shoulder forward (KD:{self.NAMASTE_RS_KEY})")
        await self._drive(ws, self.NAMASTE_RS_KEY, self.NAMASTE_RS_T)

        # 3. Hold the prayer pose
        print(f"  Holding prayer pose for {self.NAMASTE_PRAYER_HOLD}s...")
        await asyncio.sleep(self.NAMASTE_PRAYER_HOLD)

        # 4. Active return, mirrored
        print("Returning right shoulder...")
        await self._drive(ws, reverse_key, self.NAMASTE_RS_T * 1.02)
        print("Returning left shoulder to home (90)...")
        await self._shoulder_left(ws, 90, settle=0.8)
        print("Lowering both hands back...")
        await self._drive_pair(ws, "K", "A", self.NAMASTE_HANDS_T * 1.02)

    async def _execute_sequence(self, ws, ops):
        """Execute a validated generated sequence."""
        for op in ops:
            kind = op[0]
            if kind == "UP":
                await self._drive(ws, "S" if op[1] == "RH" else "L", op[2])
            elif kind == "DOWN":
                await self._drive(ws, "A" if op[1] == "RH" else "K", op[2])
            elif kind == "WAG":
                down, up = ("A", "S") if op[1] == "RH" else ("K", "L")
                await self._drive(ws, down, op[2])
                await self._drive(ws, up, op[2])
            elif kind == "SHL":
                await self._shoulder_left(ws, op[1])
            elif kind == "RSF":
                await self._drive(ws, "Q", op[1])
            elif kind == "RSB":
                await self._drive(ws, "W", op[1])
            elif kind == "PRAYER":
                await self._prayer_pose(ws)
            elif kind == "WAIT":
                await asyncio.sleep(op[1])
            elif kind == "HOME":
                await ws.send("SET_HOME")
                await asyncio.sleep(0.8)

    # ================================================================
    # 5. SCRIPTED ROUTINES (polished, used directly or as fallback)
    # ================================================================
    async def execute_choreography(self, command_text, intent):
        try:
            async with websockets.connect(self.esp32_uri, ping_interval=None, ping_timeout=None) as ws:
                print("\n[ESP32] Connected.")
                await ws.send("SET_HOME")
                await asyncio.sleep(0.5)
                await ws.send("SPEED:25")
                await asyncio.sleep(0.5)

                if intent == "WAVE":
                    print("Executing Choreography: Wave Hi (right hand higher, wags, active return)...")
                    await self._drive(ws, "S", self.WAVE_RAISE_T)
                    for i in range(self.WAVE_WAGS):
                        print(f"  Wave wag {i + 1}/{self.WAVE_WAGS}")
                        await self._drive(ws, "A", self.WAG_T)
                        await self._drive(ws, "S", self.WAG_T)
                    print("Actively lowering right hand back...")
                    await self._drive(ws, "A", self.WAVE_RAISE_T * 1.02)
                    print("Returning to original home position...")
                    await ws.send("SET_HOME")
                    await asyncio.sleep(1.0)

                elif intent == "NAMASTE":
                    print("Executing Choreography: Namaste prayer pose (hands up, shoulders forward, palms closer, full return)...")
                    await self._prayer_pose(ws)
                    print("Returning to original home position...")
                    await ws.send("SET_HOME")
                    await asyncio.sleep(1.0)

                elif intent == "DANCE":
                    print(f"Executing LONG choreography: {self.DANCE_PHASES} phases x {self.DANCE_HOLD}s per stroke...")
                    if self.DANCE_SPEED != 25:
                        await ws.send(f"SPEED:{self.DANCE_SPEED}")
                        await asyncio.sleep(0.3)
                    for phase in range(self.DANCE_PHASES):
                        if phase % 2 == 0:
                            left_key, right_key = "L", "A"   # left down + right up
                        else:
                            left_key, right_key = "K", "S"   # left up + right down
                        print(f"  Dance phase {phase + 1}/{self.DANCE_PHASES}: driving for {self.DANCE_HOLD}s")
                        await self._drive_pair(ws, left_key, right_key, self.DANCE_HOLD)
                    print("Returning to original home position...")
                    await ws.send("SET_HOME")
                    await asyncio.sleep(0.5)

                elif intent == "HOME":
                    print("Going to rest/home position...")
                    await ws.send("SET_HOME")
                    await asyncio.sleep(1.0)

                elif intent == "RAISE_R":
                    print("Moving Right Hand UP and returning...")
                    await self._drive(ws, "S", 1.0)
                    await self._drive(ws, "A", 1.02)
                    await ws.send("SET_HOME")
                    await asyncio.sleep(0.5)

                elif intent == "LOWER":
                    print("Lowering all hands and resetting...")
                    await self._drive_pair(ws, "K", "A", 1.0)
                    await ws.send("SET_HOME")
                    await asyncio.sleep(0.5)

                else:   # RAISE_L - default
                    print("Moving Left Hand UP and returning...")
                    await self._drive(ws, "L", 1.0)
                    await self._drive(ws, "K", 1.02)
                    await ws.send("SET_HOME")
                    await asyncio.sleep(0.5)

                print("[ESP32] Routine completed and returned to original position.")
        except Exception as e:
            print(f"WebSocket Error: {e}")

    async def _run_generated(self, ops):
        """Connect and execute an AI-generated sequence."""
        try:
            async with websockets.connect(self.esp32_uri, ping_interval=None, ping_timeout=None) as ws:
                print("\n[ESP32] Connected.")
                await ws.send("SET_HOME")
                await asyncio.sleep(0.5)
                await ws.send("SPEED:25")
                await asyncio.sleep(0.5)

                print("Executing AI-GENERATED choreography:")
                print("   " + "  THEN  ".join(self._op_str(o) for o in ops))
                await self._execute_sequence(ws, ops)

                print("[ESP32] AI routine completed and returned to original position.")
        except Exception as e:
            print(f"WebSocket Error: {e}")

    # ================================================================
    # 6. MAIN LOOP
    # ================================================================
    def run(self):
        while True:
            cmd = input("\nEnter command (e.g., 'wave hi', 'do namaste', 'dance opposite', "
                        "'welcome the chief guest', 'go home') or 'exit': ").strip()
            if cmd.lower() == 'exit':
                break
            if not cmd:
                continue

            # 1. Keyword fast path -> polished scripted routines (0 latency)
            keyword_intent = self._keyword_intent(cmd.lower())

            # 2. Novel context + generation enabled -> let the LLM COMPOSE
            if keyword_intent is None and self.USE_GENERATION:
                ops = self._try_generate(cmd)
                if ops:
                    print("-> AI generated a new motion sequence from context!")
                    asyncio.run(self._run_generated(ops))
                    self._log_generation(cmd, ops)
                    continue
                print("-> Generation rejected/failed, using classified intent instead.")

            # 3. Classified intent -> scripted routine
            intent, source = self.classify_intent(cmd)
            print(f"-> Intent: {intent}  (via {source})")
            asyncio.run(self.execute_choreography(cmd, intent))

if __name__ == "__main__":
    cli = LivePuppetCLI()
    cli.run()
