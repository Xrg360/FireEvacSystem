# Evaluation: reproducing Table I

These are **simulation** results. They come from the discrete-time simulator in `app/simulation`, run on the two demo buildings in `contracts/fixtures`. Every run is reproducible:

```bash
python -m app.simulation.benchmark --seeds 20 --json contracts/benchmark_results.json
```

## Method

- **Same scenario for both strategies.** For each seed, the static and dynamic strategies see:
  - the same occupants and spawn rooms;
  - the same walking speeds and reaction times (0–20 s);
  - the same 5 % of occupants with mobility needs;
  - the same random fire spread, from a separate random stream.
- **Static plan.** Everyone walks to their nearest exit by distance. People re-plan only when they physically run into fire. This is how a printed evacuation plan is followed in practice.
- **Proposed system.** The paper's dynamic A\* with:
  - hazard costs, with smoke and risk spreading around the fire;
  - congestion costs;
  - exit-capacity balancing;
  - lifts excluded during an incident;
  - refuge routing for people who can't use stairs;
  - anti-flip-flop rerouting: a 15 % improvement threshold and a 10 s cooldown.
- **Crowd model.**
  - Speed is 1.25 ± 0.25 m/s, and slows to 15 % of normal as density rises.
  - Stairs reduce speed to 0.6×, and smoke to 0.7×.
  - Each exit lets people through at its rated flow (people/min), so queues form there.
- **Fire.** Spread is probabilistic along graph edges. Doors slow it, and it climbs stair cores more easily than it descends. Anyone who stays on a burning node for 20 s counts as trapped.
- **Positioning.** Uses synthetic scans:
  - a log-distance path-loss model with 4 dB of Gaussian noise;
  - 15 dB of loss per floor slab;
  - a simulated survey of 15 scans per room.

## Results (20 seeds)

### Block B: 4-storey tower, 150 occupants, fire starts in flat 102

| Metric | Static plan | Proposed (dynamic A*) | Change |
|---|---|---|---|
| Average evacuation time | 55.6 s | 47.8 s | **−14 %** |
| 90th percentile evacuation time | 104.1 s | 78.7 s | **−24 %** |
| Total evacuation time | 126.3 s | 105.3 s | **−17 %** |
| Average exit queue | 10.3 people | 5.5 people | **−47 %** |
| Peak exit queue | 14.0 | 8.7 | −38 % |
| Trapped by fire | 1.15 | 0.80 | −30 % |
| Server route recomputation (200 people) | N/A | 10.9 ms | |
| Localization error, fused particle filter (median / p90) | – | 1.95 m / 5.0 m | |
| Localization error, trilateration only (median) | – | 6.7 m | |
| Localization error, fingerprint kNN only (median) | – | 2.6 m | |
| Correct floor (particle filter) | – | 100 % | |

### Block A: single-floor villa from the paper, 30 occupants, fire in the kitchen

| Metric | Static plan | Proposed | Change |
|---|---|---|---|
| Average evacuation time | 21.7 s | 21.5 s | −1 % |
| Average exit queue | 0.84 | 0.67 | −20 % |
| Localization error, fused (median / p90) | – | 1.8 m / 3.8 m | |

## Against the paper's Table I

| Paper claim | Our measurement | Comment |
|---|---|---|
| Evacuation time 450 s → 320 s (−29 %) | −14 % average, −24 % p90 (tower) | Same direction, smaller effect. Our buildings are smaller: evacuation takes about 2 minutes, not 7. The gain grows with crowd size and exit imbalance. A small villa barely benefits. |
| Exit queue reduction 35 % | 47 % (tower), 20 % (villa) | Comes mainly from exit-capacity balancing. |
| Route update latency ≈ 2.1 s | 11 ms server compute for 200 people; under 0.5 s over the LAN; 1 s engine tick | End-to-end latency on a phone is dominated by the engine tick (1 s) plus the network. FCM wake-up of a locked phone wasn't measured here; it depends on the device. |
| Localization 3–5 m | 1.95 m median / 5.0 m p90 (synthetic) | **Optimistic.** Synthetic noise is cleaner than a real building. The README sets out real-world expectations: room-level, 4–8 m, with scan throttling on. |

## Predictive congestion (paper Table II, "short-term" future work)

`python -m scripts.train_congestion --runs 24` collected about 106 000 samples (node × tick). The test set was 20 % of **scenarios**, held out whole:

| Predicting occupancy 30 s ahead | Mean absolute error (people / node) |
|---|---|
| Gradient-boosted model | **0.34** |
| Persistence ("nothing changes") | 1.39 |
| Planned-inflow heuristic | 1.74 |

So the model forecasts congestion about 4× more accurately. **But plugging it into routing did not measurably improve evacuations.** Tower, 6 seeds:

| Occupants | No prediction | Heuristic | Trained model |
|---|---|---|---|
| 150: average evacuation time / average queue | 47.8 s / 5.04 | 47.1 s / 5.12 | 47.9 s / 5.17 |
| 250: average evacuation time / average queue | 63.6 s / 11.03 | 63.2 s / 11.08 | 64.3 s / 10.92 |

All differences are within ±1.5 %, which is seed noise. The likely reason is that exit balancing already counts the people *assigned* to each exit, and that captures most of what a 30-second forecast adds. The model also learned from the same simulator it is tested in. We report this as a negative result rather than tuning until the numbers look good. Possible future work:
- forecasts over longer horizons, or at the stair cores;
- training on real drill data.

## Limits of this evaluation

- Everything here is simulated. Real-world validation with residents and the fire department remains future work, as the paper also says.
- The crowd model is graph-based, so it doesn't model individual collisions. The density–speed relation is simplified.
- Positioning numbers use synthetic RSSI. Expect larger errors in real buildings with people, furniture and routers changing.
