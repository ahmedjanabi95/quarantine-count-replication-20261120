"""Independent guest-kernel, sender, socket and controller accounting."""
import csv
import gzip
import hashlib
import itertools
import json
import statistics as st
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"review_evidence_v10"))
from audit_transfer import measure

def read(path):return json.loads(path.read_bytes())
def meter(observations,src,dst):
    detailed=[r["options"] for r in observations if r.get("kind")=="flower" and "actions" in r.get("options",{})]
    assert len(detailed)==1,observations
    record=detailed[0]
    keys=record["keys"]
    assert keys["eth_type"]=="ipv4" and keys["ip_proto"]=="udp" and record["skip_hw"] is True
    assert str(keys["src_port"])==str(src) and str(keys["dst_port"])==str(dst),keys
    actions=record["actions"]
    assert len(actions)==1 and actions[0]["kind"]=="gact"
    assert actions[0]["control_action"]["type"]=="pass"
    stats=actions[0]["stats"]
    return int(stats["packets"] if "packets" in stats else stats["basic"]["packets"])

def paired(rows,metric):
    ref={(r["seed"],r["dp"],r["burst"],r["arm"]):r for r in rows if r.get("eligible") and not r["omit"]}
    seeds={}
    for s in range(1141,1147):
        diffs=[]
        for dp in ("system","netdev"):
            for b in (4,32):
                g=ref.get((s,dp,b,"guard"));c=ref.get((s,dp,b,"checked"))
                if g and c:diffs.append(g[metric]-c[metric])
        if len(diffs)==4:seeds[str(s)]=st.mean(diffs)
    if not seeds:return {"blocks":seeds}
    values=list(seeds.values())
    boot=sorted(sum(vals)/len(vals) for vals in itertools.product(values,repeat=len(values)))
    return dict(blocks=seeds,mean=st.mean(values),interval=[boot[int(p*(len(boot)-1))] for p in (.025,.975)])

def audit(campaign,out):
    runs=campaign/"trials"
    plan=read(runs/"plan.json");scores=read(runs/"scores.json")
    assert len(plan)==len(scores)==56
    assert set(map(tuple,plan))=={(s,d,b,a,400 if a=="guard" else 0,s==1147)
        for s in range(1141,1148) for d in ("system","netdev") for b in (4,32) for a in ("guard","checked")}
    rows=[]
    for conditions,r in zip(plan,scores):
        assert conditions==[r[k] for k in ("seed","dp","burst","arm","guard_ms","omit")]
        f=runs/r["folder"]
        row={k:r[k] for k in ("folder","seed","dp","burst","arm","omit")}
        if "error" in r:
            row.update(eligible=False,error=r["error"])
        else:
            account=measure(f);assert account["valid"]==r["valid"] and account["exact"]==r["exact"]
            with gzip.open(f/"trace.json.gz","rt") as src:trace=json.load(src)
            meters=read(f/"port_meters.json")
            measured={}
            for name,src,dst in (("service",43110,49002),("quarantine",45500+r["seed"]%200,49001)):
                m=meters[name]
                assert m["source"]==src and m["dest"]==dst
                before=meter(m["before"],src,dst);after=meter(m["after"],src,dst)
                assert after>=before>=0
                measured[name]=after-before
            row.update(account)
            row.update(tc_service=measured["service"],tc_quarantine=measured["quarantine"],
                meter_agrees=(measured["service"]==account["regular_seen"] and measured["quarantine"]==account["reference_count"]),
                decision_ms=(trace["marks"]["decision"]-trace["marks"]["seal"])/1e6)
            row["eligible"]=row["valid"] and row["meter_agrees"]
            assert account["released"]==r["released"] and abs(account["barrier_ms"]-r["barrier_ms"])<1e-9
        rows.append(row)
    def totals(cell):
        eligible=[r for r in cell if r["eligible"]]
        return dict(planned=len(cell),eligible=len(eligible),meters_agree=sum(r.get("meter_agrees",False) for r in cell),
                    **{k:sum(r[k] for r in eligible) for k in ("accepted","exact","wrong","withheld","passive_correct","polls","tc_service","tc_quarantine")})
    results={c:{a:totals([r for r in rows if r["arm"]==a and r["omit"]==is_fault])
                for a in ("guard","checked")} for c,is_fault in (("clean",False),("masked",True))}
    results["strata"]={f"{dp}_{a}":totals([r for r in rows if r["dp"]==dp and r["arm"]==a and not r["omit"]]) for dp in ("system","netdev") for a in ("guard","checked")}
    results["choices"]={}
    for mask,label in ((False,"clean"),(True,"masked")):
        result={}
        for rule in ("guard_audit","mixed","all_checked"):
            chosen=[r for r in rows if r["omit"]==mask and r["arm"]==("checked" if rule=="all_checked" or (rule=="mixed" and r["dp"]=="netdev") else "guard")]
            assessed=[r for r in chosen if r["eligible"]]
            correct=sum(r["accepted"] if r["arm"]=="checked" else r["passive_correct"] for r in assessed)
            incorrect=sum(r["wrong"] if r["arm"]=="checked" else r["passive_wrong"] for r in assessed)
            result[rule]=dict(n=len(chosen),eligible=len(assessed),correct=correct,incorrect=incorrect,
                withheld=len(assessed)-correct-incorrect,reads=sum(r["polls"] for r in assessed))
        results["choices"][label]=result
    for m in ("barrier_ms","decision_ms"):results[m]=paired(rows,m)
    out.mkdir(parents=True,exist_ok=True)
    (out/"guest_summary.json").write_text(json.dumps(results,indent=2))
    with (out/"guest_trials.csv").open("w",newline="") as stream:
        writer=csv.DictWriter(stream,list(dict.fromkeys(k for r in rows for k in r)));writer.writeheader();writer.writerows(rows)
    return results

if __name__=="__main__":
    print(json.dumps(audit(Path(sys.argv[1]),Path(sys.argv[2])),indent=2))

