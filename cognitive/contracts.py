from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import StrEnum
from typing import Any, Protocol
import math, time, uuid

def uid(prefix: str) -> str: return prefix+'_'+uuid.uuid4().hex[:16]
def now() -> float: return time.time()

class State(StrEnum):
    PENDING='pending'
    RUNNING='running'
    INTERRUPTED='interrupted'
    BLOCKED='blocked'
    COMPLETED='completed'
    FAILED='failed'
    REPLANNED='replanned'

@dataclass
class Provenance:
    source: str
    captured_at: float = field(default_factory=now)
    method: str = 'observation'
    evidence_ids: list[str] = field(default_factory=list)

@dataclass
class Observation:
    id: str
    at: float
    scene: str
    confidence: float
    scope: str
    stage: str | None
    text: str
    features: dict[str, Any]
    frame_path: str | None = None
    blocked: str | None = None
    provenance: Provenance = field(default_factory=lambda: Provenance('android:screencap'))
    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, data):
        data=dict(data); data['provenance']=Provenance(**data['provenance']); return cls(**data)

@dataclass
class Action:
    op: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ''
    def validate(self) -> None:
        allowed={'move','attack','skill','interact','tap','text','wait','observe'}
        if self.op not in allowed: raise ValueError('Unsupported action: '+self.op)
        def finite(name,low,high,default=None):
            value=self.args.get(name,default)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
                raise ValueError('Invalid '+name)
        if self.op=='move' and self.args.get('direction') not in {'up','down','left','right','up_left','up_right','down_left','down_right'}: raise ValueError('Invalid direction')
        if self.op in {'move','attack','skill','interact'}: finite('ms',80,1500,600)
        if self.op=='tap': finite('x',0,1); finite('y',0,1)
        if self.op=='text':
            if not isinstance(self.args.get('text'),str) or not 1<=len(self.args['text'])<=80: raise ValueError('Invalid text target')
        if self.op=='wait': finite('seconds',0,15,1)
        finite('settle',0,5,.3)
        if 'min_similarity' in self.args: finite('min_similarity',0,1)
        if 'anchor' in self.args and (not isinstance(self.args['anchor'],str) or not 1<=len(self.args['anchor'])<=512): raise ValueError('Invalid anchor')
        if 'roi' in self.args:
            roi=self.args['roi']
            if not isinstance(roi,list) or len(roi)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in roi) or roi[0]>=roi[2] or roi[1]>=roi[3]: raise ValueError('Invalid ROI')
        unexpected=set(self.args)-{'direction','ms','x','y','text','seconds','settle','anchor','min_similarity','roi'}
        if unexpected: raise ValueError('Unexpected action arguments: '+str(sorted(unexpected)))
    def legacy(self): self.validate(); return {'op':self.op,**self.args}

@dataclass
class Task:
    id: str
    goal_id: str
    kind: str
    title: str
    scope: str
    state: str = State.PENDING
    parent_id: str | None = None
    preconditions: dict[str, Any] = field(default_factory=dict)
    success: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 3
    recovery: str = 'reobserve_replan_research'
    evidence: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=now)
    def validate(self):
        if self.state not in set(State): raise ValueError('Unknown task state')
        if not 1<=self.max_attempts<=100 or not 0<=self.attempts<=100: raise ValueError('Invalid attempt budget')
        if self.id in self.dependencies: raise ValueError('Self dependency')
        if not self.success: raise ValueError('Task needs a success criterion')
    def to_dict(self): self.validate(); return asdict(self)

@dataclass
class Verdict:
    progressed: bool
    completed: bool
    failure: str | None
    reason: str
    evidence: list[str]
    confidence: float

class Environment(Protocol):
    def observe(self) -> Observation: ...
    def execute(self, action: Action) -> None: ...
    def route_candidates(self, observation: Observation) -> list[dict]: ...

class Advisor(Protocol):
    available: bool
    calls: int
    usage: list[dict[str, Any]]
    def advise(self, context: dict[str, Any]) -> dict[str, Any] | None: ...
