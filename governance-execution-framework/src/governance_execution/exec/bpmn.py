"""Generate executable BPMN 2.0 (with diagram) from a step list, so the workflow in Cockpit is the same list the
Direct_Adapter would run. Service steps are external tasks (topic = step name); user steps are user tasks.
Consecutive service steps sharing ``group`` run between a parallel split and join."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import quoteattr

HISTORY_TTL_DAYS = 30


@dataclass(frozen=True)
class WfStep:
    """One workflow step. Service steps become external tasks (topic = ``name``); user steps become user tasks."""
    name: str                      # BPMN element id, external-task topic, and step name (letters, digits, underscore)
    label: str = ""
    kind: str = "service"          # service | user
    group: Optional[str] = None    # parallel group (service steps only)
    candidate_group: str = "reviewers"


@dataclass(frozen=True)
class Workflow:
    """Immutable workflow definition: process key, display name and ordered steps."""
    key: str                       # process definition key
    name: str
    steps: tuple[WfStep, ...]

    def fingerprint(self) -> str:
        """First 12 hex chars of the SHA-256 of the generated BPMN XML; changes whenever the diagram or steps change."""
        return hashlib.sha256(xml_for(self).encode()).hexdigest()[:12]


def _batches(steps: tuple[WfStep, ...]) -> list[list[WfStep]]:
    """Group steps for layout: consecutive steps with the same non-empty ``group`` form one parallel batch; every other step is its own batch."""
    out: list[list[WfStep]] = []
    for s in steps:
        if s.group and out and out[-1][0].group == s.group:
            out[-1].append(s)
        else:
            out.append([s])
    return out


def _q(s: str) -> str:
    """XML-attribute-quote ``s`` (adds quotes and escapes special characters)."""
    return quoteattr(s)


def xml_for(wf: Workflow) -> str:
    """Render the workflow as BPMN 2.0 XML with diagram interchange (shapes and edges) in one deterministic string."""
    el: list[str] = []          # process elements
    flows: list[tuple[str, str, str]] = []   # (id, source, target)
    shapes: list[str] = []
    edges: list[str] = []
    pos: dict[str, tuple[int, int, int, int]] = {}   # id -> x, y, w, h
    X0, Y0, STEP, ROW = 160, 120, 190, 110

    def put(i: str, x: int, y: int, w: int, h: int) -> None:
        """Record the diagram bounds (x, y, width, height) of element ``i``."""
        pos[i] = (x, y, w, h)

    def link(a: str, b: str) -> None:
        """Add a sequence flow a -> b with the id ``f_<a>__<b>``."""
        flows.append((f"f_{a}__{b}", a, b))

    put("start", X0 - 100, Y0 + 22, 36, 36)
    el.append('<bpmn:startEvent id="start" name="Start"/>')
    prev, x = "start", X0
    for bi, batch in enumerate(_batches(wf.steps)):
        def node(s: WfStep, nx: int, ny: int) -> None:
            """Emit one step as a user task or external service task and place it at (nx, ny)."""
            lab = s.label or s.name
            if s.kind == "user":
                el.append(f'<bpmn:userTask id="{s.name}" name={_q(lab)} camunda:candidateGroups="{s.candidate_group}"/>')
            else:
                el.append(f'<bpmn:serviceTask id="{s.name}" name={_q(lab)} camunda:type="external" camunda:topic="{s.name}"/>')
            put(s.name, nx, ny, 120, 80)

        if len(batch) == 1:
            node(batch[0], x, Y0)
            link(prev, batch[0].name)
            prev = batch[0].name
            x += STEP
        else:
            split, join = f"split_{bi}", f"join_{bi}"
            el.append(f'<bpmn:parallelGateway id="{split}"/>')
            el.append(f'<bpmn:parallelGateway id="{join}"/>')
            put(split, x, Y0 + 15, 50, 50)
            link(prev, split)
            for k, s in enumerate(batch):
                node(s, x + 110, Y0 - 55 + k * ROW)
                link(split, s.name)
                link(s.name, join)
            put(join, x + 110 + 120 + 50, Y0 + 15, 50, 50)
            prev = join
            x += STEP + 190
    el.append('<bpmn:endEvent id="end" name="End"/>')
    put("end", x, Y0 + 22, 36, 36)
    link(prev, "end")

    outs: dict[str, list[str]] = {}
    ins: dict[str, list[str]] = {}
    for fid, a, b in flows:
        outs.setdefault(a, []).append(fid)
        ins.setdefault(b, []).append(fid)
    body: list[str] = []
    for line in el:
        i = line.split('id="')[1].split('"')[0]
        io = "".join(f"<bpmn:incoming>{f}</bpmn:incoming>" for f in ins.get(i, [])) + \
             "".join(f"<bpmn:outgoing>{f}</bpmn:outgoing>" for f in outs.get(i, []))
        body.append(line[:-2] + f">{io}</{line[1:].split()[0]}>" if line.endswith("/>") else line)
    seq = "".join(f'<bpmn:sequenceFlow id="{f}" sourceRef="{a}" targetRef="{b}"/>' for f, a, b in flows)
    for i, (px, py, w, h) in pos.items():
        shapes.append(f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}"><dc:Bounds x="{px}" y="{py}" width="{w}" height="{h}"/></bpmndi:BPMNShape>')
    for fid, a, b in flows:
        ax, ay, aw, ah = pos[a]
        bx, by, bw, bh = pos[b]
        pts = [(ax + aw, ay + ah // 2)]
        if ay != by:
            pts.append((bx - 20, ay + ah // 2))
            pts.append((bx - 20, by + bh // 2))
        pts.append((bx, by + bh // 2))
        edges.append(f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">' +
                     "".join(f'<di:waypoint x="{px}" y="{py}"/>' for px, py in pts) + "</bpmndi:BPMNEdge>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
        'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:camunda="http://camunda.org/schema/1.0/bpmn" '
        f'id="defs_{wf.key}" targetNamespace="http://agip/bpmn">'
        f'<bpmn:process id="{wf.key}" name={_q(wf.name)} isExecutable="true" camunda:historyTimeToLive="{HISTORY_TTL_DAYS}">'
        + "".join(body) + seq + "</bpmn:process>"
        f'<bpmndi:BPMNDiagram id="diagram_{wf.key}"><bpmndi:BPMNPlane id="plane_{wf.key}" bpmnElement="{wf.key}">'
        + "".join(shapes) + "".join(edges) + "</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
    )
