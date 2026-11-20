"""Run a fresh per-guest calibration, freeze it, then evaluate both arms."""
import sys
from pathlib import Path
from unittest.mock import patch
from protocol import FIELDS, plan, rescore, choose
import guest_trial as guest
from campaign import write

def collect(root, phase, design):
    out=root/phase
    out.mkdir()
    write(out/"plan.json",design)
    rows=[]
    for number, spec in enumerate(design):
        seed, dp, burst, arm, delay, omitted=spec
        folder=out/f"{number:03d}_{seed}_{dp}_{burst}_{arm}_{delay}"
        folder.mkdir()
        row=dict(zip(FIELDS,spec),folder=folder.name)
        try:
            with patch.object(guest.base.w,"PortGroup",guest.instrument(folder,seed)):
                row.update(guest.base.score(guest.base.trial(folder,*spec)))
        except Exception as err:
            row["error"]=repr(err)
        rows.append(row)
        write(out/"scores.json",rows)
        print("SITE_TRIAL",phase,number,row.get("error","captured"),flush=True)

if __name__=="__main__":
    root=Path(sys.argv[1])
    cal=plan("calibration")
    collect(root,"calibration",cal)
    frozen=choose(rescore(root/"calibration",cal))
    with (root/"frozen.json").open("x") as stream:
        import json
        json.dump(frozen,stream,indent=2)
    print("GUARD_FROZEN",frozen,flush=True)
    collect(root,"heldout",plan("heldout",frozen["selected_ms"]))
