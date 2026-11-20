"""Prospectively specified local-only follow-up when the original grid has no qualifier."""
import itertools
import json
from pathlib import Path
import random
import statistics as st
import sys
from protocol import read,rescore
CANDIDATES=(325,350,375)

def design(phase,delay=None):
    if phase=="calibration":
        rows=[(s,d,b,"guard",g,False) for s,d,b,g in itertools.product(range(1701,1704),("system","netdev"),(4,32),CANDIDATES)]
        order=23601
    else:
        rows=[(s,d,b,a,delay if a=="guard" else 0,s==1727) for s,d,b,a in itertools.product(range(1721,1728),("system","netdev"),(4,32),("guard","checked"))]
        order=23602
    random.Random(order).shuffle(rows)
    return [list(r) for r in rows]

def select(rows):
    counts={g:sum(r["eligible"] and r["accepted"] for r in rows if r["guard_ms"]==g) for g in CANDIDATES}
    best=max(counts.values())
    return dict(exact_by_ms={str(g):c for g,c in counts.items()},required=12,selected_ms=min(g for g in CANDIDATES if counts[g]==best),qualified=best==12)

def run(root):
    from study import collect
    cal=design("calibration")
    collect(root,"calibration",cal)
    frozen=select(rescore(root/"calibration",cal))
    with (root/"frozen.json").open("x") as f:json.dump(frozen,f,indent=2)
    print("GUARD_FROZEN",frozen,flush=True)
    collect(root,"heldout",design("heldout",frozen["selected_ms"]))

def audit_fine(root):
    cal=rescore(root/"calibration",design("calibration"))
    frozen=select(cal)
    assert frozen==read(root/"frozen.json")
    rows=rescore(root/"heldout",design("heldout",frozen["selected_ms"]))
    result=dict(calibration=frozen,calibration_eligible=sum(r["eligible"] for r in cal))
    for mask,key in ((False,"clean"),(True,"fault")):
        result[key]={}
        for arm in ("guard","checked"):
            subs=[r for r in rows if r["omit"]==mask and r["arm"]==arm]
            ok=[r for r in subs if r["eligible"]]
            result[key][arm]=dict(planned=len(subs),eligible=len(ok),**{k:sum(r[k] for r in ok) for k in ("accepted","exact","wrong","withheld","polls")},mean_ms=st.mean(r["barrier_ms"] for r in ok) if ok else None)
    index={(r["seed"],r["dp"],r["burst"],r["arm"]):r for r in rows if not r["omit"] and r["eligible"]}
    blocks=[];wins=0
    for s in range(1721,1727):
        try: diffs=[index[s,d,b,"guard"]["barrier_ms"]-index[s,d,b,"checked"]["barrier_ms"] for d in ("system","netdev") for b in (4,32)]
        except KeyError:continue
        blocks.append(st.mean(diffs));wins+=sum(v>0 for v in diffs)
    values=sorted(sum(xs)/len(xs) for xs in itertools.product(blocks,repeat=len(blocks))) if blocks else []
    result["paired"]=dict(blocks=blocks,mean=st.mean(blocks) if blocks else None,interval=[values[int(q*(len(values)-1))] for q in (.025,.975)] if values else None,check_earlier=wins)
    return result

if __name__=="__main__":
    root=Path(sys.argv[2])
    if sys.argv[1]=="run":run(root)
    elif sys.argv[1]=="audit":print(json.dumps(audit_fine(root),indent=2))
    else:raise ValueError("Use run or audit")
