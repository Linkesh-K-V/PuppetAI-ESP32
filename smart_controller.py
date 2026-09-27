import cv2
import numpy as np
import json
import asyncio
import websockets
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

class PuppetSmartController:
    def __init__(self):
        self.model_path = r"E:\puppet_ai\puppet_llm_final"
        self.dataset_path = r"E:\puppet_ai\puppet_dataset.jsonl"
        self.esp32_uri = "ws://192.168.4.1:81"
        
        self.state = {"LS": 90, "RS": 92, "LIFT": 92, "LH": 92, "RH": 92}
        
        self.lower_cyan = np.array([75, 100, 100])
        self.upper_cyan = np.array([130, 255, 255])
        
        print("Loading TinyLlama LLM...")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=torch.bfloat16,
            device_map="cuda"
        )
        print("LLM Loaded Successfully.")

    def generate_initial_motion(self, command_text):
        prompt = f"<|user|>\n{command_text}</s>\n<|assistant|>\n"
        inputs = self.tokenizer(prompt, return_tensors="pt", add_special_tokens=False).to("cuda")
        
        outputs = self.model.generate(
            **inputs, 
            max_new_tokens=80, 
            temperature=0.2, 
            do_sample=True
        )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=False)
        print(f"\n[DEBUG RAW OUTPUT] {response}")
        
        try:
            motion_str = response.split("<|assistant|>\n")[-1].replace("</s>", "").strip()
            if ":" not in motion_str or "<|user|>" in motion_str:
                print("LLM Hallucinated. Using default test motion.")
                motion_str = "LH:CW:400, RH:CW:400, LH:STOP, RH:STOP, WAIT:1000"
        except IndexError:
            motion_str = "LH:CW:400, RH:CW:400, LH:STOP, RH:STOP, WAIT:1000"
            
        print(f"LLM Generated Motion: {motion_str}")
        return motion_str
    
    async def pulse_360_servo(self, ws, servo, pull_up, short_pulse=False):
        """Sends KD/KU keypresses for either Left Hand (LH) or Right Hand (RH)"""
        key = ""
        if servo == "LH": 
            key = "L" if pull_up else "K" 
        elif servo == "RH": 
            key = "S" if pull_up else "A"
            
        if key:
            cmd_down = f"KD:{key}"
            cmd_up = f"KU:{key}"
            
            await ws.send(cmd_down)
            print(f"-> {cmd_down}")
            
            sleep_time = 0.3 if short_pulse else 1.0
            await asyncio.sleep(sleep_time) 
            
            await ws.send(cmd_up)
            print(f"-> {cmd_up}")
            await asyncio.sleep(0.5) 

    def update_dataset(self, command_text):
        motion_string = f"LS:{self.state['LS']}, RS:{self.state['RS']}, LIFT:{self.state['LIFT']}, LH:{self.state['LH']}, RH:{self.state['RH']}, WAIT:1000"
        entry = {"text": f"<s>[INST] {command_text} [/INST] {motion_string} </s>"}
        
        with open(self.dataset_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"\n[DATASET UPDATED] Saved verified dual-arm pose for: '{command_text}'")

    async def execute_dual_arm(self, command_text, target_y=180):
        initial_motion = self.generate_initial_motion(command_text)
        
        cap = None
        for index in [0, 1, 2]:
            temp_cap = cv2.VideoCapture(index) 
            if temp_cap.isOpened():
                ret, _ = temp_cap.read()
                if ret:
                    print(f"SUCCESS: Camera found and working at index {index}")
                    cap = temp_cap
                    break
            temp_cap.release()
            
        if cap is None:
            print("ERROR: Could not open any camera.")
            return
        
        try:
            async with websockets.connect(self.esp32_uri, ping_interval=None, ping_timeout=None) as ws:
                
                print("\nSending SET_HOME to unlock motors...")
                await ws.send("SET_HOME")
                await asyncio.sleep(1.0)
                
                print("Setting MAX SPEED to overcome motor inertia...")
                await ws.send("SPEED:25")
                await asyncio.sleep(1.0)
                
                print("Tracking both left and right cyan markers simultaneously...")
                safe_target_y = max(150, min(target_y, 300))
                left_reached = False
                right_reached = False
                
                while cap.isOpened() and not (left_reached and right_reached):
                    ret, frame = cap.read()
                    if not ret: break
                    
                    frame = cv2.flip(frame, 1)
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    mask = cv2.inRange(hsv, self.lower_cyan, self.upper_cyan)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    valid_contours = [c for c in contours if cv2.contourArea(c) > 150]
                    
                    if len(valid_contours) >= 2:
                        # Sort contours horizontally: Index 0 is Left-most, Index -1 is Right-most
                        valid_contours = sorted(valid_contours, key=lambda c: cv2.moments(c)["m10"] / (cv2.moments(c)["m00"] + 1e-5))
                        
                        left_contour = valid_contours[0]
                        right_contour = valid_contours[-1]
                        
                        # Process Left Hand
                        M_l = cv2.moments(left_contour)
                        if M_l["m00"] != 0 and not left_reached:
                            cx_l, cy_l = int(M_l["m10"] / M_l["m00"]), int(M_l["m01"] / M_l["m00"])
                            cv2.circle(frame, (cx_l, cy_l), 8, (0, 255, 255), -1)
                            cv2.putText(frame, f"LH Y: {cy_l}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                            
                            error_l = cy_l - safe_target_y
                            if cy_l >= 300:
                                left_reached = True
                            elif abs(error_l) > 20:
                                pull_up_l = True if cy_l > safe_target_y else False
                                await self.pulse_360_servo(ws, "LH", pull_up_l, short_pulse=abs(error_l) < 40)
                            else:
                                left_reached = True

                        # Process Right Hand
                        M_r = cv2.moments(right_contour)
                        if M_r["m00"] != 0 and not right_reached:
                            cx_r, cy_r = int(M_r["m10"] / M_r["m00"]), int(M_r["m01"] / M_r["m00"])
                            cv2.circle(frame, (cx_r, cy_r), 8, (255, 0, 255), -1)
                            cv2.putText(frame, f"RH Y: {cy_r}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
                            
                            error_r = cy_r - safe_target_y
                            if cy_r >= 300:
                                right_reached = True
                            elif abs(error_r) > 20:
                                pull_up_r = True if cy_r > safe_target_y else False
                                await self.pulse_360_servo(ws, "RH", pull_up_r, short_pulse=abs(error_r) < 40)
                            else:
                                right_reached = True

                    cv2.imshow('Dual-Arm Closed-Loop Vision', frame)
                    cv2.imshow('Cyan Mask', mask)
                    
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                    
                    await asyncio.sleep(0.05)

                if left_reached and right_reached:
                    print("\nDual-arm target pose verified successfully!")
                    self.update_dataset(command_text)

        except Exception as e:
            print(f"WebSocket Error: {e}")
        finally:
            cap.release()
            cv2.destroyAllWindows()

if __name__ == "__main__":
    controller = PuppetSmartController()
    
    asyncio.run(controller.execute_dual_arm(
        command_text="raise both hands", 
        target_y=180
    ))