"""Regenerate the summaries from records using only standard Python."""
import itertools
import json
import statistics as st
import sys
from pathlib import Path
from protocol import plan, choose, rescore, read

def audit(root):
    calibration=rescore(root/"calibration",plan("calibration"))
    frozen=choose(calibration)
    assert read(root/"frozen.json")==frozen
    held=rescore(root/"heldout",plan("heldout",frozen["selected_ms"]))
    result=dict(calibration=frozen, calibration_eligible=sum(r["eligible"] for r in calibration))
    for mask,part in ((False,"clean"),(True,"fault")):
        result[part]={}
        for arm in ("guard","checked"):
            cell=[r for r in held if r["arm"]==arm and r["omit"]==mask]
            eligible=[r for r in cell if r["eligible"]]
            result[part][arm]=dict(planned=len(cell),eligible=len(eligible),**{k:sum(r[k] for r in eligible) for k in ("accepted","wrong","withheld","polls")},mean_ms=st.mean(r["barrier_ms"] for r in eligible) if eligible else None)
    index={(r["seed"],r["dp"],r["burst"],r["arm"]):r["barrier_ms"] for r in held if r["eligible"] and not r["omit"]}
    blocks=[]
    for s in range(1621,1627):
        try:
            blocks.append(st.mean(index[s,d,b,"guard"]-index[s,d,b,"checked"] for d in ("system","netdev") for b in (4,32)))
        except KeyError:
            continue
    boot=sorted(st.mean(x) for x in itertools.product(blocks,repeat=len(blocks))) if blocks else []
    result["paired"]=dict(seed_means=blocks,mean=st.mean(blocks) if blocks else None,interval=[boot[int(q*(len(boot)-1))] for q in (.025,.975)] if boot else None)
    return result

if __name__=="__main__":
    print(json.dumps(audit(Path(sys.argv[1])),indent=2))
