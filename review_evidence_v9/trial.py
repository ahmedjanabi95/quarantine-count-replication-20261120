"""Bounded, local functional accounting trial on a fresh private OpenFlow bridge."""
import contextlib
import gzip
import json
import random
import select
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "review_evidence_v6"))
import wireless_trial as w

clock = time.monotonic_ns

def stored(path, data):
    with gzip.open(path, "wt", encoding="utf8") as stream:
        json.dump(data, stream, separators=(",", ":"))

def frame(seq, session, tag):
    packet = w.frame(seq, session)
    if tag:
        packet = packet[:34] + struct.pack("!H", tag) + packet[36:]
    return packet

class Capture:
    def __init__(self, ports, tag, mask=False):
        self.ports = ports
        self.tag = tag
        self.mask = mask
        self.events = []
        self.quarantine = set()
        self.seen = {}
        self.invalid = 0
        self.stop = threading.Event()
        self.cpu = 0
        self.error = None
        self.thread = threading.Thread(target=self.collect)

    def collect(self):
        begin = time.thread_time_ns()
        try:
            while True:
                ready = select.select(self.ports, [], [], .008)[0]
                if not ready and self.stop.is_set():
                    break
                for sock in ready:
                    pkt = sock.recv(2048)
                    now = clock()
                    if len(pkt) != 106:
                        self.invalid += 1
                        continue
                    seq, session, _ = struct.unpack_from("!HBB", pkt, 42)
                    tag = struct.unpack_from("!H", pkt, 34)[0]
                    if session not in (0, 1) or pkt != frame(seq, session, self.tag if tag == self.tag else 0):
                        self.invalid += 1
                        continue
                    output = self.ports.index(sock)
                    keep = not (self.mask and output == 1 and seq % 8 == 0)
                    self.events.append([seq, session, output, now, int(keep)])
                    if keep:
                        key = (seq, session)
                        self.seen[key] = self.seen.get(key, 0) + 1
                        if output == 1:
                            self.quarantine.add(key)
        except Exception as err:
            self.error = repr(err)
        self.cpu = time.thread_time_ns() - begin

def trial(folder, seed, dp, burst, arm, guard_ms, omit):
    native = w.command
    def bridge(*args):
        if args[:2] == ("ovs-vsctl", "add-br"):
            return native(*args, "--", "set", "bridge", args[2], "datapath_type="+dp)
        return native(*args)
    record = dict(seed=seed, datapath=dp, burst=burst, arm=arm, guard_ms=guard_ms, omit=omit,
                  sent=[], polls=[], removal=[], marks={}, sender_errors=[])
    marks = record["marks"]
    tag = 45500 + seed % 200
    with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
        with patch.object(w, "HERE", ROOT/"review_evidence_v7"), patch.object(w, "command", bridge):
            agent = w.PortGroup(0, stack, Path(tmp))
        assert native("ovs-vsctl","get","bridge",agent.bridge,"datapath_type").strip('"') == dp
        (agent.folder/"versioned_port").write_text(str(tag))
        separate = []
        for port in agent.ports[1:]:
            sock = stack.enter_context(socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800)))
            sock.bind((port.getsockname()[0], 0))
            separate.append(sock)
        witness = Capture(agent.ports[1:], tag, omit)
        reference = Capture(separate, tag)
        for cap in (witness, reference):
            cap.thread.start()
        ordinary_stop = threading.Event()
        updater = None
        seq = 0
        def send(seq, session, selected):
            packet = frame(seq, session, tag if selected else 0)
            begin = clock()
            assert agent.ports[0].send(packet) == len(packet)
            record["sent"].append([seq, session, int(selected), begin])
        def background(start):
            try:
                due = time.monotonic()
                idx = start
                while not ordinary_stop.is_set():
                    for _ in range(burst):
                        send(idx, 1, False)
                        idx += 1
                    due += .03125
                    ordinary_stop.wait(max(0, due-time.monotonic()))
                    if idx > 10000:
                        raise RuntimeError("bounded traffic deadline")
            except Exception as err:
                record["sender_errors"].append(repr(err))
        try:
            agent.change(1)
            due = time.monotonic()
            batches = random.Random(seed).randint(8,11)
            for b in range(batches):
                time.sleep(max(0, due-time.monotonic()))
                for _ in range(burst):
                    send(seq, 0, True)
                    send(seq, 1, False)
                    seq += 1
                due += .03125
            target = {(k,0) for k in range(seq)}
            marks["seal"] = clock()
            updater = threading.Thread(target=background,args=(seq,))
            updater.start()
            matched = False
            if arm == "guard":
                time.sleep(guard_ms/1000)
            if arm == "checked":
                while clock() - marks["seal"] <= 500_000_000:
                    if witness.quarantine == target and all(witness.seen.get(k)==1 for k in target):
                        reading = agent.snapshot()
                        record["polls"].append([clock(),reading])
                        if reading == len(target):
                            matched = True
                            break
                    time.sleep(.020)
            record["precheck"] = matched
            agent.change(0)
            marks["barrier"] = clock()
            until = time.monotonic()+.100
            while time.monotonic()<until:
                if agent.counters() and witness.quarantine == target:
                    break
                time.sleep(.002)
            record["removal"] = agent.counters()
            # Snapshot operational state at the decision deadline, before diagnostic drainage.
            record["witness_complete"] = (witness.quarantine == target and
                all(witness.seen.get(k)==1 for k in target) and witness.invalid==0)
            record["witness_count"] = len(witness.quarantine)
            marks["decision"] = clock()
            time.sleep(.080)
        finally:
            ordinary_stop.set()
            if updater: updater.join(2)
            time.sleep(.025)
            for cap in (witness, reference):
                cap.stop.set()
                cap.thread.join(2)
            for name in ("controller.log","errors","removed.jsonl"):
                if (agent.folder/name).exists():
                    shutil.copyfile(agent.folder/name, folder/name)
            for name,cap in (("sensor",witness),("reference",reference)):
                record[name] = cap.events
                record[name+"_invalid"] = cap.invalid
                record[name+"_error"] = cap.error
                record[name+"_cpu_ns"] = cap.cpu
            stored(folder/"trace.json.gz",record)
    return record

def score(r):
    sent = {(i,s):(tag,t) for i,s,tag,t in r["sent"]}
    ref = {(i,s):(out,t) for i,s,out,t,_ in r["reference"]}
    selected = {k for k,(tag,_) in sent.items() if tag}
    diverted = {k for k,(out,_) in ref.items() if out}
    good = (len(sent)==len(r["sent"]) and len(ref)==len(r["reference"]) and
            set(ref)==set(sent) and diverted==selected and bool(selected) and
            not r["reference_invalid"] and not r["reference_error"] and not r["sender_errors"])
    msg = r["removal"][0] if len(r["removal"])==1 else None
    passive = (msg is not None and not r["sensor_error"] and r["witness_complete"] and msg==r["witness_count"])
    released = ((msg is not None) if r["arm"]=="guard" else
               (passive if r["arm"]=="immediate" else passive and r["precheck"]))
    exact = good and msg==len(diverted)
    peak = depth = 0
    for _,delta in sorted([(v[1],1) for v in sent.values()]+[(v[1],-1) for v in ref.values()]):
        depth += delta
        peak = max(depth,peak)
    latency = sorted((t-sent[k][1])/1e6 for k,(o,t) in ref.items() if k[1]==1 and k in sent)
    return dict(valid=bool(good),exact=bool(exact),released=bool(released),passive=bool(passive),
                witness_exact=good and r["witness_count"]==len(diverted),
                switch_count=msg,reference_count=len(diverted),peak=peak,polls=len(r["polls"]),
                barrier_ms=(r["marks"]["barrier"]-r["marks"]["seal"])/1e6,
                decision_ms=(r["marks"]["decision"]-r["marks"]["seal"])/1e6,
                service_count=len(latency),service_sent=sum(k[1]==1 for k in sent),
                service_p95_ms=latency[int(.95*(len(latency)-1))] if latency else None,
                sensor_cpu_ms=r["sensor_cpu_ns"]/1e6, sensor_bytes=len(r["sensor"])*106)

