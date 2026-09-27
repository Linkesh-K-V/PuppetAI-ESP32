# ================================================================
#  TinyLlama Fine-Tune Script — Puppet Motion Controller
#  Built by Aiko
# ================================================================

import os, sys
os.environ["HF_HOME"]            = "E:\\huggingface_cache"
os.environ["TRANSFORMERS_CACHE"] = "E:\\huggingface_cache"
os.environ["HF_DATASETS_CACHE"]  = "E:\\huggingface_cache\\datasets"

import torch
from transformers import (
    AutoTokenizer, AutoModelForCausalLM,
    BitsAndBytesConfig
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset

# ── Config ────────────────────────────────────────────────────
MODEL_NAME  = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
DATA_FILE   = "E:\\puppet_ai\\puppet_dataset.jsonl"
OUTPUT_DIR  = "E:\\puppet_ai\\puppet_llm"
FINAL_DIR   = "E:\\puppet_ai\\puppet_llm_final"
EPOCHS      = 15
BATCH_SIZE  = 4
LR          = 2e-4

print("=== Puppet LLM Training ===")
print(f"Model  : {MODEL_NAME}")
print(f"Data   : {DATA_FILE}")
print(f"Output : {FINAL_DIR}")
print(f"Epochs : {EPOCHS}")
print()

# ── GPU check ─────────────────────────────────────────────────
if torch.cuda.is_available():
    print(f"GPU  : {torch.cuda.get_device_name(0)}")
    print(f"VRAM : {torch.cuda.get_device_properties(0).total_memory/1e9:.1f} GB")
else:
    print("WARNING: No GPU — training will be very slow")
print()

# ── 4-bit quantization ────────────────────────────────────────
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,   # RTX 3050 Ti native format
    bnb_4bit_use_double_quant=True,
)

# ── Load model ────────────────────────────────────────────────
print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.pad_token    = tokenizer.eos_token
tokenizer.padding_side = "right"

print("Loading model in 4-bit...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    quantization_config=bnb_config,
    device_map="auto"
)
model = prepare_model_for_kbit_training(model)
print("Model loaded\n")

# ── LoRA ──────────────────────────────────────────────────────
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
print()

# ── Dataset ───────────────────────────────────────────────────
print("Loading dataset...")
dataset = load_dataset("json", data_files=DATA_FILE, split="train")
print(f"Examples: {len(dataset)}\n")

def format_prompt(example):
    return {
        "text": (
            f"<|system|>\n"
            f"You are a puppet motion controller. "
            f"Convert natural language commands into motion sequences.\n"
            f"</s>\n"
            f"<|user|>\n{example['input']}\n</s>\n"
            f"<|assistant|>\n{example['output']}\n</s>"
        )
    }

dataset = dataset.map(format_prompt)
print("Sample prompt:")
print(dataset[0]["text"])
print()

# ── Training ──────────────────────────────────────────────────
sft_config = SFTConfig(
    output_dir                  = OUTPUT_DIR,
    num_train_epochs            = EPOCHS,
    per_device_train_batch_size = BATCH_SIZE,
    gradient_accumulation_steps = 4,
    learning_rate               = LR,
    fp16                        = False,   # RTX 3050 Ti: use bf16 not fp16
    bf16                        = True,    # native bfloat16 support
    logging_steps               = 5,
    save_steps                  = 50,
    save_total_limit            = 2,
    warmup_steps                = 10,
    lr_scheduler_type           = "cosine",
    optim                       = "paged_adamw_8bit",
    report_to                   = "none",
)

trainer = SFTTrainer(
    model            = model,
    train_dataset    = dataset,
    processing_class = tokenizer,
    args             = sft_config,
)

print("Training started...")
print("Watch loss — should drop from ~2.5 to below 0.2\n")
trainer.train()

# ── Save ──────────────────────────────────────────────────────
model.save_pretrained(FINAL_DIR)
tokenizer.save_pretrained(FINAL_DIR)
print(f"\nTraining complete!")
print(f"Model saved to: {FINAL_DIR}")