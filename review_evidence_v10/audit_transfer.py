"""Offline accounting of transfer runs. No network libraries, controller or privileges."""
import csv
import gzip
import hashlib
import itertools
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

def load(path):
    return json.loads(path.read_bytes())
def measure(folder):
    with gzip.open(folder/"trace.json.gz","rt") as stream:
        trace=json.load(stream)
    sent=trace["sent"]; ref=trace["reference"]; op=trace["sensor"]
    tx=Counter((i,s) for i,s,tag,t in sent)
    tags={(i,s) for i,s,tag,t in sent if tag}
    rx=Counter((i,s) for i,s,o,t,k in ref)
    q=Counter((i,s) for i,s,o,t,k in ref if o==1)
    good=bool(tags) and (tx==rx and all(v==1 for v in tx.values()) and
        set(q)==tags and not trace["reference_invalid"] and not trace["reference_error"] and not trace["sender_errors"])
    count=len(q)
    removals=folder/"removed.jsonl"
    reports=[json.loads(x) for x in removals.read_text().splitlines()] if removals.exists() else []
    assert [r["packets"] for r in reports]==trace["removal"]
    raw=reports[0]["packets"] if len(reports)==1 else None
    if len(reports)==1:assert reports[0]["cookie"]==((0x613901<<16)|1)
    observed=[(i,s,o) for i,s,o,t,k in op if k and t<=trace["marks"]["decision"]]
    target=Counter((i,s) for i,s,o in observed if o==1)
    seen=Counter((i,s) for i,s,o in observed)
    independent=(set(target)==tags and all(seen[k]==1 for k in tags) and not trace["sensor_invalid"] and not trace["sensor_error"])
    # Capture timestamps precede sensor bookkeeping. The policy can see a subset,
    # but never additional observations absent from this reconstruction.
    assert not trace["witness_complete"] or independent
    passive=bool(trace["witness_complete"] and not trace["sensor_error"] and raw is not None and raw==trace["witness_count"])
    if trace["precheck"]:
        assert trace["polls"] and trace["polls"][-1][1]==len(tags)
    release=raw is not None if trace["arm"]=="guard" else bool(trace["precheck"] and passive)
    exact=good and raw==count
    times=trace["marks"]
    return dict(valid=good,raw_count=raw,reference_count=count,exact=exact,released=release,
        accepted=good and release and exact,wrong=good and release and not exact,withheld=not release,
        passive_correct=good and passive and exact,passive_wrong=good and passive and not exact,
        polls=len(trace["polls"]),barrier_ms=(times["barrier"]-times["seal"])/1e6,
        peak=peak(sent,ref),regular_sent=sum(s==1 for i,s,tag,t in sent),
        regular_seen=sum(s==1 and o==0 for i,s,o,t,k in ref))

def peak(sent,ref):
    active=top=0
    for _,d in sorted([(t,1) for i,s,tag,t in sent]+[(t,-1) for i,s,o,t,k in ref]):
        active+=d
        top=max(top,active)
    return top

def check(folder,version):
    assert (folder/"environment.txt").read_text().count(version)>=2
    root=folder/"trials"
    plan=load(root/"plan.json")
    scores=load(root/"scores.json")
    dimensions={(s,d,b,a,400 if a=="guard" else 0,False) for s in range(1041,1047) for d in ("system","netdev") for b in (4,32) for a in ("guard","checked")}
    assert len(scores)==len(plan)==48 and dimensions==set(map(tuple,plan))
    out=[]
    for conditions,r in zip(plan,scores):
        assert conditions==[r[k] for k in ("seed","dp","burst","arm","guard_ms","omit")]
        row=dict(release=version,seed=r["seed"],dp=r["dp"],burst=r["burst"],arm=r["arm"],trial=r["folder"])
        if "error" in r:
            row.update(valid=False,error=r["error"])
        else:
            row.update(measure(root/r["folder"]))
            for k in ("valid","exact","released","peak","polls","barrier_ms"):
                assert row[k]==r[k],(r["folder"],k)
        out.append(row)
    return out

def summary(rows):
    ok=[r for r in rows if r["valid"]]
    total=lambda field:sum(r[field] for r in ok)
    return dict(planned=len(rows),eligible=len(ok),exact=total("exact"),correct=total("accepted"),wrong=total("wrong"),withheld=total("withheld"),
        passive_correct=total("passive_correct"),passive_wrong=total("passive_wrong"),polls=total("polls"),regular_sent=total("regular_sent"),regular_seen=total("regular_seen"),
        median_ms=st.median(r["barrier_ms"] for r in ok) if ok else None)

def audit(base,out):
    rows=[]
    result={}
    for v,sub in [("3.3.9","run_339"),("3.7.1","run_371")]:
        for name,h in load(base/sub/"trials"/"sources.json").items():
            assert hashlib.sha256((base.parent/name).read_bytes()).hexdigest()==h,name
        obs=check(base/sub,v)
        rows+=obs
        parts={f"{a}_{b}":summary([r for r in obs if r["arm"]==a and r["burst"]==b]) for a in ("guard","checked") for b in (4,32)}
        arms={a:summary([r for r in obs if r["arm"]==a]) for a in ("guard","checked")}
        index={(r["seed"],r["dp"],r["burst"],r["arm"]):r for r in obs if r["valid"]}
        diffs={}
        discordant=[0,0]
        for s in range(1041,1047):
            deltas=[]
            for dp in ("system","netdev"):
                for b in (4,32):
                    g=index.get((s,dp,b,"guard"));c=index.get((s,dp,b,"checked"))
                    if g and c:
                        deltas.append(g["barrier_ms"]-c["barrier_ms"])
                        discordant[0]+=int(c["accepted"] and not g["accepted"])
                        discordant[1]+=int(g["accepted"] and not c["accepted"])
            if len(deltas)==4:diffs[s]=st.mean(deltas)
        # Each seed block receives equal weight. This interval is conditional on one host.
        boot=sorted(sum(vals)/len(vals) for vals in itertools.product(diffs.values(),repeat=len(diffs))) if diffs else []
        result[v]=dict(arms=arms,cells=parts,discordant=discordant,seed_differences=diffs,
            mean_ms=st.mean(diffs.values()) if diffs else None,
            interval=[boot[int(p*(len(boot)-1))] for p in (.025,.975)] if boot else [],
            peak_range=[min(r["peak"] for r in obs if r["valid"]),max(r["peak"] for r in obs if r["valid"])] if index else [])
    out.mkdir(exist_ok=True,parents=True)
    (out/"transfer_summary.json").write_text(json.dumps(result,indent=2))
    with (out/"transfer_trials.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader();writer.writerows(rows)
    return result

if __name__=="__main__":
    data=audit(Path(sys.argv[1]),Path(sys.argv[2]))
    for version,s in data.items():print(version,s["arms"],s["mean_ms"],s["interval"])

