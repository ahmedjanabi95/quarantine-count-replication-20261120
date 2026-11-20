"""Bounded two-session functional validation. Run as root in the local WSL testbed."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import select
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import zlib

HERE = Path(__file__).resolve().parent
MANAGER = os.environ.get("OSKEN_MANAGER", "/opt/ids-venv/bin/osken-manager")
def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=8).strip()

def until(flag):
    stop = time.monotonic()+8
    while not flag.exists():
        if time.monotonic()>stop:
            raise RuntimeError("missing controller acknowledgement " + str(flag))
        time.sleep(.01)

def frame(seq, session):
    payload = struct.pack("!HBB",seq,session,0)+bytes(60)
    udp = struct.pack("!HHHH",43110,49001+session,72,0)+payload
    header = struct.pack("!BBHHHBBH4s4s",69,0,92,seq,0,64,17,0,socket.inet_aton("192.0.2.1"),socket.inet_aton("192.0.2.2"))
    csum=sum(struct.unpack("!10H",header))
    while csum>65535: csum=(csum&65535)+(csum>>16)
    return bytes.fromhex("0200000000020200000000010800")+header[:10]+struct.pack("!H",65535-csum)+header[12:]+udp

class PortGroup:
    def __init__(self, index, scope, parent):
        self.folder=parent/str(index)
        self.folder.mkdir()
        br=self.bridge=f"rv6{os.getpid()}g{index}"
        command("ovs-vsctl","add-br",br)
        scope.callback(command,"ovs-vsctl","--if-exists","del-br",br)
        command("ovs-vsctl","set","bridge",br,"protocols=OpenFlow13","fail_mode=secure")
        self.ports=[]
        for num in range(1,4):
            side,peer=br+str(num)+"s",br+str(num)+"p"
            command("ip","link","add",side,"type","veth","peer","name",peer)
            scope.callback(command,"ip","link","del",side)
            for dev in [side,peer]:
                command("ip","link","set",dev,"up")
            command("ovs-vsctl","add-port",br,side,"--","set","interface",side,"ofport_request="+str(num))
            sock=scope.enter_context(socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x0800)))
            sock.bind((peer,0))
            self.ports.append(sock)
        port=29741+index
        lf=scope.enter_context((self.folder/"controller.log").open("w"))
        self.process=subprocess.Popen([MANAGER,"--ofp-listen-host","127.0.0.1","--ofp-tcp-listen-port",str(port),str(HERE/"gateway_agent.py")],
                    env={**os.environ,"REVIEW_GATEWAY_DIR":str(self.folder)},stdout=lf,stderr=lf)
        scope.callback(self.shutdown)
        command("ovs-vsctl","set-controller",br,"tcp:127.0.0.1:"+str(port))
        until(self.folder/"ack-ready")
        self.epoch=0

    def shutdown(self):
        self.process.terminate()
        try:self.process.wait(3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def change(self, active):
        self.epoch+=1
        tmp=self.folder/"next"
        tmp.write_text(json.dumps([self.epoch,active]))
        tmp.replace(self.folder/"lease")
        until(self.folder/f"ack-{self.epoch}")
        if (self.folder/"errors").exists():raise RuntimeError("OpenFlow error")

    def deliver(self,seq,session):
        packet=frame(seq,session)
        self.ports[0].send(packet)
        ready,_,_=select.select(self.ports[1:],[],[],1)
        if len(ready)!=1 or ready[0].recv(2048)!=packet:
            raise RuntimeError("unexpected disposition of tagged probe")
        return "service" if ready[0]==self.ports[1] else "quarantine"

    def counters(self):
        log=self.folder/"removed.jsonl"
        return [json.loads(line)["packets"] for line in log.read_text().splitlines()] if log.exists() else []

    def snapshot(self):
        cookie=(0x613901 << 16) | self.epoch
        raw=command("ovs-ofctl","-O","OpenFlow13","dump-flows",self.bridge,f"cookie={cookie:#x}/-1")
        matches=re.findall(r"n_packets=(\d+)",raw)
        if len(matches)!=1: raise RuntimeError("missing unique lease in switch snapshot: "+raw)
        return int(matches[0])

def trial(agents,seed,mobile,policy):
    before=[len(a.counters()) for a in agents]
    records=[]
    snapshots=[]
    p=subprocess.Popen([str(HERE/"mobile"),"--seed="+str(seed),"--mobile="+str(int(mobile))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    try:
        for line in p.stdout:
            fields=line.split()
            if not fields:continue
            record=fields[:]
            if fields[0]=="LEASE":
                targets={"forward":[],"primary":[0],"replicated":[0,1]}[policy]
                if fields[1]=="0" and targets:
                    start=time.monotonic()
                    for delay in (0,.25,1.25,2.5):
                        time.sleep(max(0,start+delay-time.monotonic()))
                        snapshots.append({"seconds":time.monotonic()-start,"counts":[agents[i].snapshot() for i in targets]})
                for idx in targets:agents[idx].change(int(fields[1]))
                response=1
            elif fields[0]=="RX":
                _,t,g,seq,session=fields
                disposition=agents[int(g)].deliver(int(seq),int(session))
                record.append(disposition)
                response=int(disposition=="service")
            else:response=None
            records.append(record)
            if response is not None:
                p.stdin.write(str(response)+"\n");p.stdin.flush()
        if p.wait(5) or not records or records[-1]!=["END"]:raise RuntimeError("incomplete simulator stream")
    finally:
        if p.poll() is None:p.kill();p.wait()
        p.stdin.close();p.stdout.close()
    return {"seed":seed,"mobile":mobile,"policy":policy,"events":records,
            "snapshots":snapshots,"removed_counts":[a.counters()[k:] for a,k in zip(agents,before)]}

def main():
    import random
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path)
    parser.add_argument("--pilot",action="store_true")
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    seeds=[200] if args.pilot else list(range(301,306))
    plan=[(s,m,p) for s in seeds for m in [False,True] for p in ["forward","primary","replicated"]]
    random.Random(611).shuffle(plan)
    manifest={"plan":plan,"versions":{"ovs":command("ovs-vsctl","--version"),"ns3":command("pkg-config","--modversion","ns3-wifi"),"osken":command(MANAGER,"--version")},"hashes":{n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ["mobile","mobile.cc","wireless_trial.py","gateway_agent.py"]},"trials":[]}
    registry=args.output/"manifest.json"
    registry.write_text(json.dumps(manifest,indent=2))
    with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as scope:
        tmp=Path(tmp)
        try:
            agents=[PortGroup(i,scope,tmp) for i in range(2)]
            for seed,mobile,policy in plan:
                row=trial(agents,seed,mobile,policy)
                name=f"{seed}_{int(mobile)}_{policy}.json"
                (args.output/name).write_text(json.dumps(row))
                manifest["trials"].append(name)
                registry.write_text(json.dumps(manifest,indent=2))
        finally:
            for i in range(2):
                for log in ("controller.log","errors","removed.jsonl"):
                    f=tmp/str(i)/log
                    if f.exists():shutil.copyfile(f,args.output/f"gateway{i}_{log}")
if __name__=="__main__":main()

