# CSIV Interactive Demo

A small sandbox that visualizes **Cell Selection Integrity Verification (CSIV)** concepts from the technical specification using a top‑down “city block” scene. You drive a UE (the blue car) around and watch nearby towers transition between **CLEAN → SUSPECT → BARRED → PROBATION** based on CSIV checks, a decaying suspicion score, and a few immediate‑bar rules.


---

## Requirements

- Python **3.8+**
- `pygame` (SDL-based game library)


---

## Quick start

### 1) (Optional) Create a virtual environment

**macOS/Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
```

**Windows (PowerShell)**
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel
```

### 2) Install dependencies
```bash
pip install pygame
```

### 3) Run
```bash
python3 csiv_demo.py
```
If you toggle fullscreen and want to return to windowed, press **F** or **F11** again. fileciteturn0file0

---

## Controls

- **Arrow keys** - move the UE (your car)
- **R** - flip the nearest tower between **clean** and **rogue identity**
- **L** - snapshot tower states to a log panel; press again to hide
- **C** - clear the log buffer
- **M** - toggle the menu (shows current weights/thresholds)
- **H** - show/hide the help overlay
- **Y** - toggle SIB display overlay
- **T** - toggle SIB generation (more expensive)
- **F / F11** - fullscreen
- **1/2, 3/4, 5/6** - adjust weights for dVer/pVer/spVer
- **7/8, 9/0** - adjust thresholds for suspect/barred
- **Q/A** - adjust combo‑boost for “dup+priority” escalation
- **ESC** - double‑press to exit; single press toggles menu

---

## What you’re seeing (CSIV mapping)

- **States & colors**:  
  - CLEAN (light blue), SUSPECT (amber), BARRED (red), PROBATION (green). A short fade blends SUSPECT→BARRED so you can see the transition.  
- **Suspicion score `S` with decay**:  
  Each tick, `S` decays with a half‑life (default **5 s**) then adds weighted deviations from checks such as **duplicate identity (dVer)**, **priority anomaly (pVer)**, and **signal‑power deviation (spVer)**. 
- **Thresholds & weights (tunable in the menu keys above)**:  
  `THETA_SUSPECT = 0.5`, `THETA_BARRED = 1.0`, `W_DVER = 1.5`, `W_PVER = 1.0`, `W_SPVER = 1.0` (defaults in this build). 
- **Immediate‑bar example**:  
  *Duplicate identity + no neighbors advertised* ⇒ instant **BARRED** (models a rogue with spoofed ID and no proper neighbor graph).
- **Vicinity gating**:  
  Towers outside a radius (**~250 units**) are treated as out‑of‑vicinity and snap back to CLEAN with score reset (reduces noise from far towers).  
- **SIB overlay & generation**:  
  Press **Y** to view SIB summaries; press **T** to generate active SIB traffic (periodic messages with TAC, priority, barring flags, RA config, etc.). 

These mechanics are a lightweight visualization of the spec’s **Verification Conditions (VCs)**, weighted **Verification Algorithm (VA)** with decay, and the **Clean/Suspect/Barred/Probation** state machine. See the spec for the full definitions and policy choices (e.g., immediate‑bar combinations, barred backoff, probation). 

---

## Troubleshooting

- **“Failed to create display”** at start: ensure you’re not on a headless session or missing SDL; try installing OS packages (e.g., on Debian/Ubuntu `sudo apt install python3-pygame` or SDL2 dev libs), then `pip install pygame` again. 
- **Unexpected crash**: check `csiv_demo_error.log` (the script writes a timestamped traceback there on unhandled exceptions). 

---

## Background / Spec

- **CSIV (Cell Selection Integrity Verification)** tightens UE pre‑authentication behavior by validating unauthenticated broadcast info (MIB/SIB, neighbor lists, priorities) and applying a conservative decision process with decay and state transitions before the UE attaches. This reduces dwell time on rogue cells without changing the 3GPP air‑interface.

If you’re implementing a real modem/HAL/userspace version, treat this demo as a conceptual aid; the spec is the source of truth for VCs, weighting, and enforcement mappings. 

---

## License & attribution

- Demo code: provided as‑is by the author in this repo/folder. 
- Specification: © 2022–2025 Michael (Mike) Curnow, C6. See the document header for terms. 
