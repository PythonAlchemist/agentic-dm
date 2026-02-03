from transformers import AutoModelForCausalLM, AutoTokenizer

model_path = "Zhengyi/LLaMA-Mesh"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForCausalLM.from_pretrained(model_path, device_map="auto")

prompt = "Create a 3D model of a female elf wizard with long silver hair, wearing a flowing blue robe adorned with intricate silver patterns, holding a wooden staff topped with a glowing crystal orb."

inputs = tokenizer(prompt, return_tensors="pt").to("mps")
model.eval()
