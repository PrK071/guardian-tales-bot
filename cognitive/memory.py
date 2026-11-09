from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import hashlib, json, os, sqlite3, threading, time
from .contracts import Observation, Provenance, State, Task, now, uid

def encode(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False)

class Memory:
    """One locked connection, explicit transactions, atomic operation journal.

    SQLite corruption is reported; never silently discard a damaged database.
    """
    def __init__(self,path: Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(str(self.path),timeout=5,check_same_thread=False,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        try: self._initialize()
        except BaseException: self.db.close(); raise
    def _initialize(self):
        self.db.execute('PRAGMA foreign_keys=ON'); self.db.execute('PRAGMA busy_timeout=5000')
        # This portable runtime ships SQLite 3.49.1. Use rollback journal + FULL
        # rather than depending on WAL behavior of a newer SQLite distribution.
        self.db.execute('PRAGMA journal_mode=DELETE'); self.db.execute('PRAGMA synchronous=FULL')
        result=self.db.execute('PRAGMA quick_check').fetchone()[0]
        if result!='ok': raise RuntimeError('Memory integrity check failed: '+result)
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0,1): raise RuntimeError('Unsupported memory schema: '+str(version))
        with self.tx() as db:
            for sql in (
                'CREATE TABLE IF NOT EXISTS goals(id TEXT PRIMARY KEY,title TEXT NOT NULL,scope TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL)',
                'CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,goal_id TEXT NOT NULL REFERENCES goals(id),kind TEXT NOT NULL,state TEXT NOT NULL,scope TEXT NOT NULL,data TEXT NOT NULL,updated REAL NOT NULL)',
                'CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,scope TEXT NOT NULL,data TEXT NOT NULL,created REAL NOT NULL)',
                'CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY,category TEXT NOT NULL,kind TEXT NOT NULL,scope TEXT NOT NULL,confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),validation TEXT NOT NULL,provenance TEXT NOT NULL,content TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,dedupe TEXT UNIQUE)',
                'CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,goal_id TEXT NOT NULL,task_id TEXT NOT NULL,state TEXT NOT NULL,action TEXT NOT NULL,before_id TEXT NOT NULL,after_id TEXT,result TEXT,created REAL NOT NULL,updated REAL NOT NULL)',
                'CREATE TABLE IF NOT EXISTS checkpoints(goal_id TEXT PRIMARY KEY REFERENCES goals(id),observation_id TEXT NOT NULL REFERENCES observations(id),data TEXT NOT NULL,updated REAL NOT NULL)',
                'CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,data TEXT NOT NULL,expires REAL NOT NULL)',
                'CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL)',
                'CREATE INDEX IF NOT EXISTS memory_context ON memories(category,scope,kind,validation)',
                'CREATE INDEX IF NOT EXISTS task_context ON tasks(goal_id,state)',
                'CREATE INDEX IF NOT EXISTS observation_context ON observations(scope,created)',
            ): db.execute(sql)
            db.execute('PRAGMA user_version=1')
    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try: yield self.db; self.db.execute('COMMIT')
            except BaseException: self.db.execute('ROLLBACK'); raise
    def close(self):
        with self.lock: self.db.close()
    def backup(self,path: Path):
        path=Path(path)
        if path.resolve()==self.path.resolve(): raise ValueError('Backup must be another file')
        with self.lock:
            destination=sqlite3.connect(str(path))
            try: self.db.backup(destination)
            finally: destination.close()
    def goal(self,title: str,scope='story') -> str:
        with self.tx() as db:
            row=db.execute("SELECT id FROM goals WHERE title=? AND scope=? AND state NOT IN ('completed','failed') ORDER BY created DESC LIMIT 1",(title,scope)).fetchone()
            if row: return row['id']
            id=uid('goal'); db.execute('INSERT INTO goals VALUES(?,?,?,?,?,?)',(id,title,scope,'pending',now(),now())); return id
    def goals(self):
        with self.lock: return [dict(r) for r in self.db.execute('SELECT * FROM goals ORDER BY updated DESC LIMIT 20')]
    def goal_state(self,id,state):
        if state not in set(State): raise ValueError('Invalid state')
        with self.tx() as db: db.execute('UPDATE goals SET state=?,updated=? WHERE id=?',(state,now(),id))
    def save_task(self,task: Task):
        task.updated_at=now(); data=encode(task.to_dict())
        with self.tx() as db:
            existing=db.execute('SELECT goal_id FROM tasks WHERE id=?',(task.id,)).fetchone()
            if existing and existing['goal_id']!=task.goal_id:raise ValueError('A task cannot change its owning goal')
            graph={row['id']:json.loads(row['data'])['dependencies'] for row in db.execute('SELECT id,data FROM tasks WHERE goal_id=?',(task.goal_id,))}
            if any(dependency not in graph for dependency in task.dependencies): raise ValueError('Missing or cross-goal task dependency')
            graph[task.id]=task.dependencies
            def visit(node,path):
                if node in path: raise ValueError('Cyclic task dependencies')
                for dependency in graph[node]: visit(dependency,path|{node})
            visit(task.id,set())
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,state=excluded.state,scope=excluded.scope,data=excluded.data,updated=excluded.updated',
                       (task.id,task.goal_id,task.kind,task.state,task.scope,data,task.updated_at))
    def tasks(self,goal_id: str) -> list[Task]:
        with self.lock: return [Task(**json.loads(r[0])) for r in self.db.execute('SELECT data FROM tasks WHERE goal_id=? ORDER BY rowid',(goal_id,))]
    def observe(self,ob: Observation):
        with self.tx() as db: db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?)',(ob.id,ob.scope,encode(ob.to_dict()),ob.at))
    def observation(self,id: str) -> Observation | None:
        with self.lock: row=self.db.execute('SELECT data FROM observations WHERE id=?',(id,)).fetchone()
        return Observation.from_dict(json.loads(row[0])) if row else None
    def remember(self,category,kind,scope,content,provenance: Provenance,confidence=.5,validation='hypothesis',dedupe=None):
        if category not in ('working','episodic','semantic'): raise ValueError('Invalid memory category')
        if validation not in ('hypothesis','reported','verified','contradicted','uncertain'): raise ValueError('Invalid validation')
        if not 0<=confidence<=1: raise ValueError('Invalid confidence')
        id=uid('memory'); stamp=now()
        with self.tx() as db:
            db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(dedupe) DO UPDATE SET scope=excluded.scope,content=excluded.content,confidence=excluded.confidence,validation=excluded.validation,provenance=excluded.provenance,updated=excluded.updated',
                (id,category,kind,scope,confidence,validation,encode(asdict(provenance)),encode(content),stamp,stamp,dedupe))
            if dedupe: id=db.execute('SELECT id FROM memories WHERE dedupe=?',(dedupe,)).fetchone()[0]
        return id
    def retrieve(self,scope,category=None,kind=None,limit=8,include_global=True):
        clauses=['(scope=?'+(' OR scope IN (\'global\',\'story\')' if include_global else '')+')']; params=[scope]
        if category: clauses.append('category=?'); params.append(category)
        if kind: clauses.append('kind=?'); params.append(kind)
        params.extend([scope,min(50,max(1,limit))])
        with self.lock:
            rows=self.db.execute('SELECT * FROM memories WHERE '+' AND '.join(clauses)+' ORDER BY CASE WHEN scope=? THEN 0 ELSE 1 END,updated DESC LIMIT ?',params).fetchall()
        out=[]
        for row in rows:
            data=dict(row)
            for key in ('content','provenance'): data[key]=json.loads(data[key])
            out.append(data)
        return out
    def checkpoint(self,goal_id,ob: Observation,data):
        self.observe(ob)
        with self.tx() as db: db.execute('INSERT INTO checkpoints VALUES(?,?,?,?) ON CONFLICT(goal_id) DO UPDATE SET observation_id=excluded.observation_id,data=excluded.data,updated=excluded.updated',(goal_id,ob.id,encode(data),now()))
    def load_checkpoint(self,goal_id):
        with self.lock: row=self.db.execute('SELECT * FROM checkpoints WHERE goal_id=?',(goal_id,)).fetchone()
        return {**dict(row),'data':json.loads(row['data'])} if row else None
    def prepare(self,goal_id,task_id,action,before_id):
        id=uid('operation')
        with self.tx() as db:
            if not db.execute('SELECT 1 FROM tasks WHERE id=? AND goal_id=?',(task_id,goal_id)).fetchone() or not db.execute('SELECT 1 FROM observations WHERE id=?',(before_id,)).fetchone():raise ValueError('Operation requires an existing task and observation')
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?)',(id,goal_id,task_id,'prepared',encode(action),before_id,None,None,now(),now()))
        return id
    def operation(self,id,state,after_id=None,result=None):
        if state not in ('issued','observed','failed','uncertain'): raise ValueError('Invalid operation state')
        with self.tx() as db: db.execute('UPDATE operations SET state=?,after_id=?,result=?,updated=? WHERE id=?',(state,after_id,encode(result) if result is not None else None,now(),id))
    def unresolved(self,goal_id):
        with self.lock: return [dict(r) for r in self.db.execute("SELECT * FROM operations WHERE goal_id=? AND state IN ('prepared','issued','uncertain')",(goal_id,))]
    def cached(self,key):
        with self.lock: row=self.db.execute('SELECT data FROM cache WHERE key=? AND expires>?',(key,now())).fetchone()
        return json.loads(row[0]) if row else None
    def cache(self,key,data,ttl=86400):
        with self.tx() as db: db.execute('INSERT INTO cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data,expires=excluded.expires',(key,encode(data),now()+ttl))
    def acquire(self,owner,ttl=60):
        with self.tx() as db:
            row=db.execute("SELECT owner,expires FROM leases WHERE name='executor'").fetchone()
            if row and row['owner']!=owner and row['expires']>now(): return False
            db.execute("INSERT INTO leases VALUES('executor',?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires=excluded.expires",(owner,now()+ttl)); return True
    def release(self,owner):
        with self.tx() as db: db.execute("DELETE FROM leases WHERE name='executor' AND owner=?",(owner,))
    def summary(self):
        with self.lock:
            counts={table:self.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('goals','tasks','observations','memories','operations')}
            integrity=self.db.execute('PRAGMA quick_check').fetchone()[0]
        return {'counts':counts,'integrity':integrity,'schema':1,'database':str(self.path)}
