"""Frozen acquisition and pairing plan for an isolated defensive accounting study."""
import itertools
import random
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"review_evidence_v16"))
from protocol import FIELDS,rescore

def treatments(site):
    assert site in ("local","hosted")
    return [("guard",d) for d in ((325,400) if site=="local" else (300,))]+[("checked",0),("sparse",0),("adaptive",0)]

def plan(site):
    rows=[[s,dp,b,a,g,s>=1817] for s,dp,b in itertools.product(range(1811,1819),("system","netdev"),(4,32)) for a,g in treatments(site)]
    random.Random(41800).shuffle(rows)
    return rows
