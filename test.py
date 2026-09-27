import os
os.environ["HF_HOME"]            = "E:\\huggingface_cache"
os.environ["TRANSFORMERS_CACHE"] = "E:\\huggingface_cache"

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

MODEL_NAME  = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
FINAL_DIR   = "E:\\puppet_ai\\puppet_llm_final"

print("Loading model...")
tokenizer = AutoTokenizer.from_pretrained(FINAL_DIR)
base      = AutoModelForCausalLM.from_pretrained(MODEL_NAME, torch_dtype=torch.float16, device_map="auto")
model     = PeftModel.from_pretrained(base, FINAL_DIR)
model.eval()
print("Model ready!\n")

def ask(command):
    prompt = (
        f"<|system|>\n"
        f"You are a puppet motion controller. "
        f"Convert natural language commands into motion sequences.\n"
        f"</s>\n"
        f"<|user|>\n"
        f"{command}\n"
        f"</s>\n"
        f"<|assistant|>\n"
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens  = 80,
            temperature     = 0.2,
            do_sample       = True,
            pad_token_id    = tokenizer.eos_token_id,
            eos_token_id    = tokenizer.eos_token_id,
        )
    result = tokenizer.decode(out[0], skip_special_tokens=True)
    return result.split("<|assistant|>")[-1].strip()

# ── Test known commands ────────────────────────────────────────
print("=== Testing trained commands ===")
known = ["say hi", "do namaste", "bow down", "wave goodbye", "raise hands"]
for cmd in known:
    print(f"Input : {cmd}")
    print(f"Output: {ask(cmd)}")
    print()

# ── Test unseen commands ───────────────────────────────────────
print("=== Testing new unseen commands ===")
unseen = [
    "greet the audience",
    "say hello and bow",
    "perform a welcome gesture",
    "wave slowly",
]
for cmd in unseen:
    print(f"Input : {cmd}")
    print(f"Output: {ask(cmd)}")
    print()

# ── Interactive mode ──────────────────────────────────────────
print("=== Interactive Mode (type quit to exit) ===")
while True:
    cmd = input("Command: ").strip()
    if cmd.lower() in ["quit", "exit", "q"]:
        break
    if cmd:
        print(f"Motion : {ask(cmd)}\n")