"""Bounded EMS document scan; file names are evidence of presence, not signing."""
from pathlib import Path
import os
import re
import stat
import time

PATTERNS = {
    'Initial Scope': r'^(?!.*\bfinal\b).*\bscope\b',
    'Final Scope': r'\bfinal\b.*\bscope\b|\bscope\b.*\bfinal\b',
    'State Farm — Authorization to Perform (28000)': r'\b28000\b',
    'State Farm — Authorization to Pay': r'^(?!.*(?:auth\w*.*perform|\b28000\b)).*(?:(?:state[ _-]*farm|\b(?:sf|st)\b).*(?:auth\w*.*pay|\batp\b)|(?:auth\w*.*pay|\batp\b).*(?:state[ _-]*farm|\b(?:sf|st)\b))',
    'State Farm — Authorization to Repair (ATR California)': r'\batr\b|auth\w*.*repair',
    'State Farm — Certificate of Satisfaction (28531)': r'\b28531\b',
    'State Farm Warranty Form': r'(?:state[ _-]*farm|\bsf\b).*warrant|warrant.*state[ _-]*farm',
    'Home Improvement Contract': r'home[ _-]*improv|\bhic\b|\blong[ -]*form[ -]*contract\b',
    'Credit Card Authorization': r'\b(?:credit[ -]*card|cc)[ -]*auth(?:orization|orisation)?\b',
    'Change Order': r'\bchange[ -]*order\b',
    '3 Day Right to Cancel': r'right[ _-]*to[ _-]*cancel|\brtc\b|(?:3|three)[ _-]*day.*cancel',
}


def is_document_candidate(filename):
    """Filename eligibility only; never proof of signing or completion."""
    path = Path(filename)
    return (path.suffix.lower() in ('.pdf', '.doc', '.docx') and
            not re.search(r'\b(blank|template|unsigned|draft)\b',
                          path.stem.replace('_', ' '), re.I))


def _is_link(path):
    """Do not follow Windows junctions or symlinks outside the verified job."""
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) &
                                     getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def scan(job_folder):
    if not job_folder:
        return {}
    root = Path(job_folder)
    ems = root if root.name.upper() == 'EMS' else root / 'EMS'
    try:
        if _is_link(ems):
            return {}
        deadline = time.monotonic() + 5
        entries = list(ems.iterdir())
        docs = next((p for p in entries if p.name.upper() == 'DOCS'), None)
        if docs and (_is_link(docs) or not docs.is_dir()):
            return {}
        files = [p for p in entries if p.is_file() and not _is_link(p)]
        if docs:
            # Check common document subfolders, but never follow a shortcut or
            # junction into another job. Keep the network scan bounded.
            pending = [(docs, 0)]
            visited = 0
            while pending:
                folder, depth = pending.pop()
                with os.scandir(folder) as items:
                    for entry in items:
                        visited += 1
                        if visited > 5000 or time.monotonic() > deadline:
                            return {}  # Incomplete is not a clean scan.
                        if entry.is_file(follow_symlinks=False):
                            files.append(Path(entry.path))
                        elif depth < 2 and entry.is_dir(follow_symlinks=False):
                            path = Path(entry.path)
                            if not _is_link(path):
                                pending.append((path, depth + 1))
    except OSError:
        return {}  # Unavailable is not an empty successful scan.
    files = [p for p in files if is_document_candidate(p)]
    from audit_logic import REQUIRED_FORMS
    patterns = {**dict(REQUIRED_FORMS), **PATTERNS}
    # 28000 and 28001 are the company's authorization-to-perform form IDs.
    patterns['Auth to Perform'] = r'auth\w*.*perform|\batp\b|\b2800[01]\b'
    def matches(label, pattern, path):
        name = path.stem.replace('_', ' ')
        if label == 'Auth to Perform' and re.search(r'auth\w*.*\bpay\b', name, re.I) and not re.search(r'auth\w*.*perform|\b2800[01]\b', name, re.I):
            return False  # Authorization to Pay is a distinct State Farm form.
        return bool(re.search(pattern, name, re.I))
    return {label: {'checked': True, 'files': [str(p) for p in files if matches(label, pattern, p)]}
            for label, pattern in patterns.items()}
