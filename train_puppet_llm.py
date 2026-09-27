import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
)
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig

def train_puppet_model():
    # Paths
    model_id = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
    dataset_path = r"E:\puppet_ai\puppet_dataset.jsonl"
    output_dir = r"E:\puppet_ai\puppet_llm_final"

    print("Loading tokenizer and base model...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # Load model in bfloat16 for efficient training on your GPU
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=torch.bfloat16,          # 'torch_dtype' was renamed to 'dtype' (removes the deprecation warning)
        device_map="cuda"
    )

    # Configure PEFT / LoRA
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )

    # Load custom JSONL dataset
    print(f"Loading dataset from {dataset_path}...")
    dataset = load_dataset("json", data_files=dataset_path, split="train")

    # Safety net: drop rows with null/missing/empty 'text'
    # (TRL crashes with AttributeError: 'NoneType' object has no attribute 'endswith')
    before = len(dataset)
    dataset = dataset.filter(lambda x: isinstance(x.get("text"), str) and x["text"].strip() != "")
    if len(dataset) < before:
        print(f"Dropped {before - len(dataset)} corrupt row(s) with null/empty 'text'.")
        print("Run clean_dataset.py to see exactly which lines are bad.")

    # FIX: in TRL >= 0.20, 'dataset_text_field' is a SFTConfig parameter,
    # NOT an SFTTrainer.__init__() argument -> passing it to SFTTrainer
    # raises "TypeError: SFTTrainer.__init__() got an unexpected keyword
    # argument 'dataset_text_field'"
    training_args = SFTConfig(
        output_dir=output_dir,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        logging_steps=5,
        num_train_epochs=3,
        max_steps=-1,
        save_strategy="epoch",
        fp16=False,
        bf16=True,
        optim="paged_adamw_8bit",
        dataset_text_field="text",   # <--- moved here (was a SFTTrainer argument)
        max_length=1024,             # new name for the old 'max_seq_length'
        report_to="none",
    )

    # Initialize SFTTrainer - no dataset kwargs here anymore
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        processing_class=tokenizer,
        args=training_args,
    )

    print("Starting model fine-tuning...")
    trainer.train()

    print(f"Saving fine-tuned model to {output_dir}...")
    trainer.model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print("Training complete! TinyLlama is now specialized in puppet choreography.")

if __name__ == "__main__":
    train_puppet_model()
