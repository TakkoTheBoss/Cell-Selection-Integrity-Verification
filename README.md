# CSIV — Cell Selection Integrity Verification

**What it is**  
CSIV is a verification and decision framework that hardens how User Equipment (UE) chooses a serving cell _before_ it connects. It checks what a cell broadcasts (MIB/SIB and measurements), scores odd behavior, and steers the UE away from suspicious cells—reducing tracking, denial, and manipulation risks.

## The problem

Before security is established, **UEs rely on unauthenticated broadcast information** to pick and reselect cells. A rogue transmitter can spoof identities, tweak thresholds, or hide neighbors to win selection, keep a UE parked, or force back-offs. This threatens privacy and **can disrupt cellular-enabled operations** across transportation, power, water, industrial IoT, intelligent transport/roadside units, connected vehicles, and other cyber-physical systems which rely on cellular communications for commands, alerts, telemetry, and safety-critical comms.

## What CSIV does (at a high level)

- **Validate** key broadcast fields and measurements for plausibility and consistency.
    
- **Score** anomalies with weights and a time **decay** (short blips fade; persistent issues matter).
    
- **Decide** via a simple state machine: **Clean → Suspect → Barred → Probation**, with defined **immediate overrides** for high-confidence attacks.
    
- **Act** by barring/avoiding or rapidly exiting questionable cells; log evidence for tuning and audit.
    

> CSIV adds no new air-interface messages; it uses existing 3GPP info.

## Core checks (Verification Conditions, “VCs”)

- **sVer (Scheduling):** SI periodicities/window are valid and sane.
    
- **tVer (Timing):** `connEstFailCount`, `T300` valid and not maxed out.
    
- **dVer (Duplication):** No conflicting PCI/CID duplicates in the local view.
    
- **lVer (Location):** TAC matches trusted TACs.
    
- **pVer (Priority):** `cellReselectionPriority` not abnormally elevated.
    
- **nVer (Neighborhood):** Advertised neighbors intersect trusted neighbor sets.
    
- **spVer (Signal Power):** Deviation fits local variability (adaptive Z-threshold).
    
- **qVer (Min Threshold):** `q-RxLevMin` is reasonable and neighbor-consistent.
    
- **rVer (Received Level):** UE’s RSRP coherent with `q-RxLevMin` and not below a plausibility floor.
    

Each “soft” VC contributes a small penalty (ΔS); “fatal” combos (e.g., duplicate identity **and** no neighbors) trigger an immediate bar.

## Decision engine (summary)

- **Suspicion score SSS** uses a half-life decay so transient blips fade.
    
- Thresholds move cells between **Clean/Suspect/Barred**, with **Probation** to re-enter clean state after time and a few clean evaluations.
    
- Repeated bar events increase the barred duration (exponential backoff).
    

## Where it runs

CSIV is designed for baseband integration, but the same logic can also be realized in a driver/HAL or a supervisory userspace service where available controls allow (e.g., steer reselection, deny/avoid lists). Behavior is the same; enforcement power depends on platform.

## What it does **not** do

- It is **not** a new protocol and defines no new RRC/NAS IEs.
    
- It does **not** change network behavior; it’s a UE-side policy.
    

## Getting started with the spec

1. **Introduction** → threat model and motivation.
    
2. **Components** → OCS data and VC definitions.
    
3. **Verification Algorithm** → scoring, decay, state machine, overrides.
    
4. **Tuning** → weights, thresholds, half-life; logging for audit.
    

## References

3GPP TS 36.304/36.331 (LTE) and TS 38.304/38.331 (NR) for the source IEs and procedures CSIV evaluates.
