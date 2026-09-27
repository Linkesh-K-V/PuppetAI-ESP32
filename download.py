import os
os.environ["HF_HOME"]            = "E:\\huggingface_cache"
os.environ["TRANSFORMERS_CACHE"] = "E:\\huggingface_cache"

from transformers import AutoTokenizer, AutoModelForCausalLM

print("Downloading TinyLlama — about 2.2GB...")

model_name = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

tokenizer = AutoTokenizer.from_pretrained(model_name)
model     = AutoModelForCausalLM.from_pretrained(model_name)

print("Download complete!")
print(f"Total parameters: {model.num_parameters():,}")
print(f"Saved to: E:\\huggingface_cache")