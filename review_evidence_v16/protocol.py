"""Frozen design and independent accounting for the two site experiments."""
import itertools
import json
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "review_evidence_v11"))
from audit_guest import read, meter, measure

GRID = (0, 50, 100, 200, 300, 400)
FIELDS = ("seed", "dp", "burst", "arm", "guard_ms", "omit")

def plan(phase, delay=None):
    if phase == "calibration":
        rows = [(s,d,b,"guard",g,False) for s,d,b,g in itertools.product(range(1601,1604), ("system","netdev"), (4,32), GRID)]
        order = 23561
    else:
        rows = [(s,d,b,a,delay if a=="guard" else 0,s==1627) for s,d,b,a in itertools.product(range(1621,1628), ("system","netdev"), (4,32), ("guard","checked"))]
        order = 23562
    random.Random(order).shuffle(rows)
    return [list(r) for r in rows]

def rescore(directory, expected):
    assert read(directory/"plan.json") == expected
    scores = read(directory/"scores.json")
    assert len(scores) == len(expected)
    rows = []
    for meta, spec in zip(scores,expected):
        assert [meta[k] for k in FIELDS] == spec
        row = dict(zip(FIELDS,spec))
        row["eligible"] = False
        if "error" in meta:
            row["error"] = meta["error"]
        else:
            folder = directory/meta["folder"]
            row.update(measure(folder))
            meters = read(folder/"port_meters.json")
            matched = True
            for name, expected_count, src, dest in (("service",row["regular_seen"],43110,49002),("quarantine",row["reference_count"],45500+row["seed"]%200,49001)):
                m = meters[name]
                diff = meter(m["after"],src,dest)-meter(m["before"],src,dest)
                matched = matched and diff == expected_count
            row["eligible"] = bool(matched and row["valid"])
        rows.append(row)
    return rows

def choose(rows):
    counts = {str(g): sum(r["eligible"] and r["accepted"] for r in rows if r["guard_ms"]==g) for g in GRID}
    passing = [g for g in GRID if counts[str(g)]==12]
    return dict(exact_by_ms=counts, required=12, selected_ms=min(passing) if passing else 400, qualified=bool(passing))
