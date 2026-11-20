"""Apply unchanged retirement policies with separate guest-kernel accounting."""
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"review_evidence_v9"))
import trial as base
from campaign import write

def run_cmd(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT,timeout=8)

def observe(port):
    return json.loads(run_cmd("tc","-j","-s","filter","show","dev",port,"ingress"))

def instrument(folder,seed):
    native=base.w.PortGroup
    class MeteredGroup(native):
        def __init__(self,index,scope,parent):
            super().__init__(index,scope,parent)
            meters={}
            for name,output,source,dest in (("service",1,43110,49002),("quarantine",2,45500+seed%200,49001)):
                iface=self.ports[output].getsockname()[0]
                run_cmd("tc","qdisc","add","dev",iface,"clsact")
                run_cmd("tc","filter","add","dev",iface,"ingress","protocol","ip","pref","41","flower","skip_hw",
                        "ip_proto","udp","src_port",str(source),"dst_port",str(dest),"action","pass")
                meters[name]=dict(port=iface,source=source,dest=dest,before=observe(iface))
            write(folder/"port_meters.json",meters)
            def finish():
                for entry in meters.values():
                    entry["after"]=observe(entry["port"])
                write(folder/"port_meters.json",meters)
            scope.callback(finish)
    return MeteredGroup

def run(out,smoke):
    out.mkdir(exist_ok=False)
    plan=[(1140,d,4,"checked",0,False) for d in ("system","netdev")] if smoke else [
        (s,d,b,a,400 if a=="guard" else 0,s==1147) for s in range(1141,1148)
        for d in ("system","netdev") for b in (4,32) for a in ("guard","checked")]
    random.Random(419).shuffle(plan)
    write(out/"plan.json",plan)
    rows=[]
    for n,(s,dp,b,arm,delay,mask) in enumerate(plan):
        folder=out/f"{n:03d}_{s}_{dp}_{b}_{arm}"
        folder.mkdir()
        row=dict(folder=folder.name,seed=s,dp=dp,burst=b,arm=arm,guard_ms=delay,omit=mask)
        try:
            with patch.object(base.w,"PortGroup",instrument(folder,s)):
                raw=base.trial(folder,s,dp,b,arm,delay,mask)
            row.update(base.score(raw))
        except Exception as err:
            row["error"]=repr(err)
        rows.append(row)
        write(out/"scores.json",rows)
        print("LEASE_TRIAL",n,dp,arm,row.get("error","captured"),flush=True)
    if smoke and any("error" in r for r in rows):raise RuntimeError("Guest infrastructure preflight failed")

if __name__=="__main__":run(Path(sys.argv[1]),"--smoke" in sys.argv[2:])

