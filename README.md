# PuppetAI-ESP32

An end-to-end AI controller for a 5-DOF string puppet. This project bridges a locally fine-tuned Large Language Model (TinyLlama 1.1B) with an ESP32 microcontroller, allowing the puppet to autonomously translate natural language commands into physical choreography.

## 🧠 System Architecture

The pipeline consists of two main stages:
1. **LLM Generation Engine:** A custom fine-tuned TinyLlama model classifies intents and generates verified hardware state strings using a custom Domain Specific Language (DSL). It features an auto-balancer to ensure the puppet always safely returns to absolute zero.
2. **Hardware Execution:** An ESP32 microcontroller running C++ firmware receives parsed motor commands via a low-latency WebSocket connection to actuate continuous rotation servos.

## 📂 Repository Structure

* `live_puppet_cli.py`: The core LLM classifier and generation engine. Handles intent parsing, auto-balancing motion bricks, and dispatching WebSocket commands to the ESP32.
* `train_puppet_llm.py` & `clean_dataset.py`: Scripts used to fine-tune TinyLlama via LoRA/PEFT on real-world, verified string tension and motor timing data.
* `string_puppt/`: PlatformIO project containing the C++ firmware for the ESP32 WebSocket server and servo control.
* `puppet_dataset.jsonl`: The self-expanding dataset of physical motion primitives. 

## 🛠️ Hardware Requirements

* ESP32 Development Board
* 5x 360° Continuous Rotation Servos (Mapped to Left/Right Arms, Shoulders, and Lift)
* CUDA-enabled PC for local LLM inference

## 🚀 Getting Started

### 1. Flash the ESP32
Open the `string_puppt/` folder with PlatformIO. Compile and upload the firmware to your ESP32. Ensure your PC is connected to the ESP32's network (default: `192.168.4.1`).

### 2. Setup the Python AI Environment
```bash
python -m venv puppet_env
puppet_env\Scripts\activate
pip install torch transformers trl peft datasets websockets
