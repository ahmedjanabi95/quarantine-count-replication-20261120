"""OS-Ken application controlling one private OpenFlow bridge per process."""
import json
import os
from pathlib import Path
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.ofproto import ofproto_v1_3

COOKIE = 0x613901
class Gateway(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folder = Path(os.environ["REVIEW_GATEWAY_DIR"])
        self.dp = None
        self.pending = {}
        self.last = -1
        self.cookie = 0
        self.worker = hub.spawn(self.poll)

    def barrier(self, dp, tag):
        req = dp.ofproto_parser.OFPBarrierRequest(dp)
        dp.set_xid(req)
        self.pending[req.xid] = tag
        dp.send_msg(req)

    def install(self, dp, cookie, priority, match, port, flags=0):
        p, of = dp.ofproto_parser, dp.ofproto
        inst = [p.OFPInstructionActions(of.OFPIT_APPLY_ACTIONS, [p.OFPActionOutput(port)])]
        dp.send_msg(p.OFPFlowMod(dp, cookie=cookie, priority=priority, match=match, instructions=inst, flags=flags))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def connect(self, ev):
        dp = self.dp = ev.msg.datapath
        self.install(dp, 0, 10, dp.ofproto_parser.OFPMatch(in_port=1, eth_type=0x0800), 2)
        self.barrier(dp, "ready")

    @set_ev_cls(ofp_event.EventOFPBarrierReply, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def confirmed(self, ev):
        tag = self.pending.pop(ev.msg.xid, None)
        if tag is not None:
            (self.folder / ("ack-" + str(tag))).touch()

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def removed(self, ev):
        if ev.msg.cookie >> 16 == COOKIE:
            with (self.folder / "removed.jsonl").open("a") as f:
                f.write(json.dumps({"cookie": ev.msg.cookie, "packets": ev.msg.packet_count, "bytes": ev.msg.byte_count}) + "\n")

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error_msg(self, ev):
        with (self.folder / "errors").open("a") as f:
            f.write(f"{ev.msg.type} {ev.msg.code}\n")

    def poll(self):
        while True:
            hub.sleep(.01)
            request = self.folder / "lease"
            if self.dp is None or not request.exists():
                continue
            seq, active = json.loads(request.read_text())
            if seq == self.last:
                continue
            dp = self.dp
            if active:
                self.cookie = (COOKIE << 16) | seq
                match = dp.ofproto_parser.OFPMatch(in_port=1, eth_type=2048, ip_proto=17, udp_dst=49001)
                self.install(dp, self.cookie, 100, match, 3, dp.ofproto.OFPFF_SEND_FLOW_REM)
            else:
                dp.send_msg(dp.ofproto_parser.OFPFlowMod(dp, cookie=self.cookie, cookie_mask=(1<<64)-1,
                    command=dp.ofproto.OFPFC_DELETE, out_port=dp.ofproto.OFPP_ANY, out_group=dp.ofproto.OFPG_ANY))
            self.last = seq
            self.barrier(dp, seq)

