"""Shared touch/desktop application-update screen."""
import textwrap


def boxes(ui):
    return {
        'back': ui.lcd_drawer_back_box(),
        'stable': (30, 128, 240, 188),
        'development': (254, 128, 484, 188),
        'check': (510, 128, 980, 188),
        'previous_notes': (30, 566, 190, 622),
        'next_notes': (204, 566, 364, 622),
        'install': (30, 650, 490, 714),
        'rollback': (510, 650, 980, 714),
    }


def lines(text, width=75):
    output = []
    for paragraph in text.splitlines():
        output.extend(textwrap.wrap(paragraph, width=width) or [''])
    return output


def action(controller, ui, x, y):
    for name, box in boxes(ui).items():
        if not ui.contains(box, x, y):
            continue
        if name == 'back':
            controller.open = False; controller.confirm = None
            return 'back'
        if controller.busy:
            return
        if name in ('stable', 'development'):
            controller.channel = name; controller.release = None; controller.confirm = None
            controller.message = 'Press CHECK FOR UPDATES to contact GitHub.'
        elif name == 'check':
            controller.check()
        elif name in ('previous_notes', 'next_notes'):
            count = len(lines((controller.release or {}).get('notes', '')))
            maximum = max(0, (count - 1) // 10)
            controller.notes_page = max(0, min(maximum, controller.notes_page + (1 if name == 'next_notes' else -1)))
        elif name == 'install' and controller.release and controller.release['commit'] != controller.current().get('commit'):
            if controller.confirm == 'install':
                controller.launch('install')
            else:
                controller.confirm = 'install'
                controller.message = 'Ready to install? Press CONFIRM INSTALL. Audio and decoders will restart.'
        elif name == 'rollback' and controller.rollback_available():
            if controller.confirm == 'rollback':
                controller.launch('rollback')
            else:
                controller.confirm = 'rollback'
                controller.message = 'Press CONFIRM RESTORE to return to the saved previous version.'
        return


def draw(controller, ui, cache):
    palette = ui.APP_UI_STYLE.palette
    ui.draw_logical_rect(0, 0, ui.LOGICAL_W, ui.LOGICAL_H, palette.surface)
    text = (228, 237, 245); secondary = (158, 183, 199); accent = (105, 211, 207)
    def label(x, y, value, size=20, color=text):
        ui.draw_text(cache, x, y, value, color, size, False, False, 'lm', family=ui.APP_UI_STYLE.button.font_family)
    b = boxes(ui)
    label(30, 40, 'APPLICATION UPDATE', 28)
    current = controller.current()
    label(30, 90, 'Installed: v' + current.get('version', '?') + '  ·  ' + current.get('commit', '')[:8], 22, secondary)
    ui.draw_picker_button(cache, b['back'], 'BACK', 22)
    ui.draw_picker_button(cache, b['stable'], 'STABLE', 20, controller.channel == 'stable')
    ui.draw_picker_button(cache, b['development'], 'DEVELOPMENT', 20, controller.channel == 'development')
    ui.draw_picker_button(cache, b['check'], 'CHECKING...' if controller.busy else 'CHECK FOR UPDATES', 22)
    for i, line in enumerate(lines(controller.message, 78)[:3]):
        label(30, 218 + i * 26, line, 20, accent)
    release = controller.release
    label(30, 310, 'Available: ' + (release['name'] if release else 'Check to see available updates'), 22)
    notes = lines(release['notes'] if release else 'Stable: published releases.\nDevelopment: the latest main branch, for testing.\n\nUpdates are checked only when you press the button.')
    start = controller.notes_page * 10
    for i, line in enumerate(notes[start:start + 10]):
        label(30, 346 + i * 21, line, 18, secondary)
    ui.draw_picker_button(cache, b['previous_notes'], 'PREVIOUS', 20)
    ui.draw_picker_button(cache, b['next_notes'], 'NEXT', 20)
    label(390, 594, 'Release notes · page ' + str(controller.notes_page + 1), 18, secondary)
    install = 'CONFIRM INSTALL' if controller.confirm == 'install' else 'INSTALL UPDATE'
    rollback = 'CONFIRM RESTORE' if controller.confirm == 'rollback' else 'RESTORE PREVIOUS'
    ui.draw_picker_button(cache, b['install'], install, 22, bool(release and release['commit'] != current.get('commit') and not controller.busy))
    ui.draw_picker_button(cache, b['rollback'], rollback, 22, controller.rollback_available() and not controller.busy)
    label(30, 752, 'Application only · hardware, settings, recordings and models are preserved', 18, secondary)
