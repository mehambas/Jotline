"""Shared views use cooperative locks and compare-before-write, never last-writer-wins."""
import fcntl
import os
import tempfile
from pathlib import Path


class SharedNote:
    shared = True

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_name(self.path.name + '.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise OSError('This file is open in a normal Jotline view; close that view first.')
        try:
            self.write_lock = self.path.with_name(self.path.name + '.write.lock').open('a')
        except OSError:
            self.lock.close()
            raise
        self.conflict_path = None
        self.conflict_saved = False
        self.last_bytes = None
        self.text = ''
        try:
            self.refresh()
        except Exception:
            self.close()
            raise

    def refresh(self):
        current = self.path.read_bytes() if self.path.exists() else None
        text = current.decode('utf-8') if current is not None else ''
        changed = current != self.last_bytes
        self.last_bytes, self.text = current, text
        return changed

    def save(self, text):
        from notes import NoteFile
        if self.conflict_path:
            self.conflict_saved = False
            with self.conflict_path.open('w', encoding='utf-8') as draft:
                draft.write(text)
                draft.flush()
                os.fsync(draft.fileno())
            self.conflict_saved = True
            raise OSError('Draft preserved at ' + str(self.conflict_path) + ' · press Ctrl+Q and reopen')
        fcntl.flock(self.write_lock, fcntl.LOCK_EX)
        try:
            current = self.path.read_bytes() if self.path.exists() else None
            if current != self.last_bytes:
                # Keep the local draft durably before allowing the UI to refresh.
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                        dir=self.path.parent, prefix=self.path.stem + '-conflict-',
                        suffix='.md', delete=False) as draft:
                    draft.write(text)
                    draft.flush()
                    os.fsync(draft.fileno())
                    name = draft.name
                self.conflict_path = Path(name)
                self.conflict_saved = True
                raise OSError('Concurrent change: local draft preserved at ' + name + ' · reopen to continue')
            NoteFile.save(self, text)
            self.text = text
        finally:
            fcntl.flock(self.write_lock, fcntl.LOCK_UN)

    def close(self):
        self.write_lock.close()
        self.lock.close()
