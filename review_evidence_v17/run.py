from pathlib import Path
import sys
from unittest.mock import patch
from design import plan
from study import collect,guest
import trial_v17
from adaptive import check

def main(root,site):
    original=guest.base.trial
    def execute(folder,seed,dp,burst,arm,delay,omit):
        entry=trial_v17.trial if arm in ("adaptive","sparse") else original
        return entry(folder,seed,dp,burst,arm,delay,omit)
    with patch.object(guest.base,"trial",execute):
        collect(root,"comparison",plan(site))

if __name__=="__main__": main(Path(sys.argv[1]),sys.argv[2])
