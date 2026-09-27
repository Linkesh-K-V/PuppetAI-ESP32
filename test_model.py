import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

def test_fine_tuned_model():
    model_path = r"E:\puppet_ai\puppet_llm_final"
    
    print("Loading fine-tuned model and tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        device_map="cuda"
    )
    
    # Few-shot context anchors the model into the correct output format
    system_context = (
        "<|user|>\nraise left hand</s>\n<|assistant|>\n"
        "LS:90, RS:92, LIFT:92, LH:180, RH:92, WAIT:1000 </s>\n"
    )
    
    commands = [
        "raise left hand",
        "raise right hand",
        "raise both hands"
    ]
    
    for cmd in commands:
        prompt = system_context + f"<|user|>\n{cmd}</s>\n<|assistant|>\n"
        inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")
        
        outputs = model.generate(
            **inputs, 
            max_new_tokens=40, 
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id
        )
        
        response = tokenizer.decode(outputs[0], skip_special_tokens=False)
        # Extract just the assistant's latest response
        final_output = response.split("<|assistant|>")[-1].strip()
        print(f"\nPrompt: '{cmd}'")
        print(f"Generated Output:\n{final_output}")

if __name__ == "__main__":
    test_fine_tuned_model()