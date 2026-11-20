"""Test controller: retain the v6 controller and optionally match the study epoch tag."""
import importlib.util
from pathlib import Path
file=Path(__file__).resolve().parent.parent/"review_evidence_v6"/"gateway_agent.py"
spec=importlib.util.spec_from_file_location("baseline_gateway",file)
legacy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

class EpochGateway(legacy.Gateway):
    def install(self,dp,cookie,priority,match,port,flags=0):
        tag=self.folder/"versioned_port"
        if priority==100 and tag.exists():
            fields=dict(match.items())
            fields["udp_src"]=int(tag.read_text())
            match=dp.ofproto_parser.OFPMatch(**fields)
        super().install(dp,cookie,priority,match,port,flags)

