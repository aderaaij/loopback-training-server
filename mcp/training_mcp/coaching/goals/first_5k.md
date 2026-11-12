# Goal module: First 5K — starting from zero

For an athlete who has never run, hasn't run in years, or cannot yet run 10
minutes continuously. Experience levels don't apply here — this module *is*
the beginner path. If workout history shows they can already run ~30 min
continuously, use the `5k` module instead.

## Principles

- **Walk/run intervals from day one** (Couch-to-5K model). Cardiovascular
  fitness adapts in weeks; tendons and bones take months. Walk breaks protect
  the slow-adapting tissues while the heart and lungs improve.
- **3 sessions/week, never on consecutive days.** More is counterproductive
  at this stage.
- **No pace targets, ever.** Effort only. Run segments should pass the talk
  test — if the athlete can't speak a short sentence, they're running too
  fast. "Slower than feels natural" is correct.
- **Progression is gated on comfort, not the calendar.** Repeating a week is
  a success, not a failure. The plan takes 9 weeks only if every week goes
  well; 12–16 weeks is normal and fine.

## The 9-week progression (NHS Couch to 5K)

Every session: 5-min brisk-walk warmup → intervals below → 5-min walk cooldown.
All 3 weekly sessions are identical except weeks 5 and 6.

| Week | Session (×3/week unless noted) |
|------|--------------------------------|
| 1 | 8 × (run 60s / walk 90s) |
| 2 | 6 × (run 90s / walk 2min) |
| 3 | 2 × (run 90s / walk 90s / run 3min / walk 3min) |
| 4 | run 3min / walk 90s / run 5min / walk 2½min / run 3min / walk 90s / run 5min |
| 5 | S1: 3 × (run 5min / walk 3min) · S2: run 8 / walk 5 / run 8 · S3: **run 20min continuous** |
| 6 | S1: run 5 / walk 3 / run 8 / walk 3 / run 5 · S2: run 10 / walk 3 / run 10 · S3: **run 25min continuous** |
| 7 | run 25min continuous |
| 8 | run 28min continuous |
| 9 | run 30min continuous — graduation (~5K) |

## Coaching rules

- Advance to the next week only when all three sessions were completed and
  the last one felt manageable. Otherwise repeat the week — say so positively.
- The jump to continuous running (week 5 session 3) is the classic failure
  point. If it fails, the fix is almost always pace, not fitness: repeat at a
  slower effort before concluding the athlete "isn't ready".
- Sharp or localized pain (shin, knee, foot): insert extra rest days.
  Pain that persists across sessions: pause the plan and recommend
  professional assessment. Muscle soreness that fades within 48h is normal.
- If continuous running keeps failing after repeats, reframe with the
  Galloway run-walk-run model: a 5K with planned walk breaks (e.g. 2min run /
  1min walk throughout) is a complete, legitimate goal — not a fallback.

## Mapping onto this API

- These sessions translate directly to structured workouts: warmup step
  (time goal, 5min), one interval block with iterations (work = run segment,
  recovery = walk segment), cooldown step. Use **time goals only — no pace or
  HR alerts**.
- **Queue at most 1–2 weeks ahead.** Progression is gated, so check completed
  workouts and `get_workout_feedback` before queueing the next week; requeue
  the same week when repeating.
- Set plan `guardrails` metadata: no pace targets, max 3 sessions/week,
  repeat-don't-push.

## After graduation

Consolidate first: 3 × 30min easy running for 2–4 weeks before adding any
distance or speed. Then a parkrun or local 5K event makes a great milestone;
the `5k` module (beginner level) is the natural next block.
