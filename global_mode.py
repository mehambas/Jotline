"""Optional cmux integration. One watcher per window, no cmux dependency for editing."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

APP = Path(__file__).resolve().with_name('notes.py')
GLOBAL_PANE_WIDTH = 420


def cmux(*args):
    try:
        result = subprocess.run(['cmux', '--json', '--id-format', 'both', *args], capture_output=True,
                                text=True, timeout=15)
    except subprocess.TimeoutExpired as error:
        raise OSError('cmux did not respond') from error
    if result.returncode:
        raise OSError(result.stderr.strip() or result.stdout.strip())
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise OSError('cmux returned an unexpected JSON response: ' + result.stdout[:200]) from error


def runtime(window):
    root = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'jotline'
    root.mkdir(parents=True, exist_ok=True)
    # The window identity is stable across shells in the same cmux window.
    # Including the socket path made --global-stop miss views opened from a
    # different terminal session.
    key = hashlib.sha256(window.encode()).hexdigest()[:16]
    return root / ('global-' + key)


def state_root():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'jotline'


def running(base):
    with base.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def rightmost_pane(panes):
    if not panes:
        raise OSError('No target pane found in the workspace')
    def position(pane):
        frame = pane.get('pixel_frame')
        if not frame:
            raise OSError('cmux did not report pane positions; layout was not changed')
        return (frame['x'] + frame['width'], frame['x'], -frame['y'])
    return max(panes, key=position)


def create_rightmost(window, workspace):
    panes = cmux('list-panes', '--workspace', workspace, '--window', window)['panes']
    target = rightmost_pane(panes)
    return cmux('new-split', 'right', '--workspace', workspace, '--window', window,
                '--surface', target.get('selected_surface_id') or target['selected_surface_ref'], '--focus', 'false')


def _pane_for_surface(panes, surface):
    for pane in panes:
        if surface in pane.get('surface_ids', []) or surface in pane.get('surface_refs', []):
            return pane
    return None


def size_global_pane(window, workspace, surface, width=GLOBAL_PANE_WIDTH):
    """Give a new right-hand global pane a predictable width in terminal pixels."""
    panes = cmux('list-panes', '--workspace', workspace, '--window', window)['panes']
    current = _pane_for_surface(panes, surface)
    if not current or not current.get('pixel_frame'):
        return
    frame = current['pixel_frame']
    delta = round(frame['width'] - width)
    if abs(delta) < 3:
        return
    left = [p for p in panes if p is not current and p.get('pixel_frame') and
            abs(p['pixel_frame']['x'] + p['pixel_frame']['width'] - frame['x']) < 3]
    if not left:
        return
    # The pane immediately to the left absorbs the difference. This keeps the
    # global pane at the same width even when the workspace is resized later.
    cmux('resize-pane', '--workspace', workspace, '--window', window,
         '--pane', left[0]['id'], '-R' if delta > 0 else '-L', '--amount', str(abs(delta)))


def resize_global_pane(window, workspace, surface, collapsed):
    target = 72 if collapsed else GLOBAL_PANE_WIDTH
    size_global_pane(window, workspace, surface, target)


class Watcher:
    def __init__(self, window, path, token):
        self.window, self.path, self.token = window, path, token
        self.seen = set()
        self.errors = {}
        self.surfaces = {}
        self.closed = set()
        self.pane_state = None

    def sync_pane_state(self):
        state_file = self.token.with_suffix('.pane-state')
        if not state_file.exists():
            return
        try:
            state = state_file.read_text().strip()
        except OSError:
            return
        if state not in ('collapsed', 'expanded') or state == self.pane_state:
            return
        collapsed = state == 'collapsed'
        for workspace, surface in list(self.surfaces.items()):
            try:
                resize_global_pane(self.window, workspace, surface, collapsed)
            except (OSError, KeyError):
                pass
        self.pane_state = state

    def tick(self):
        workspaces = cmux('list-workspaces', '--window', self.window)['workspaces']
        for workspace in workspaces:
            ident = workspace.get('id') or workspace['ref']
            if ident in self.seen:
                # A workspace that only contains Jotline's pane no longer has
                # an editor for it. Remove the global surface automatically.
                try:
                    panes = cmux('list-panes', '--workspace', ident, '--window', self.window)['panes']
                    surface = self.surfaces.get(ident)
                    if surface and len(panes) == 1:
                        cmux('close-surface', '--workspace', ident, '--window', self.window,
                             '--surface', surface)
                        self.surfaces.pop(ident, None)
                        self.seen.discard(ident)
                        self.closed.add(ident)
                except (OSError, KeyError):
                    pass
                continue
            if ident in self.closed:
                # A later split makes the workspace usable again.
                try:
                    if len(cmux('list-panes', '--workspace', ident, '--window', self.window)['panes']) > 1:
                        self.closed.discard(ident)
                    else:
                        continue
                except (OSError, KeyError):
                    continue
            # Remote shells cannot execute this machine's Jotline installation.
            if workspace.get('remote', {}).get('enabled'):
                self.seen.add(ident)
                print('Skipped remote workspace: ' + ident, flush=True)
                continue
            if not self.token.exists():
                return
            try:
                created = create_rightmost(self.window, ident)
                # Never create duplicate panes if a later API request fails.
                self.seen.add(ident)
                surface = created.get('surface_id') or created['surface_ref']
                self.surfaces[ident] = surface
                try:
                    size_global_pane(self.window, ident, surface)
                except (OSError, KeyError):
                    # A pane can still be usable when cmux cannot report its
                    # pixel frame (for example while a workspace is animating).
                    pass
                command = shlex.join([sys.executable, str(APP), str(self.path),
                                      '--shared', '--global-token', str(self.token)])
                cmux('respawn-pane', '--workspace', ident, '--window', self.window,
                     '--surface', surface, '--command', command)
            except (OSError, KeyError) as error:
                self.errors[ident] = str(error)
                print('Could not open pane: ' + ident + ': ' + str(error), flush=True)
                # Retry only on explicit restart, not endlessly every two seconds.
                self.seen.add(ident)
        self.sync_pane_state()


def worker(window, path):
    base = runtime(window)
    token = base.with_suffix('.enabled')
    with base.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        watcher = Watcher(window, path, token)
        resume = base.with_suffix('.resume')
        if resume.exists():
            watcher.seen.update(json.loads(resume.read_text()))
            resume.unlink()
        failures = 0
        try:
            while token.exists():
                try:
                    watcher.tick()
                    failures = 0
                    base.with_suffix('.ready').write_text(json.dumps({
                        'panes': len(watcher.seen), 'errors': watcher.errors}))
                except OSError as error:
                    failures += 1
                    print(str(error), flush=True)
                    if failures >= 3:
                        break
                time.sleep(2)
        finally:
            for workspace, surface in list(watcher.surfaces.items()):
                try:
                    cmux('close-surface', '--workspace', workspace, '--window', watcher.window,
                         '--surface', surface)
                except (OSError, KeyError):
                    pass
            token.unlink(missing_ok=True)
            base.with_suffix('.ready').unlink(missing_ok=True)


def dispatch(args):
    if not shutil.which('cmux') or not os.environ.get('CMUX_SOCKET_PATH'):
        raise OSError('-g must be started from a cmux terminal pane. Use jotline or jotline NOTE.md in a regular terminal.')
    if args.global_worker:
        worker(args.global_worker, args.file)
        return
    identity = cmux('identify')
    target = identity.get('caller') or identity.get('focused') or {}
    window = target.get('window_ref')
    if not window:
        raise OSError('No cmux window found; run this command inside cmux.')
    base = runtime(window)
    token = base.with_suffix('.enabled')
    if args.global_stop:
        token.unlink(missing_ok=True)
        # Also retire markers from older releases that included the socket
        # path in their runtime key.
        for stale in state_root().glob('global-*.enabled'):
            stale.unlink(missing_ok=True)
        print('Stopping global mode. The note file is preserved and views will close.')
        return
    if running(base):
        print('Global mode is already open in this cmux window. No duplicate panes were created.')
        return
    # A dedicated global note leaves the existing scratchpad untouched.
    default = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'jotline/scratch.md'
    path = args.file if args.file != default else default.with_name('global.md')
    path = path.expanduser().resolve()
    from shared_note import SharedNote
    probe = SharedNote(path)
    probe.close()
    token.touch()
    ready = base.with_suffix('.ready')
    ready.unlink(missing_ok=True)
    with base.with_suffix('.log').open('a') as log:
        process = subprocess.Popen([sys.executable, str(APP), str(path), '--global-worker', window],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True)
    for _ in range(100):
        if ready.exists():
            status = json.loads(ready.read_text())
            print(f"Global note opened: {path}\nNew workspaces are being watched. Stop: jotline --global-stop")
            if status['errors']:
                print('Some panes could not be opened. Details: ' + str(base.with_suffix('.log')))
            return
        if process.poll() is not None:
            token.unlink(missing_ok=True)
            raise OSError('Global mode could not start. Log: ' + str(base.with_suffix('.log')))
        time.sleep(.1)
    print('Global panes are being prepared in the background. Log: ' + str(base.with_suffix('.log')))
