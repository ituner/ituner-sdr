"""LAN digital-mode control, serialized through the application's owner thread."""
import copy
import queue
import threading
import time


class ControlError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class DigitalWebBridge:
    """HTTP workers enqueue commands; only the UI thread changes receivers."""
    def __init__(self):
        self.commands = queue.Queue(maxsize=32)
        self.lock = threading.Lock()
        self.state = {'sstv': [], 'wspr': []}
        self.updated_at = 0
        self.closed = False

    def publish(self, sstv, wspr):
        with self.lock:
            self.state = copy.deepcopy({'sstv': sstv, 'wspr': wspr})
            self.updated_at = time.time()

    def snapshot(self, mode):
        with self.lock:
            return {'decoders': copy.deepcopy(self.state[mode]), 'updated_at': self.updated_at}

    def request(self, mode, key, action, timeout=5):
        if mode not in ('sstv', 'wspr') or action not in ('start', 'stop') or not isinstance(key, str) or not key:
            raise ControlError(400, 'Choose a receiver and Start or Stop')
        with self.lock:
            if self.closed:
                raise ControlError(503, 'The SDR is stopping')
        item = dict(mode=mode, key=key, action=action, deadline=time.monotonic()+timeout,
                    done=threading.Event(), error=None)
        try:
            self.commands.put_nowait(item)
        except queue.Full:
            raise ControlError(503, 'The SDR is busy; try again')
        if not item['done'].wait(timeout):
            raise ControlError(504, 'No confirmation from the SDR; refresh before retrying')
        if item['error']:
            raise item['error']
        return {'ok': True, 'id': key, 'action': action}

    def drain(self, apply):
        """Call on the UI thread; expired commands must never execute later."""
        for _ in range(32):
            try:
                item = self.commands.get_nowait()
            except queue.Empty:
                break
            try:
                if time.monotonic() > item['deadline']:
                    raise ControlError(504, 'Request expired; please retry')
                apply(item['mode'], item['key'], item['action'] == 'start')
            except (KeyError, StopIteration):
                item['error'] = ControlError(404, 'Receiver no longer exists; refresh the page')
            except ControlError as exc:
                item['error'] = exc
            except Exception:
                item['error'] = ControlError(500, 'Could not update the receiver; check the SDR')
            finally:
                item['done'].set()

    def close(self):
        with self.lock:
            self.closed = True
        def reject(*args):
            raise ControlError(503, 'The SDR is stopping')
        self.drain(reject)


def wspr_snapshot(tiles, manager):
    """Bounded JSON-ready state; omit waterfall buffers and large graph history."""
    result = []
    for tile in tiles:
        key = str(tile['id'])
        session = manager.sessions.get(key)
        state = session.snapshot() if session else {}
        paused = bool(tile.get('paused'))
        result.append(dict(id=key, name=tile.get('name', 'Receiver'), band=str(tile.get('band', '')),
            freq_khz=tile.get('freq_khz', 0), paused=paused, running=not paused,
            status='STOPPED' if paused else state.get('status', 'QUEUED'),
            decode_status='STOPPED' if paused else state.get('decode_status', 'QUEUED'),
            detail=state.get('decode_detail', ''), receiver_grid=state.get('receiver_grid'),
            progress_pct=0 if paused else min(100, max(0, state.get('decode_audio_seconds', 0)/1.2)),
            cycle_start=state.get('decode_cycle_start', 0),
            spots=list(state.get('decoded_spots', ()))[:96]))
    return result


def set_wspr_running(tiles, manager, key, running):
    tile = next(item for item in tiles if str(item.get('id')) == key)
    changed = bool(tile.get('paused', False)) == running
    tile['paused'] = not running
    session = manager.sessions.get(key)
    if running and changed and session is not None:
        session.retry_now()
    manager.sync(tiles, immediate_keys={key} if running else ())
    return tile
