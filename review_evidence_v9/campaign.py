import argparse
import hashlib
import json
import platform
import random
import subprocess
from pathlib import Path
from trial import trial, score, ROOT

def write(path,data):
    temp = path.with_suffix(".new")
    temp.write_text(json.dumps(data,indent=2))
    temp.replace(path)

def campaign(out, smoke):
    out.mkdir(exist_ok=False,parents=True)
    phases = ["smoke"] if smoke else ["calibration","heldout"]
    frozen = {}
    for phase in phases:
        if phase == "smoke":
            plan = [(970,dp,16,"checked",0,False) for dp in ("system","netdev")]
        elif phase == "calibration":
            plan = [(s,dp,b,"guard",g,False) for s in (971,972) for dp in ("system","netdev")
                    for b in (4,16) for g in (0,50,250,1000)]
        else:
            plan = [(s,dp,b,a,frozen[dp]["guard_ms"] if a=="guard" else 0,s==991)
                    for s in (981,982,983,984,985,991) for dp in ("system","netdev")
                    for b in (4,16) for a in ("guard","immediate","checked")]
        random.Random(1071 if phase=="calibration" else 1072).shuffle(plan)
        base = out/phase
        base.mkdir()
        write(base/"plan.json",plan)
        rows=[]
        for n,(s,dp,b,a,g,f) in enumerate(plan):
            folder=base/f"{n:03d}_{s}_{dp}_{b}_{a}_{g}"
            folder.mkdir()
            row=dict(folder=folder.name,seed=s,dp=dp,burst=b,arm=a,guard_ms=g,omit=f)
            try:
                row.update(score(trial(folder,s,dp,b,a,g,f)))
            except Exception as err:
                row["error"]=repr(err)
            rows.append(row)
            write(base/"scores.json",rows)
            print(phase,n, row.get("error",(row["valid"],row["exact"]) if "valid" in row else "-"),flush=True)
        if phase=="calibration":
            for dp in ("system","netdev"):
                eligible=[]
                for g in (0,50,250,1000):
                    group=[r for r in rows if r["dp"]==dp and r["guard_ms"]==g]
                    if len(group)==4 and all(r.get("valid") and r["exact"] for r in group):
                        eligible.append(g)
                frozen[dp]={"guard_ms":min(eligible) if eligible else 1000,"eligible":eligible,"fallback":not eligible}
            write(out/"frozen.json",frozen)
    write(out/"environment.json",{"kernel":platform.release(),"python":platform.python_version(),
         "ovs":subprocess.check_output(["ovs-vswitchd","--version"],text=True).splitlines()[0],
         "sources":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
         for sub,names in {"review_evidence_v6":["wireless_trial.py","gateway_agent.py"],
                           "review_evidence_v7":["gateway_agent.py"],
                           "review_evidence_v9":["PROTOCOL.md","trial.py","campaign.py"]}.items()
         for name in names for p in [ROOT/sub/name]}})

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("--smoke",action="store_true")
    args=p.parse_args()
    campaign(args.out,args.smoke)

