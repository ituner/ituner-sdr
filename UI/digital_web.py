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
        self.options = {"receivers": [], "presets": {"sstv": [], "wspr": []}}
        self.updated_at = 0
        self.closed = False

    def publish(self, sstv, wspr):
        with self.lock:
            self.state = copy.deepcopy({'sstv': sstv, 'wspr': wspr})
            self.updated_at = time.time()

    def snapshot(self, mode):
        with self.lock:
            return {'decoders': copy.deepcopy(self.state[mode]), 'updated_at': self.updated_at}

    def publish_options(self, options):
        with self.lock:
            self.options = copy.deepcopy(options)

    def options_snapshot(self):
        with self.lock:
            return copy.deepcopy(self.options)

    def request(self, mode, key, action, timeout=5, config=None):
        if mode not in ('sstv', 'wspr') or action not in ('start', 'stop', 'add', 'edit', 'delete') or not isinstance(key, str) or not 0 < len(key) <= 100:
            raise ControlError(400, 'Choose a decoder and a valid action')
        if action in ('add', 'edit') and not isinstance(config, dict):
            raise ControlError(400, 'Choose a receiver and band')
        with self.lock:
            if self.closed:
                raise ControlError(503, 'The SDR is stopping')
        item = dict(mode=mode, key=key, action=action, deadline=time.monotonic()+timeout,
                    done=threading.Event(), error=None, config=copy.deepcopy(config or {}))
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
                apply(item['mode'], item['key'], item['action'], item['config'])
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
        result.append(dict(id=key, name=tile.get('name', 'Receiver'), server=tile.get('server', ''), band=str(tile.get('band', '')),
            freq_khz=tile.get('freq_khz', 0), paused=paused, running=not paused,
            status='STOPPED' if paused else state.get('status', 'QUEUED'),
            decode_status='STOPPED' if paused else state.get('decode_status', 'QUEUED'),
            detail=state.get('decode_detail', ''), receiver_grid=state.get('receiver_grid'),
            run_id=state.get('run_id', ''),
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


def receiver_options(receivers, wspr_bands, sstv_presets, configured=(), current=None):
    """Use the same directory and presets as the touchscreen; retain saved sources."""
    stations, seen = [], set()
    for row in receivers:
        name, location, server = row[:3]
        if server and server.rstrip('/') not in seen:
            stations.append(dict(name=name, location=location, server=server))
            seen.add(server.rstrip('/'))
    for row in configured:
        server = row.get('server', '')
        if server and server.rstrip('/') not in seen:
            stations.append(dict(name=row.get('name', server), location='', server=server))
            seen.add(server.rstrip('/'))
    presets = []
    def add_preset(band, freq, mode):
        key = f'{float(freq):g}:{mode}'
        if not any(p['id'] == key for p in presets):
            presets.append(dict(id=key, band=band, freq_khz=freq, mode=mode))
    for row in sstv_presets:
        add_preset(*row)
    for row in configured:
        if row.get('mode') in ('usb', 'lsb'):
            add_preset(row['band'], row['freq_khz'], row['mode'])
    if current and current[2] in ('usb', 'lsb') and 0 < current[1] <= 30000:
        add_preset(*current)
    return dict(receivers=stations, presets=dict(sstv=presets,
        wspr=[dict(id=band, band=band, freq_khz=freq, mode='usb') for band, freq in wspr_bands]))


def resolve_receiver_config(mode, payload, options):
    server, preset = payload.get('server'), payload.get('preset')
    if not isinstance(server, str) or not isinstance(preset, str):
        raise ControlError(400, 'Choose a receiver and band')
    receiver = next((row for row in options['receivers'] if row['server'] == server), None)
    band = next((row for row in options['presets'][mode] if row['id'] == preset), None)
    if not receiver or not band:
        raise ControlError(400, 'Receiver or band is no longer available; reopen the editor')
    return dict(name=receiver['name'], server=receiver['server'], location=receiver.get('location', ''),
                band=band['band'], freq_khz=band['freq_khz'], mode=band['mode'])


class ReceiverController:
    """Called only on the UI thread, shared by both browser modes."""
    def __init__(self, sstv, tiles, wspr, options):
        self.sstv, self.tiles, self.wspr, self.options = sstv, tiles, wspr, options

    def apply(self, mode, key, action, payload):
        configs = self.sstv.configs if mode == 'sstv' else self.tiles
        existing = next((row for row in configs if str(row['id']) == key), None)
        if action != 'add' and existing is None:
            raise ControlError(404, 'Decoder no longer exists; refresh the page')
        config = None
        if action in ('add', 'edit'):
            config = resolve_receiver_config(mode, payload, self.options())
            if action == 'add':
                if type(payload.get('start', True)) is not bool:
                    raise ControlError(400, 'Invalid start setting')
                # Client-generated ids make a retried Add safe after a lost response.
                if existing:
                    if all(existing.get(k) == config[k] for k in ('server', 'band', 'freq_khz')):
                        return dict(existing)
                    raise ControlError(409, 'Decoder id already exists; refresh the page')
                if mode == 'wspr' and len(configs) >= 64:
                    raise ControlError(409, '64 saved WSPR decoders maximum; remove an unused decoder')
        if mode == 'sstv':
            if action == 'add':
                try:
                    self.sstv.add(config['name'], config['server'],
                                  (config['band'], config['freq_khz'], config['mode']),
                                  key=key, running=payload.get('start', True))
                except ValueError as exc:
                    raise ControlError(409, str(exc))
            elif action == 'edit':
                self.sstv.update(key, config['name'], config['server'],
                                 (config['band'], config['freq_khz'], config['mode']))
            elif action == 'delete':
                self.sstv.delete(key)
            else:
                self.sstv.set_running(key, action == 'start')
        else:
            if action == 'add':
                existing = dict(config, id=key, paused=not payload.get('start', True), view=0)
                existing.pop('mode')
                self.tiles.append(existing)
            elif action == 'edit':
                # Remove the old session first so old-band spots do not appear under the new label.
                changed = any(existing.get(k) != config[k] for k in ('server', 'band', 'freq_khz'))
                if changed:
                    session = self.wspr.sessions.pop(key, None)
                    if session:
                        session.stop()
                    self.wspr.start_at.pop(key, None)
                existing.update({k: v for k, v in config.items() if k != 'mode'})
            elif action == 'delete':
                self.tiles[:] = [row for row in self.tiles if str(row['id']) != key]
            else:
                set_wspr_running(self.tiles, self.wspr, key, action == 'start')
                return dict(existing)
            self.wspr.sync(self.tiles, immediate_keys={key} if existing and not existing.get('paused') else ())
        return dict(existing or config or {})
