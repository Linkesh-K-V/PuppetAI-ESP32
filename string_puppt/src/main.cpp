// ================================================================
//  ESP32 Animatronics Puppet Controller
//  Built by Aiko
// ================================================================
//  GPIO 18 -> Lift               (360° continuous rotation)
//  GPIO 19 -> Left Shoulder      (MG90S 180° positional)
//  GPIO 21 -> Right Shoulder     (360° continuous rotation)
//  GPIO 22 -> Hand Left          (360° continuous rotation)
//  GPIO 23 -> Hand Right         (360° continuous rotation)
// ================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <ArduinoOTA.h>
#include <ESP32Servo.h>

// ── WiFi AP ───────────────────────────────────────────────────
const char* AP_SSID = "ESP32_Puppet";
const char* AP_PASS = "12345678";

// ── 360° Continuous Rotation STOP values ─────────────────────
// Tune each ±1 until servo stands completely still when idle
#define STOP1  92   // Lift
#define STOP3  92   // Right Shoulder (360° continuous)
#define STOP4  92   // Hand Left
#define STOP5  92   // Hand Right

// ── Shoulder defaults ────────────────────────────────────────
#define LS_DEFAULT  90   // Left Shoulder center on power on

// ── Servers ───────────────────────────────────────────────────
WebServer        http(80);
WebSocketsServer ws(81);

// ── Servos ────────────────────────────────────────────────────
Servo lift, shoulderL, shoulderR, handL, handR;

// ── System ────────────────────────────────────────────────────
bool sysOn    = false;   // starts OFF — must set home first
bool homeSet  = false;   // blocks all movement until home is defined
int  spinSpeed = 15;     // 360° speed offset (1–25)
int  shStep    = 2;      // 180° shoulder degrees per tick (1–5)

// ── Home position storage ─────────────────────────────────────
// Left Shoulder (180°) home = saved angle
// Right Shoulder + Lift + Hands (360°) home = write STOP (strings hold rest)
int  homeLs = 90;   // Left Shoulder home angle

// ── Held keys ─────────────────────────────────────────────────
bool heldUP=false, heldDOWN=false;   // Lift
bool heldI=false,  heldO=false;      // Left Shoulder (180°)
bool heldQ=false,  heldW=false;      // Right Shoulder (360°)
bool heldK=false,  heldL=false;      // Hand Left
bool heldA=false,  heldS=false;      // Hand Right

// ── Left Shoulder position state (180° positional) ──────────
int lsPos = 90;   // Left Shoulder current angle

// ── Choreography ──────────────────────────────────────────────
#define NUM_SLOTS   5
#define MAX_FRAMES  600   // ~60 seconds at 10Hz capture rate

struct Frame { int p1,p2,p3,p4,p5; uint32_t ms; };

Frame    slots[NUM_SLOTS][MAX_FRAMES];
int      slotCount[NUM_SLOTS] = {0,0,0,0,0};
int      activeSlot = 0;
bool     recording  = false;
bool     playing    = false;
bool     looping    = false;
int      playIdx    = 0;
uint32_t recStart   = 0;
uint32_t playStart  = 0;

// ── Timers ────────────────────────────────────────────────────
uint32_t lastBroadcast = 0;
uint32_t lastMotion    = 0;   // 50Hz motion update
uint32_t lastCapture   = 0;   // 10Hz recording capture

// ── Forward declarations ──────────────────────────────────────
void stopAll();
void captureFrame();
void broadcastStatus();

// ── Stop all servos (hold position) ──────────────────────────
void stopAll() {
  lift.write(STOP1);
  shoulderL.write(lsPos);   // 180° — hold current angle
  shoulderR.write(STOP3);   // 360° — stop spinning immediately
  handL.write(STOP4);
  handR.write(STOP5);
}

// ── Go Home ────────────────────────────────────────────────────
// Both shoulders → write saved home angle directly (positional)
// Lift + Hands → write STOP (360° continuous — strings hold rest)
void goHome() {
  if (!homeSet) return;
  Serial.println("Going HOME...");

  // Left Shoulder — 180° positional, go to saved home angle
  lsPos = homeLs; shoulderL.write(lsPos);
  delay(600);

  // Right Shoulder + Lift + Hands — 360° continuous
  // Write STOP — strings hold the puppet at rest naturally
  shoulderR.write(STOP3);
  lift.write(STOP1);
  handL.write(STOP4);
  handR.write(STOP5);

  Serial.println("HOME done");
}

// ── Set Home ──────────────────────────────────────────────────
// Called when user presses SET HOME button
// Saves current puppet position as the reference home
void setHome() {
  homeLs  = lsPos;   // save left shoulder angle as home reference
  homeSet = true;
  sysOn   = true;    // enable system automatically
  Serial.print("Home set! LS angle="); Serial.println(homeLs);
  // Right shoulder (360°): current physical string position IS home
  // Writing STOP3 keeps it there — strings hold the rest position
}

// ── Capture frame for recording ───────────────────────────────
// Captures ALL states at 10Hz — including stopped states
// This ensures playback correctly replicates both moving and pausing
void captureFrame() {
  int n = slotCount[activeSlot];
  if (n >= MAX_FRAMES) return;

  // Record actual servo commands at this moment
  int p1 = STOP1, p3 = STOP3, p4 = STOP4, p5 = STOP5;
  if (heldUP)   p1 = STOP1 + spinSpeed;
  if (heldDOWN) p1 = STOP1 - spinSpeed;
  if (heldQ)    p3 = STOP3 + spinSpeed;
  if (heldW)    p3 = STOP3 - spinSpeed;
  if (heldK)    p4 = STOP4 + spinSpeed;
  if (heldL)    p4 = STOP4 - spinSpeed;
  if (heldA)    p5 = STOP5 + spinSpeed;
  if (heldS)    p5 = STOP5 - spinSpeed;

  // p2 = lsPos (LS angle), p3 = RS speed value
  slots[activeSlot][n] = { p1, lsPos, p3, p4, p5,
                            (uint32_t)(millis() - recStart) };
  slotCount[activeSlot]++;
}

// ── Apply motion every loop ───────────────────────────────────
void applyMotion() {
  if (!sysOn || !homeSet) { stopAll(); return; }

  // Lift — 360° continuous
  if      (heldUP)   lift.write(STOP1 + spinSpeed);
  else if (heldDOWN) lift.write(STOP1 - spinSpeed);
  else               lift.write(STOP1);

  // Left Shoulder — 180° positional
  if      (heldI) lsPos = constrain(lsPos + shStep, 0, 180);
  else if (heldO) lsPos = constrain(lsPos - shStep, 0, 180);
  shoulderL.write(lsPos);

  // Right Shoulder — 360° continuous (press=spin, release=stop)
  if      (heldQ) shoulderR.write(STOP3 + spinSpeed);
  else if (heldW) shoulderR.write(STOP3 - spinSpeed);
  else            shoulderR.write(STOP3);   // release = immediate stop

  // Hand Left — 360° continuous
  if      (heldK) handL.write(STOP4 + spinSpeed);
  else if (heldL) handL.write(STOP4 - spinSpeed);
  else            handL.write(STOP4);

  // Hand Right — 360° continuous
  if      (heldA) handR.write(STOP5 + spinSpeed);
  else if (heldS) handR.write(STOP5 - spinSpeed);
  else            handR.write(STOP5);

  // Record at 10Hz — captures ALL states (moving + stopped)
  if (recording && millis() - lastCapture >= 100) {
    lastCapture = millis();
    captureFrame();
  }
}

// ── Playback ──────────────────────────────────────────────────
void updatePlayback() {
  if (!playing || slotCount[activeSlot] == 0) return;
  int n = slotCount[activeSlot];
  uint32_t elapsed = millis() - playStart;

  while (playIdx < n-1 && slots[activeSlot][playIdx+1].ms <= elapsed)
    playIdx++;

  const Frame& f = slots[activeSlot][playIdx];
  lift.write(f.p1);
  lsPos = f.p2; shoulderL.write(lsPos);   // 180° — write angle
  shoulderR.write(f.p3);                   // 360° — write speed value
  handL.write(f.p4);
  handR.write(f.p5);

  if (playIdx >= n-1 && elapsed >= slots[activeSlot][n-1].ms) {
    if (looping) {
      // Loop: go back to home position first, then replay
      goHome();
      playIdx = 0; playStart = millis();
    } else {
      playing = false;
      goHome();   // return to home after playback ends
    }
    broadcastStatus();
  }
}

// ── Broadcast status ──────────────────────────────────────────
void broadcastStatus() {
  String j = "{\"type\":\"status\",";
  j += "\"on\":"        + String(sysOn     ?"true":"false") + ",";
  j += "\"homeSet\":"   + String(homeSet   ?"true":"false") + ",";
  j += "\"recording\":" + String(recording ?"true":"false") + ",";
  j += "\"playing\":"   + String(playing   ?"true":"false") + ",";
  j += "\"looping\":"   + String(looping   ?"true":"false") + ",";
  j += "\"slot\":"      + String(activeSlot) + ",";
  j += "\"speed\":"     + String(spinSpeed)  + ",";
  j += "\"lsPos\":"     + String(lsPos)      + ",";
  j += "\"homeLs\":"    + String(homeLs)     + ",";
  j += "\"frames\":[";
  for (int i=0;i<NUM_SLOTS;i++){
    j += String(slotCount[i]);
    if (i < NUM_SLOTS-1) j += ",";
  }
  j += "]}";
  ws.broadcastTXT(j);
}

// ── WebSocket handler ─────────────────────────────────────────
void onWsMessage(uint8_t num, WStype_t type, uint8_t* payload, size_t len) {
  if (type != WStype_TEXT) return;
  String msg = String((char*)payload);

  // ── SET HOME — must be handled even when sysOn=false ─────
  if (msg == "SET_HOME") {
    setHome();
    broadcastStatus();
    return;
  }

  // ── RESET HOME — clears home, blocks movement again ──────
  if (msg == "RESET_HOME") {
    homeSet = false;
    sysOn   = false;
    heldUP=heldDOWN=heldI=heldO=heldQ=heldW=heldK=heldL=heldA=heldS=false;
    recording = false; playing = false;
    stopAll();
    broadcastStatus();
    return;
  }

  // ── All other commands blocked until home is set ──────────
  if (!homeSet) return;

  if (msg.startsWith("KD:")) {
    String k = msg.substring(3);
    if      (k=="UP")    heldUP=true;
    else if (k=="DOWN")  heldDOWN=true;
    else if (k=="I")     heldI=true;
    else if (k=="O")     heldO=true;
    else if (k=="Q")     heldQ=true;
    else if (k=="W")     heldW=true;
    else if (k=="K")     heldK=true;
    else if (k=="L")     heldL=true;
    else if (k=="A")     heldA=true;
    else if (k=="S")     heldS=true;
    else if (k=="HOME")  { goHome(); broadcastStatus(); }
    else if (k=="SPACE") {
      heldUP=heldDOWN=heldI=heldO=heldQ=heldW=heldK=heldL=heldA=heldS=false;
      stopAll();
    }
    else if (k=="SHIFT") { sysOn=true;  broadcastStatus(); }
    else if (k=="CTRL")  {
      sysOn=false;
      heldUP=heldDOWN=heldI=heldO=heldQ=heldW=heldK=heldL=heldA=heldS=false;
      stopAll(); broadcastStatus();
    }
  }
  else if (msg.startsWith("KU:")) {
    String k = msg.substring(3);
    if      (k=="UP")   heldUP=false;
    else if (k=="DOWN") heldDOWN=false;
    else if (k=="I")    heldI=false;
    else if (k=="O")    heldO=false;
    else if (k=="Q")    heldQ=false;
    else if (k=="W")    heldW=false;
    else if (k=="K")    heldK=false;
    else if (k=="L")    heldL=false;
    else if (k=="A")    heldA=false;
    else if (k=="S")    heldS=false;
  }
  else if (msg.startsWith("SPEED:")) {
    int v = msg.substring(6).toInt();
    spinSpeed = map(v, 1, 100, 1, 25);
    shStep    = map(v, 1, 100, 1, 5);
    broadcastStatus();
  }
  else if (msg == "START") { sysOn=true;  broadcastStatus(); }
  else if (msg == "STOP")  {
    sysOn=false;
    heldUP=heldDOWN=heldI=heldO=heldQ=heldW=heldK=heldL=heldA=heldS=false;
    stopAll(); broadcastStatus();
  }
  else if (msg == "HOME") { goHome(); broadcastStatus(); }
  else if (msg.startsWith("SLOT:")) {
    activeSlot = constrain(msg.substring(5).toInt(), 0, NUM_SLOTS-1);
    broadcastStatus();
  }
  else if (msg == "REC_START") {
    if (!sysOn) return;
    slotCount[activeSlot] = 0;
    lastCapture = 0;
    recording = true; recStart = millis();
    broadcastStatus();
  }
  else if (msg == "REC_STOP")  { recording = false; broadcastStatus(); }
  else if (msg == "CLEAR") {
    recording = false; playing = false;
    slotCount[activeSlot] = 0; broadcastStatus();
  }
  else if (msg == "PLAY") {
    if (slotCount[activeSlot]==0 || !sysOn) return;
    goHome();   // always start playback from home position
    delay(800);
    playIdx=0; playStart=millis(); playing=true; broadcastStatus();
  }
  else if (msg == "PLAY_STOP")   { playing=false; stopAll(); broadcastStatus(); }
  else if (msg == "LOOP_TOGGLE") { looping=!looping; broadcastStatus(); }
  // Direct angle control from AI controller
  else if (msg.startsWith("SHOULDER_L:")) {
    lsPos = constrain(msg.substring(11).toInt(), 0, 180);
    shoulderL.write(lsPos);
    broadcastStatus();
  }

}

// ================================================================
//  HTML PAGE
// ================================================================
const char PAGE[] PROGMEM = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"/>
<title>Puppet Controller</title>
<style>
:root{
  --bg:#0d1117;--card:#161b22;--card2:#21262d;--border:#30363d;
  --accent:#58a6ff;--green:#3fb950;--red:#f85149;
  --yellow:#d29922;--purple:#bc8cff;--text:#e6edf3;--muted:#8b949e;
  --orange:#f0883e;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent;}
body{background:var(--bg);color:var(--text);
     font-family:'Segoe UI',Arial,sans-serif;padding:12px;}
h1{text-align:center;font-size:1.2rem;color:var(--accent);
   letter-spacing:2px;text-transform:uppercase;margin-bottom:2px;}
.sub{text-align:center;color:var(--muted);font-size:.75rem;margin-bottom:12px;}

/* Status bar */
.sbar{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-bottom:12px;}
.badge{padding:4px 11px;border-radius:20px;font-size:.73rem;font-weight:700;
       background:var(--card2);border:1px solid var(--border);}
.badge.on{background:#0d2a0d;border-color:var(--green);color:var(--green);}
.badge.off{background:#2a0d0d;border-color:var(--red);color:var(--red);}
.badge.rec{background:#2a1800;border-color:var(--yellow);color:var(--yellow);}
.badge.play{background:#0d1a2a;border-color:var(--accent);color:var(--accent);}
.badge.loop{background:#1a0d2a;border-color:var(--purple);color:var(--purple);}
.badge.home{background:#1a1000;border-color:var(--orange);color:var(--orange);}
.badge.homeset{background:#0d2a0d;border-color:var(--green);color:var(--green);}

/* Home required overlay */
#homeOverlay{
  position:fixed;top:0;left:0;right:0;bottom:0;
  background:rgba(13,17,23,0.97);
  z-index:1000;display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  padding:24px;text-align:center;
}
#homeOverlay.hidden{display:none;}
.overlay-icon{font-size:3rem;margin-bottom:16px;}
.overlay-title{font-size:1.4rem;font-weight:700;color:var(--orange);margin-bottom:10px;}
.overlay-desc{font-size:.9rem;color:var(--muted);margin-bottom:24px;max-width:320px;line-height:1.6;}
.overlay-steps{text-align:left;margin-bottom:28px;max-width:320px;}
.overlay-steps li{font-size:.85rem;color:var(--text);margin-bottom:8px;padding-left:8px;}
.btn-sethome{background:var(--orange);color:#000;border:none;border-radius:12px;
             padding:16px 40px;font-size:1.1rem;font-weight:700;cursor:pointer;
             touch-action:manipulation;width:100%;max-width:320px;}
.btn-sethome:active{transform:scale(.96);}

/* Cards */
.card{background:var(--card);border:1px solid var(--border);
      border-radius:12px;padding:12px;margin-bottom:10px;}
.card h2{font-size:.73rem;color:var(--muted);text-transform:uppercase;
         letter-spacing:1px;margin-bottom:10px;}

/* Buttons */
.row{display:flex;gap:7px;flex-wrap:wrap;justify-content:center;}
.btn{border:none;border-radius:9px;padding:11px 16px;font-size:.88rem;
     font-weight:700;cursor:pointer;transition:transform .1s;
     touch-action:manipulation;min-width:76px;user-select:none;}
.btn:active{transform:scale(.93);}
.btn-green{background:var(--green);color:#000;}
.btn-red{background:var(--red);color:#fff;}
.btn-blue{background:var(--accent);color:#000;}
.btn-yellow{background:var(--yellow);color:#000;}
.btn-purple{background:var(--purple);color:#000;}
.btn-orange{background:var(--orange);color:#000;}
.btn-gray{background:var(--card2);color:var(--text);border:1px solid var(--border);}
.btn-sm{padding:8px 11px;font-size:.8rem;min-width:54px;}

/* Speed */
.sprow{display:flex;align-items:center;gap:10px;}
.sprow input{flex:1;accent-color:var(--accent);}
.spval{min-width:38px;text-align:right;font-weight:700;color:var(--accent);font-size:.85rem;}

/* Live positions */
.pos-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px;}
.pos-card{background:var(--card2);border-radius:9px;padding:10px;text-align:center;}
.pos-label{font-size:.7rem;color:var(--muted);margin-bottom:4px;}
.pos-val{font-size:1rem;font-weight:700;color:var(--text);margin-bottom:5px;font-family:monospace;}
.pos-bar-bg{height:5px;background:var(--border);border-radius:3px;overflow:hidden;}
.pos-bar{height:5px;background:var(--accent);border-radius:3px;transition:width .2s;}
.pos-bar.green{background:var(--green);}
.pos-type{font-size:.62rem;color:var(--muted);margin-bottom:3px;}

/* D-pad */
.dpad-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:10px;}
.dpad-block{display:flex;flex-direction:column;align-items:center;gap:4px;}
.dpad-title{font-size:.68rem;color:var(--muted);text-align:center;line-height:1.3;}
.dpad{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;width:96px;}
.dbtn{border:none;border-radius:8px;width:28px;height:28px;font-size:1rem;
      cursor:pointer;background:var(--card2);color:var(--text);
      border:1px solid var(--border);display:flex;align-items:center;
      justify-content:center;touch-action:manipulation;user-select:none;}
.dbtn:active{background:var(--accent);color:#000;}
.dbtn.green:active{background:var(--green);color:#000;}
.dpad-mid{width:28px;height:28px;display:flex;align-items:center;
          justify-content:center;color:var(--muted);font-size:.65rem;text-align:center;}

/* Slot tabs */
.slots{display:flex;gap:5px;margin-bottom:10px;flex-wrap:wrap;}
.slot-btn{flex:1;padding:8px 4px;border:1px solid var(--border);
          border-radius:8px;background:var(--card2);color:var(--muted);
          font-size:.76rem;cursor:pointer;text-align:center;min-width:46px;}
.slot-btn.active{background:var(--accent);color:#000;border-color:var(--accent);font-weight:700;}
.slot-btn.has-data{border-color:var(--green);color:var(--green);}
.slot-btn.active.has-data{background:var(--green);color:#000;border-color:var(--green);}

/* Keyboard grid */
.kb{display:grid;grid-template-columns:repeat(auto-fill,minmax(116px,1fr));gap:5px;}
.kbi{background:var(--card2);border-radius:7px;padding:5px 8px;
     display:flex;align-items:center;gap:6px;}
.key{background:var(--bg);border:1px solid var(--border);border-radius:4px;
     padding:1px 6px;font-family:monospace;font-size:.8rem;
     color:var(--accent);min-width:26px;text-align:center;}
.kdesc{font-size:.72rem;color:var(--muted);}

/* OTA */
.ota-form{display:flex;flex-direction:column;gap:8px;}
.ota-form input[type=file]{background:var(--card2);border:1px solid var(--border);
  border-radius:8px;padding:8px;color:var(--text);font-size:.82rem;}

/* Disabled state */
.disabled-msg{text-align:center;color:var(--red);font-size:.8rem;
              padding:8px;background:#2a0d0d;border-radius:8px;margin-top:6px;}
</style>
</head>
<body>

<!-- ── HOME SETUP OVERLAY (shown until home is set) ── -->
<div id="homeOverlay">
  <div class="overlay-icon">&#127959;</div>
  <div class="overlay-title">Set Home Position First</div>
  <div class="overlay-desc">
    Before you can control the puppet, you must define its home position.
    This is the reference point for all movements and playback.
  </div>
  <ol class="overlay-steps">
    <li>&#9312; Manually position the puppet strings to the desired home/rest pose</li>
    <li>&#9313; Make sure all strings are at the correct natural tension</li>
    <li>&#9314; Press SET HOME POSITION below</li>
    <li>&#9315; All controls will unlock and movement can begin</li>
  </ol>
  <button class="btn-sethome" onclick="setHomePosition()">
    &#9654; SET HOME POSITION
  </button>
  <p style="font-size:.72rem;color:var(--muted);margin-top:14px;">
    WebSocket: <span id="wsStatusOverlay">Connecting...</span>
  </p>
</div>

<!-- ── MAIN CONTROLLER UI ── -->
<h1>&#127917; Puppet Controller</h1>
<p class="sub">ESP32 Animatronics &bull; Mixed Servo Mode</p>

<div class="sbar">
  <span class="badge off"   id="bSys">&#9899; System OFF</span>
  <span class="badge home"  id="bHome">&#8962; Home NOT SET</span>
  <span class="badge"       id="bRec">&#9899; Idle</span>
  <span class="badge"       id="bPlay">&#9724; Stopped</span>
  <span class="badge"       id="bLoop">&#8634; Loop OFF</span>
  <span class="badge"       id="bWs">&#9711; Connecting</span>
</div>

<!-- Home control card -->
<div class="card" style="border-color:var(--orange);">
  <h2 style="color:var(--orange);">&#8962; Home Position Control</h2>
  <div class="row">
    <button class="btn btn-orange btn-sm" onclick="setHomePosition()">&#9654; SET HOME</button>
    <button class="btn btn-yellow btn-sm" onclick="wsSend('HOME')">&#8635; GO HOME</button>
    <button class="btn btn-gray   btn-sm" onclick="resetHome()">&#9940; RESET HOME</button>
  </div>
  <p id="homeStatusMsg" style="text-align:center;font-size:.76rem;
     color:var(--orange);margin-top:8px;">
    Home not set — position puppet then press SET HOME
  </p>
</div>

<!-- System -->
<div class="card">
  <h2>System</h2>
  <div class="row">
    <button class="btn btn-green" onclick="wsSend('START')">&#9654; START</button>
    <button class="btn btn-red"   onclick="wsSend('STOP')">&#9632; STOP</button>
    <button class="btn btn-blue"  onclick="wsSend('KD:SPACE')">&#9724; STOP ALL</button>
  </div>
  <div id="sysBlock" class="disabled-msg" style="display:none;">
    Set home position first to enable controls
  </div>
</div>

<!-- Speed -->
<div class="card">
  <h2>&#9889; Speed</h2>
  <div class="sprow">
    <span style="font-size:.76rem;color:var(--muted)">Slow</span>
    <input type="range" min="1" max="100" value="25" id="spSlider"
      oninput="onSpeed(this.value)">
    <span style="font-size:.76rem;color:var(--muted)">Fast</span>
    <span class="spval" id="spVal">25%</span>
  </div>
</div>

<!-- Live positions -->
<div class="card">
  <h2>&#128202; Live Positions</h2>
  <div class="pos-grid">
    <div class="pos-card">
      <div class="pos-type">360° continuous</div>
      <div class="pos-label">Lift</div>
      <div class="pos-val" id="pLift">--</div>
      <div class="pos-bar-bg"><div class="pos-bar" id="bLift" style="width:50%"></div></div>
    </div>
    <div class="pos-card">
      <div class="pos-type">180° positional</div>
      <div class="pos-label">L. Shoulder</div>
      <div class="pos-val" id="pLS">90&#176;</div>
      <div class="pos-bar-bg"><div class="pos-bar green" id="bLS" style="width:50%"></div></div>
    </div>
    <div class="pos-card">
      <div class="pos-type">360° continuous</div>
      <div class="pos-label">R. Shoulder</div>
      <div class="pos-val" id="pRS">Idle</div>
      <div class="pos-bar-bg"><div class="pos-bar" id="bRS" style="width:50%"></div></div>
    </div>
    <div class="pos-card">
      <div class="pos-type">360° continuous</div>
      <div class="pos-label">Hand Left</div>
      <div class="pos-val" id="pHL">--</div>
      <div class="pos-bar-bg"><div class="pos-bar" id="bHL" style="width:50%"></div></div>
    </div>
    <div class="pos-card">
      <div class="pos-type">360° continuous</div>
      <div class="pos-label">Hand Right</div>
      <div class="pos-val" id="pHR">--</div>
      <div class="pos-bar-bg"><div class="pos-bar" id="bHR" style="width:50%"></div></div>
    </div>
  </div>
</div>

<!-- D-pad mobile control -->
<div class="card">
  <h2>&#127918; Mobile Control</h2>
  <div class="dpad-grid">

    <div class="dpad-block">
      <div class="dpad-title">Lift<br>
        <span style="color:var(--accent);font-size:.6rem;">360°</span></div>
      <div class="dpad">
        <div></div>
        <button class="dbtn"
          onmousedown="kd('UP')" onmouseup="ku('UP')" onmouseleave="ku('UP')"
          ontouchstart="kd('UP');event.preventDefault();"
          ontouchend="ku('UP')" ontouchcancel="ku('UP')">&#9650;</button>
        <div></div>
        <div></div><div class="dpad-mid">Lift</div><div></div>
        <div></div>
        <button class="dbtn"
          onmousedown="kd('DOWN')" onmouseup="ku('DOWN')" onmouseleave="ku('DOWN')"
          ontouchstart="kd('DOWN');event.preventDefault();"
          ontouchend="ku('DOWN')" ontouchcancel="ku('DOWN')">&#9660;</button>
        <div></div>
      </div>
    </div>

    <div class="dpad-block">
      <div class="dpad-title">L.Shoulder<br>
        <span style="color:var(--accent);font-size:.6rem;">360°</span></div>
      <div class="dpad">
        <div></div>
        <button class="dbtn green"
          onmousedown="kd('I')" onmouseup="ku('I')" onmouseleave="ku('I')"
          ontouchstart="kd('I');event.preventDefault();"
          ontouchend="ku('I')" ontouchcancel="ku('I')">&#9650;</button>
        <div></div>
        <div></div><div class="dpad-mid">L.Sh</div><div></div>
        <div></div>
        <button class="dbtn green"
          onmousedown="kd('O')" onmouseup="ku('O')" onmouseleave="ku('O')"
          ontouchstart="kd('O');event.preventDefault();"
          ontouchend="ku('O')" ontouchcancel="ku('O')">&#9660;</button>
        <div></div>
      </div>
    </div>

    <div class="dpad-block">
      <div class="dpad-title">R.Shoulder<br>
        <span style="color:var(--accent);font-size:.6rem;">360°</span></div>
      <div class="dpad">
        <div></div>
        <button class="dbtn"
          onmousedown="kd('Q')" onmouseup="ku('Q')" onmouseleave="ku('Q')"
          ontouchstart="kd('Q');event.preventDefault();"
          ontouchend="ku('Q')" ontouchcancel="ku('Q')">&#9650;</button>
        <div></div>
        <div></div><div class="dpad-mid">R.Sh</div><div></div>
        <div></div>
        <button class="dbtn"
          onmousedown="kd('W')" onmouseup="ku('W')" onmouseleave="ku('W')"
          ontouchstart="kd('W');event.preventDefault();"
          ontouchend="ku('W')" ontouchcancel="ku('W')">&#9660;</button>
        <div></div>
      </div>
    </div>

    <div class="dpad-block">
      <div class="dpad-title">Hand Left<br>
        <span style="color:var(--accent);font-size:.6rem;">360°</span></div>
      <div class="dpad">
        <div></div>
        <button class="dbtn"
          onmousedown="kd('K')" onmouseup="ku('K')" onmouseleave="ku('K')"
          ontouchstart="kd('K');event.preventDefault();"
          ontouchend="ku('K')" ontouchcancel="ku('K')">&#9650;</button>
        <div></div>
        <div></div><div class="dpad-mid">H.L</div><div></div>
        <div></div>
        <button class="dbtn"
          onmousedown="kd('L')" onmouseup="ku('L')" onmouseleave="ku('L')"
          ontouchstart="kd('L');event.preventDefault();"
          ontouchend="ku('L')" ontouchcancel="ku('L')">&#9660;</button>
        <div></div>
      </div>
    </div>

    <div class="dpad-block">
      <div class="dpad-title">Hand Right<br>
        <span style="color:var(--accent);font-size:.6rem;">360°</span></div>
      <div class="dpad">
        <div></div>
        <button class="dbtn"
          onmousedown="kd('A')" onmouseup="ku('A')" onmouseleave="ku('A')"
          ontouchstart="kd('A');event.preventDefault();"
          ontouchend="ku('A')" ontouchcancel="ku('A')">&#9650;</button>
        <div></div>
        <div></div><div class="dpad-mid">H.R</div><div></div>
        <div></div>
        <button class="dbtn"
          onmousedown="kd('S')" onmouseup="ku('S')" onmouseleave="ku('S')"
          ontouchstart="kd('S');event.preventDefault();"
          ontouchend="ku('S')" ontouchcancel="ku('S')">&#9660;</button>
        <div></div>
      </div>
    </div>

  </div>
</div>

<!-- Choreography -->
<div class="card">
  <h2>&#127909; Choreography</h2>
  <p style="font-size:.72rem;color:var(--muted);margin-bottom:8px;">
    Playback always starts from HOME position for consistency.
  </p>
  <div class="slots">
    <div class="slot-btn active" onclick="selectSlot(0)" id="slot0">Slot 1<br><small id="sf0">0fr</small></div>
    <div class="slot-btn"        onclick="selectSlot(1)" id="slot1">Slot 2<br><small id="sf1">0fr</small></div>
    <div class="slot-btn"        onclick="selectSlot(2)" id="slot2">Slot 3<br><small id="sf2">0fr</small></div>
    <div class="slot-btn"        onclick="selectSlot(3)" id="slot3">Slot 4<br><small id="sf3">0fr</small></div>
    <div class="slot-btn"        onclick="selectSlot(4)" id="slot4">Slot 5<br><small id="sf4">0fr</small></div>
  </div>
  <div class="row">
    <button class="btn btn-red    btn-sm" onclick="wsSend('REC_START')">&#9210; REC</button>
    <button class="btn btn-yellow btn-sm" onclick="wsSend('REC_STOP')">&#9632; STOP</button>
    <button class="btn btn-green  btn-sm" onclick="wsSend('PLAY')">&#9654; PLAY</button>
    <button class="btn btn-purple btn-sm" onclick="wsSend('LOOP_TOGGLE')">&#8634; LOOP</button>
    <button class="btn btn-gray   btn-sm" onclick="wsSend('PLAY_STOP')">&#9646;&#9646; PAUSE</button>
    <button class="btn btn-gray   btn-sm" onclick="wsSend('CLEAR')">CLR</button>
  </div>
  <p id="chorMsg" style="text-align:center;font-size:.76rem;color:var(--muted);margin-top:8px;">
    Select slot &rarr; REC &rarr; operate puppet &rarr; STOP &rarr; PLAY
  </p>
</div>

<!-- Keyboard reference -->
<div class="card">
  <h2>Keyboard</h2>
  <div class="kb">
    <div class="kbi"><span class="key">Up/Dn</span><span class="kdesc">Lift (360°)</span></div>
    <div class="kbi"><span class="key">I/O</span><span class="kdesc">L.Sh (180°)</span></div>
    <div class="kbi"><span class="key">Q/W</span><span class="kdesc">R.Sh (360°)</span></div>
    <div class="kbi"><span class="key">K/L</span><span class="kdesc">Hand Left</span></div>
    <div class="kbi"><span class="key">A/S</span><span class="kdesc">Hand Right</span></div>
    <div class="kbi"><span class="key">H</span><span class="kdesc">Go Home</span></div>
    <div class="kbi"><span class="key">Space</span><span class="kdesc">Stop all</span></div>
    <div class="kbi"><span class="key">Shift</span><span class="kdesc">Start sys</span></div>
    <div class="kbi"><span class="key">Ctrl</span><span class="kdesc">Stop sys</span></div>
  </div>
</div>

<!-- OTA update -->
<div class="card">
  <h2>OTA Firmware Update</h2>
  <div class="ota-form">
    <input type="file" id="otaFile" accept=".bin"/>
    <button class="btn btn-gray" onclick="otaUpload()">Upload Firmware</button>
  </div>
  <p id="otaMsg" style="text-align:center;font-size:.78rem;color:var(--muted);margin-top:6px;">
    Select firmware.bin from .pio/build/esp32dev/
  </p>
  <div style="height:6px;background:var(--border);border-radius:3px;margin-top:6px;overflow:hidden;">
    <div id="otaFill" style="height:6px;background:var(--accent);width:0%;transition:width .3s;"></div>
  </div>
</div>

<script>
var ws;
var isHomeSet = false;

function connectWS() {
  ws = new WebSocket('ws://' + location.hostname + ':81');
  ws.onopen  = function(){
    setBadge('bWs','Connected','on');
    document.getElementById('wsStatusOverlay').textContent = 'Connected';
  };
  ws.onclose = function(){
    setBadge('bWs','Disconnected','off');
    document.getElementById('wsStatusOverlay').textContent = 'Disconnected';
    setTimeout(connectWS, 2000);
  };
  ws.onerror = function(){ ws.close(); };
  ws.onmessage = function(e) {
    try { handleStatus(JSON.parse(e.data)); } catch(ex){}
  };
}
connectWS();

function wsSend(msg) {
  if (ws && ws.readyState===1) ws.send(msg);
}
function kd(k) { wsSend('KD:' + k); }
function ku(k) { wsSend('KU:' + k); }

// ── Set Home ─────────────────────────────────────────────────
function setHomePosition() {
  wsSend('SET_HOME');
  document.getElementById('homeStatusMsg').textContent =
    'Home position saved! Controls are now unlocked.';
  document.getElementById('homeStatusMsg').style.color = 'var(--green)';
}

function resetHome() {
  if (!confirm('Reset home? This will lock all controls until home is set again.')) return;
  wsSend('RESET_HOME');
}

// ── Status handler ────────────────────────────────────────────
function handleStatus(d) {
  if (d.type !== 'status') return;

  isHomeSet = d.homeSet;

  // Show/hide overlay
  document.getElementById('homeOverlay').className = d.homeSet ? 'hidden' : '';

  // Update home badge
  if (d.homeSet) {
    setBadge('bHome', '\u2962 Home SET', 'homeset');
    document.getElementById('homeStatusMsg').textContent =
      'Home set \u2014 L.Shoulder: ' + d.homeLs + '\u00b0 \u2014 press GO HOME to return';
    document.getElementById('homeStatusMsg').style.color = 'var(--green)';
    document.getElementById('sysBlock').style.display = 'none';
  } else {
    setBadge('bHome', '\u2962 Home NOT SET', 'home');
    document.getElementById('sysBlock').style.display = 'block';
  }

  setBadge('bSys',  d.on        ? 'System ON'  : 'System OFF', d.on?'on':'off');
  setBadge('bRec',  d.recording ? 'RECORDING'  : 'Idle',       d.recording?'rec':'');
  setBadge('bPlay', d.playing   ? 'PLAYING'    : 'Stopped',    d.playing?'play':'');
  setBadge('bLoop', d.looping   ? 'Loop ON'    : 'Loop OFF',   d.looping?'loop':'');

  // Both shoulders — show exact angle (both 180° positional)
  if (d.lsPos !== undefined) {
    document.getElementById('pLS').textContent = d.lsPos + '\u00b0';
    document.getElementById('bLS').style.width = (d.lsPos/180*100) + '%';
  }
  // 360° servos (RS, Lift, Hands) — show direction status
  var st = !d.homeSet ? 'LOCKED' : (d.on ? 'Idle' : 'STOP');
  document.getElementById('pLift').textContent = st;
  document.getElementById('pRS').textContent   = st;
  document.getElementById('pHL').textContent   = st;
  document.getElementById('pHR').textContent   = st;
  document.getElementById('bRS').style.width   = '50%';

  // Slot buttons
  for (var i=0;i<5;i++) {
    var btn = document.getElementById('slot'+i);
    var fr  = document.getElementById('sf'+i);
    fr.textContent = d.frames[i] + 'fr';
    btn.className  = 'slot-btn'
      + (i===d.slot    ? ' active'   : '')
      + (d.frames[i]>0 ? ' has-data' : '');
  }

  // Choreo msg
  var cm = document.getElementById('chorMsg');
  if (!d.homeSet) {
    cm.textContent = 'Set home position first';
  } else if (d.recording) {
    var used = d.frames[d.slot];
    cm.textContent = 'Recording slot ' + (d.slot+1) + ' — ' + used + '/600 frames';
  } else if (d.playing) {
    cm.textContent = 'Playing slot ' + (d.slot+1) + (d.looping?' (loop)':'');
  } else {
    cm.textContent = 'Select slot \u2192 REC \u2192 operate puppet \u2192 STOP \u2192 PLAY';
  }
}

function setBadge(id, text, cls) {
  var el = document.getElementById(id);
  el.textContent = text;
  el.className = 'badge ' + (cls||'');
}

function onSpeed(v) {
  document.getElementById('spVal').textContent = v + '%';
  wsSend('SPEED:' + v);
}

function selectSlot(n) { wsSend('SLOT:' + n); }

// Safety: release all held keys when window loses focus
window.addEventListener('blur', function() {
  ['UP','DOWN','I','O','Q','W','K','L','A','S'].forEach(function(k){
    wsSend('KU:' + k);
  });
});

// Keyboard control
var km = {
  'ArrowUp':'UP','ArrowDown':'DOWN',
  'q':'Q','Q':'Q','w':'W','W':'W',
  'i':'I','I':'I','o':'O','O':'O',
  'k':'K','K':'K','l':'L','L':'L',
  'a':'A','A':'A','s':'S','S':'S',
  'h':'HOME','H':'HOME',
  ' ':'SPACE','Shift':'SHIFT','Control':'CTRL'
};
document.addEventListener('keydown', function(e) {
  if (e.key==='ArrowUp'||e.key==='ArrowDown'||e.key===' ') e.preventDefault();
  if (e.repeat) return;
  var k = km[e.key]; if(k) wsSend('KD:'+k);
});
document.addEventListener('keyup', function(e) {
  var k = km[e.key]; if(k) wsSend('KU:'+k);
});

// OTA
function otaUpload() {
  var file = document.getElementById('otaFile').files[0];
  if (!file) { document.getElementById('otaMsg').textContent='Select a .bin file first'; return; }
  var form = new FormData();
  form.append('file', file, file.name);
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/ota');
  xhr.upload.onprogress = function(e) {
    var pct = Math.round(e.loaded/e.total*100);
    document.getElementById('otaFill').style.width = pct + '%';
    document.getElementById('otaMsg').textContent = 'Uploading: ' + pct + '%';
  };
  xhr.onload = function() {
    document.getElementById('otaMsg').textContent =
      xhr.status===200 ? 'Upload complete! ESP32 restarting...' : 'Upload failed';
  };
  xhr.onerror = function() {
    document.getElementById('otaMsg').textContent = 'Connection error';
  };
  xhr.send(form);
}
</script>
</body>
</html>)HTML";

// ── HTTP handlers ─────────────────────────────────────────────
void handleRoot() { http.send_P(200, "text/html", PAGE); }

void handleOTA() {
  HTTPUpload& upload = http.upload();
  if (upload.status == UPLOAD_FILE_START) {
    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) Update.printError(Serial);
  } else if (upload.status == UPLOAD_FILE_WRITE) {
    if (Update.write(upload.buf, upload.currentSize) != upload.currentSize)
      Update.printError(Serial);
  } else if (upload.status == UPLOAD_FILE_END) {
    if (Update.end(true)) {
      http.send(200, "text/plain", "OK");
      delay(300); ESP.restart();
    } else {
      Update.printError(Serial);
      http.send(500, "text/plain", "FAIL");
    }
  }
}

// ── Setup ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println("\n=== Puppet Controller ===");
  Serial.println("  Waiting for home position to be set...");

  lift.attach(18);
  shoulderL.attach(19);
  shoulderR.attach(21);
  handL.attach(22);
  handR.attach(23);

  lsPos = 90;
  stopAll();
  delay(300);

  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("AP IP: "); Serial.println(WiFi.softAPIP());

  http.on("/",    HTTP_GET,  handleRoot);
  http.on("/ota", HTTP_POST, [](){ }, handleOTA);
  http.begin();

  ws.begin();
  ws.onEvent([](uint8_t n, WStype_t t, uint8_t* p, size_t l){
    if (t == WStype_DISCONNECTED) {
      heldUP=heldDOWN=heldI=heldO=heldQ=heldW=heldK=heldL=heldA=heldS=false;
      if (homeSet) stopAll();
    } else if (t == WStype_TEXT) {
      onWsMessage(n, t, p, l);
    }
  });

  ArduinoOTA.setHostname("esp32-puppet");
  ArduinoOTA.setPassword("puppet123");
  ArduinoOTA.begin();

  Serial.println("Ready: http://192.168.4.1");
}

// ── Loop ──────────────────────────────────────────────────────
void loop() {
  ArduinoOTA.handle();
  http.handleClient();
  ws.loop();

  // Motion runs at 50Hz
  if (millis() - lastMotion >= 20) {
    lastMotion = millis();
    if (homeSet) {
      if (playing) updatePlayback();
      else         applyMotion();
    }
  }

  // Status broadcast every 200ms
  if (millis() - lastBroadcast > 200) {
    lastBroadcast = millis();
    broadcastStatus();
  }
}