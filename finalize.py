"""Audit saved evidence; never manufacture test results or gameplay claims."""
from pathlib import Path
import runpy
if __name__=='__main__':
    runpy.run_path(str(Path(__file__).resolve().parent/'evaluations/audit_evidence.py'),run_name='__main__')
