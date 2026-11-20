"""Independent accounting from sender, packet, switch, snapshot and port journals."""
import gzip
import itertools
import json
from pathlib import Path
from statistics import mean
import sys
from design import plan,rescore,treatments

def interval(values):
    if not values: return dict(blocks=[],mean=None,interval=None)
    boot=sorted(sum(x)/len(x) for x in itertools.product(values,repeat=len(values)))
    return dict(blocks=values,mean=mean(values),interval=[boot[int(q*(len(boot)-1))] for q in (.025,.975)])

def audit(root,site):
    directory=root/"comparison"
    design=plan(site)
    rows=rescore(directory,design)
    raw_scores=json.loads((directory/"scores.json").read_bytes())
    for row,m in zip(rows,raw_scores):
        row["policy"]=str(row["guard_ms"]) if row["arm"]=="guard" else row["arm"]
        if "error" in m:continue
        with gzip.open(directory/m["folder"]/"trace.json.gz","rt") as f: trace=json.load(f)
        assert [trace[k] for k in ("seed","datapath","burst","arm","guard_ms","omit")]==[row[k] for k in ("seed","dp","burst","arm","guard_ms","omit")]
        if row["arm"] not in ("adaptive","sparse"):continue
        seal=trace["marks"]["seal"]; starts=trace.get("read_starts",[]); polls=trace["polls"]
        assert len(starts)==len(polls)
        due=seal+100_000_000
        for start,(end,reading) in zip(starts,polls):
            assert due<=start<=seal+500_000_000 and start<=end
            assert len([s for s in starts if s>=seal+460_000_000])<=1
            target=sum(bool(t) for _,_,t,_ in trace["sent"])
            delay=100 if row["arm"]=="sparse" else (145 if reading is None else round(35+110*min(1,max(0,(target-reading)/target))))
            due=min(end+delay*1_000_000,seal+460_000_000)
    policies=[str(d) if a=="guard" else a for a,d in treatments(site)]
    result={}
    for mask,name in ((False,"clean"),(True,"omission")):
        result[name]={}
        for policy in policies:
            all_rows=[r for r in rows if r["omit"]==mask and r["policy"]==policy]
            sub=[r for r in all_rows if r["eligible"]]
            result[name][policy]=dict(planned=len(all_rows),eligible=len(sub),**{k:sum(r[k] for r in sub) for k in ("accepted","wrong","withheld","exact","polls")},mean_ms=mean(r["barrier_ms"] for r in sub) if sub else None)
    index={(r["seed"],r["dp"],r["burst"],r["policy"]):r for r in rows if r["eligible"] and not r["omit"]}
    result["paired"]={}
    for comp in policies:
        if comp=="adaptive":continue
        contrasts={}
        for metric in ("polls","barrier_ms","accepted"):
            blocks=[]
            for seed in range(1811,1817):
                keys=[(seed,dp,b) for dp,b in itertools.product(("system","netdev"),(4,32))]
                if all((*k,comp) in index and (*k,"adaptive") in index for k in keys):
                    blocks.append(mean(index[*k,comp][metric]-index[*k,"adaptive"][metric] for k in keys))
            contrasts[metric]=interval(blocks)
        result["paired"][comp]=contrasts
    return result
if __name__=="__main__":print(json.dumps(audit(Path(sys.argv[1]),sys.argv[2]),indent=2))
