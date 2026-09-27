import asyncio
import websockets

async def diagnostic_test(uri="ws://192.168.4.1:81"):
    try:
        async with websockets.connect(uri, ping_interval=None, ping_timeout=None) as ws:
            print("Connected to ESP32 WebSocket.")
            
            # 1. Unlock the safety system
            print("\n1. Sending SET_HOME to unlock motors...")
            await ws.send("SET_HOME")
            await asyncio.sleep(1)

            # 2. Maximize torque
            print("2. Setting MAX SPEED to overcome motor inertia...")
            await ws.send("SPEED:25")
            await asyncio.sleep(1)

            # --- TEST 1: LEFT SHOULDER (Positional) ---
            print("\n--- TEST 1: LEFT SHOULDER (Positional MG90S) ---")
            print("Moving Left Shoulder to 130 degrees...")
            await ws.send("SHOULDER_L:130")
            await asyncio.sleep(2)
            print("Moving Left Shoulder back to 90 degrees...")
            await ws.send("SHOULDER_L:90")
            await asyncio.sleep(2)

            # --- TEST 2: RIGHT SHOULDER (360) ---
            print("\n--- TEST 2: RIGHT SHOULDER (360 Continuous) ---")
            print("Commanding RS CW (KD:Q) for 1 second...")
            await ws.send("KD:Q")
            await asyncio.sleep(1)
            await ws.send("KU:Q")
            await asyncio.sleep(2)

            print("Commanding RS CCW (KD:W) for 1 second...")
            await ws.send("KD:W")
            await asyncio.sleep(1)
            await ws.send("KU:W")
            await asyncio.sleep(2)

            # --- TEST 3: HAND LEFT (360) ---
            print("\n--- TEST 3: HAND LEFT (360 Continuous) ---")
            print("Commanding HL CW (KD:K) for 1 second...")
            await ws.send("KD:K")
            await asyncio.sleep(1)
            await ws.send("KU:K")
            await asyncio.sleep(2)

            print("Commanding HL CCW (KD:L) for 1 second...")
            await ws.send("KD:L")
            await asyncio.sleep(1)
            await ws.send("KU:L")
            await asyncio.sleep(2)

            # --- TEST 4: HAND RIGHT (360) ---
            print("\n--- TEST 4: HAND RIGHT (360 Continuous) ---")
            print("Commanding HR CW (KD:A) for 1 second...")
            await ws.send("KD:A")
            await asyncio.sleep(1)
            await ws.send("KU:A")
            await asyncio.sleep(2)

            print("Commanding HR CCW (KD:S) for 1 second...")
            await ws.send("KD:S")
            await asyncio.sleep(1)
            await ws.send("KU:S")
            await asyncio.sleep(2)

            # --- TEST 5: LIFT (360) ---
            print("\n--- TEST 5: LIFT / BODY (360 Continuous) ---")
            print("Commanding LIFT UP (KD:UP) for 1 second...")
            await ws.send("KD:UP")
            await asyncio.sleep(1)
            await ws.send("KU:UP")
            await asyncio.sleep(2)
            
            print("Commanding LIFT DOWN (KD:DOWN) for 1 second...")
            await ws.send("KD:DOWN")
            await asyncio.sleep(1)
            await ws.send("KU:DOWN")
            
            print("\n--- DIAGNOSTIC COMPLETE ---")

    except Exception as e:
        print(f"Diagnostic Failed: {e}")

if __name__ == "__main__":
    asyncio.run(diagnostic_test())