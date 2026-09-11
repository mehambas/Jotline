"""Optional cmux focus and pane sizing; the editor remains terminal-independent."""
import os
from global_mode import cmux


class PaneController:
    def __init__(self):
        self.enabled = bool(os.environ.get('CMUX_SURFACE_ID'))
        self.original_width = None

    def identity(self):
        result = cmux('identify')
        caller = result.get('caller') or {}
        if not caller.get('surface_id'):
            raise OSError("Jotline's cmux pane was not found")
        return caller, result.get('focused') or {}

    def focused(self):
        caller, focused = self.identity()
        return caller['surface_id'] == focused.get('surface_id')

    def toggle(self, collapsed):
        caller, _ = self.identity()
        workspace, window = caller['workspace_id'], caller['window_id']
        def panes():
            return cmux('list-panes', '--workspace', workspace, '--window', window)['panes']
        all_panes = panes()
        current = next(p for p in all_panes if caller['surface_id'] in p.get('surface_ids', []))
        frame = current['pixel_frame']
        width = frame['width']
        target = (self.original_width or 500) if collapsed else 72
        delta = target - width
        if abs(delta) < 2:
            raise OSError('The pane cannot be resized any further')
        adjacent = []
        for other in all_panes:
            if other['id'] == current['id']:
                continue
            f = other['pixel_frame']
            overlaps = min(f['y'] + f['height'], frame['y'] + frame['height']) > max(f['y'], frame['y'])
            if overlaps and abs(f['x'] + f['width'] - frame['x']) < 3:
                adjacent.append((other, '-L', '-R'))
            elif overlaps and abs(frame['x'] + width - f['x']) < 3:
                adjacent.append((other, '-R', '-L'))
        if not adjacent:
            raise OSError('A horizontal neighboring pane is required for resizing')
        neighbor, grow_self, grow_neighbor = adjacent[0]
        # cmux only grows toward an adjacent border. To shrink us, grow our neighbor.
        target_pane = current if delta > 0 else neighbor
        direction = grow_self if delta > 0 else grow_neighbor
        cmux('resize-pane', '--workspace', workspace, '--window', window,
             '--pane', target_pane['id'], direction, '--amount', str(max(1, round(abs(delta)))))
        actual = next(p for p in panes() if p['id'] == current['id'])['pixel_frame']['width']
        if (actual - width) * delta <= 0:
            raise OSError('This pane layout does not support resizing')
        if not collapsed:
            self.original_width = width
        return not collapsed
