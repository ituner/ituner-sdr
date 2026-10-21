"""One update source and one primary action, shared by Pi and Mac."""
import textwrap


def boxes(ui):
    return {
        'back': ui.lcd_drawer_back_box(),
        'check': (30, 638, 490, 706),
        'install': (30, 638, 490, 706),
        'rollback': (30, 638, 490, 706),
        'cancel': (520, 638, 980, 706),
        'recovery': (520, 638, 980, 706),
        'previous_notes': (30, 554, 190, 610),
        'next_notes': (204, 554, 364, 610),
    }


def lines(text, width=75):
    output = []
    for paragraph in text.splitlines():
        output.extend(textwrap.wrap(paragraph, width=width) or [''])
    return output


def update_available(controller):
    return bool(controller.release and
                controller.release['commit'] != controller.current().get('commit'))


def controls(controller):
    """Only displayed controls are hit-tested; busy controls cannot submit jobs."""
    if controller.busy:
        return [('check', 'CHECKING...' if controller.phase == 'checking' else 'UPDATE IN PROGRESS', False)]
    if controller.recovery:
        return [('rollback', 'CONFIRM RESTORE' if controller.confirm == 'rollback' else 'RESTORE PREVIOUS',
                 controller.rollback_available()), ('cancel', 'CANCEL', True)]
    if controller.confirm == 'install':
        return [('install', 'CONFIRM INSTALL', update_available(controller)), ('cancel', 'CANCEL', True)]
    result = [('install', 'INSTALL UPDATE', True)] if update_available(controller) and controller.phase != 'error' else [
        ('check', 'CHECK AGAIN' if controller.release else 'CHECK FOR UPDATES', bool(controller.cfg))]
    if controller.rollback_available():
        result.append(('recovery', 'RECOVERY', True))
    if len(lines((controller.release or {}).get('notes', ''))) > 5:
        maximum = (len(lines(controller.release['notes'])) - 1) // 5
        result.extend([('previous_notes', 'PREVIOUS', controller.notes_page > 0),
                       ('next_notes', 'NEXT', controller.notes_page < maximum)])
    return result


def action(controller, ui, x, y):
    b = boxes(ui)
    if ui.contains(b['back'], x, y):
        controller.open = False; controller.confirm = None; controller.recovery = False
        return 'back'
    for name, _label, enabled in controls(controller):
        if not enabled or not ui.contains(b[name], x, y):
            continue
        if name == 'check':
            controller.check()
        elif name == 'recovery':
            controller.recovery = True; controller.confirm = None
        elif name == 'cancel':
            controller.recovery = False; controller.confirm = None
        elif name in ('previous_notes', 'next_notes'):
            controller.notes_page += 1 if name == 'next_notes' else -1
        elif name in ('install', 'rollback'):
            if controller.confirm == name:
                controller.launch(name)
            else:
                controller.confirm = name
        return


def draw(controller, ui, cache):
    palette = ui.APP_UI_STYLE.palette
    ui.draw_logical_rect(0, 0, ui.LOGICAL_W, ui.LOGICAL_H, palette.surface)
    text = (228, 237, 245); secondary = (158, 183, 199); accent = (105, 211, 207)
    def label(x, y, value, size=22, color=text):
        ui.draw_text(cache, x, y, value, color, size, False, False, 'lm', family=ui.APP_UI_STYLE.button.font_family)
    b = boxes(ui)
    label(30, 40, 'SYSTEM UPDATES', 28)
    label(30, 80, 'Latest iTuner from GitHub main', 20, secondary)
    current = controller.current()
    build = current.get('commit', '')[:8] or 'unknown'
    label(30, 135, 'Installed build: ' + build, 24)
    label(30, 172, 'Application version: ' + current.get('version', '?'), 20, secondary)
    ui.draw_picker_button(cache, b['back'], 'BACK', 22)
    if controller.recovery:
        heading = 'Restore the previous build?'
        message = 'Use this only if an update caused a problem. The app will restart.'
    elif controller.confirm == 'install':
        heading = 'Install this update?'
        message = 'Audio and decoders will stop while the app restarts. Your settings are kept.'
    else:
        heading = {
            'idle': 'Ready to check', 'checking': 'Checking for updates...',
            'available': 'Update available', 'current': 'Up to date',
            'starting': 'Starting update...', 'downloading': 'Downloading update...',
            'installing': 'Installing update...', 'complete': 'Update complete',
            'error': 'Update needs attention',
        }.get(controller.phase, 'Application update')
        message = controller.message
    label(30, 240, heading, 28, accent)
    for i, line in enumerate(lines(message)[:3]):
        label(30, 285 + i * 28, line, 21, secondary)
    release = controller.release
    if controller.recovery:
        label(30, 395, 'One previous installation is saved for recovery.', 22)
    elif release and not controller.busy:
        label(30, 395, ('Latest: ' if not update_available(controller) else 'New: ') + release['name'], 22)
        start = controller.notes_page * 5
        for i, line in enumerate(lines(release['notes'])[start:start + 5]):
            label(30, 432 + i * 24, line, 20, secondary)
    elif not controller.busy and controller.phase != 'error':
        label(30, 395, 'Check when you want to update. Nothing installs automatically.', 21, secondary)
    for name, caption, enabled in controls(controller):
        visual = ui.draw_styled_button_frame(b[name], active=enabled and name in ('check', 'install', 'rollback'))
        ui.draw_text(cache, (b[name][0] + b[name][2]) / 2, (b[name][1] + b[name][3]) / 2,
                     caption, visual.text if enabled else secondary, 22, True, False, 'cm',
                     family=ui.APP_UI_STYLE.button.font_family)
    label(30, 750, 'Display drivers, settings, recordings and models are kept.', 20, secondary)
