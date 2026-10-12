"""Conservative, asynchronous Hell strip triage. OCR is not a verified decode.

One recognized ASCII letter or digit keeps a strip. A negative result keeps
the newest preview for that receiver/mode; older *negative* previews expire.
Errors, missing OCR and queue overload retain captures instead of losing them.
"""
import csv
import io
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from sstv_monitor import Gallery, atomic_json


def recognize(path):
    executable = shutil.which('tesseract')
    if not executable:
        raise RuntimeError('OCR unavailable; strip kept')
    result = subprocess.run(
        [executable, str(path), 'stdout', '-l', 'eng', '--psm', '6',
         '-c', 'tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/', 'tsv'],
        capture_output=True, text=True, timeout=8,
        env=dict(os.environ, OMP_THREAD_LIMIT='1'))
    if result.returncode:
        raise RuntimeError('OCR failed; strip kept')
    tokens = []
    reader = csv.DictReader(io.StringIO(result.stdout), delimiter='\t')
    if not reader.fieldnames or not {'text', 'conf'} <= set(reader.fieldnames):
        raise RuntimeError('Invalid OCR output; strip kept')
    for row in reader:
        token = row.get('text') or ''
        # PSM 6 will invent long strings from static at confidence zero. A
        # deliberately low floor rejects these, without requiring a word/call.
        if float(row.get('conf', -1)) >= 20 and re.search('[A-Za-z0-9]', token):
            tokens.append(token)
    return ' '.join(tokens)[:300]


class HellGallery(Gallery):
    def __init__(self, root):
        super().__init__(root)
        for row in self.items:
            if row.get('ocr_status') == 'pending':
                self.annotate(row['id'], ocr_status='unchecked',
                              ocr_detail='OCR interrupted; strip kept')
        self.pending = queue.Queue(maxsize=42)
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self.run, name='hell-ocr', daemon=True)
        self.worker.start()

    def display_path(self, key):
        from hell_palette import display_path
        return display_path(self.image_path(key))

    def annotate(self, key, **values):
        with self.lock:
            row = next((r for r in self.items if r['id'] == key), None)
            if row is None:
                return
            row.update(values)
            row['updated_ns'] = time.time_ns()
            atomic_json(self.root/(key+'.json'), row)

    def classify(self, key):
        self.annotate(key, ocr_status='pending')
        try:
            self.pending.put_nowait(key)
        except queue.Full:
            self.annotate(key, ocr_status='unchecked', ocr_detail='OCR busy; strip kept')

    def complete(self, key, text):
        with self.lock:
            self.annotate(key, ocr_status='possible_text' if text else 'no_text',
                          ocr_text=text, kind='saved' if text else 'preview')
            row = next((r for r in self.items if r['id'] == key), None)
            if row is None:
                return
            # Only post-update, OCR-negative previews may expire. Existing
            # archives, candidates and unclassified strips are never removed here.
            previews = [r for r in self.items if r.get('ocr_status') == 'no_text'
                        and (r['session_id'], r['mode']) == (row['session_id'], row['mode'])]
            previews.sort(key=lambda r: r.get('received_at', 0), reverse=True)
            for old in previews[1:]:
                self.image_path(old['id']).unlink(missing_ok=True)
                (self.root/(old['id']+'.json')).unlink(missing_ok=True)
                self.items.remove(old)

    def run(self):
        while not self.stopping.is_set():
            try:
                key = self.pending.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                text = recognize(self.image_path(key))
                self.complete(key, text)
            except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
                self.annotate(key, ocr_status='unchecked', ocr_detail='OCR unavailable or timed out; strip kept')
            finally:
                self.pending.task_done()

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=9)
        # Unfinished work remains as saved strips and is visible after restart.
