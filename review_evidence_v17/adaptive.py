"""Bounded scheduling of reads for an already sealed diversion epoch."""
import time

def next_delay_ms(reading, target):
    if reading is None:
        return 145
    deficit = min(1, max(0, (target - reading) / target))
    return round(35 + 110 * deficit)

def check(agent, witness, target, record, policy):
    seal = record["marks"]["seal"]
    due = seal + 100_000_000
    last_slot = seal + 460_000_000
    deadline = seal + 500_000_000
    while time.monotonic_ns() <= deadline:
        now = time.monotonic_ns()
        if now < due:
            time.sleep((due - now) / 1e9)
            continue
        if witness.quarantine != target or any(witness.seen.get(k) != 1 for k in target):
            time.sleep(.005)
            continue
        start = time.monotonic_ns()
        if start > deadline:
            break
        reading = agent.snapshot()
        end = time.monotonic_ns()
        record["polls"].append([end, reading])
        record.setdefault("read_starts", []).append(start)
        if reading == len(target):
            return True
        if start >= last_slot:
            break
        interval = next_delay_ms(reading, len(target)) if policy == "adaptive" else 100
        due = min(end + interval * 1_000_000, last_slot)
    return False
