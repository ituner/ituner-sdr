#!/usr/bin/env python3
"""Disable desktop menus on the appliance splash without changing touch mapping."""
import argparse
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def configure(home):
    path = Path(home) / '.config/labwc/rc.xml'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        tree = ET.parse(path)
        backup = path.with_name('rc.xml.before-ituner-kiosk')
        if not backup.exists():
            shutil.copy2(path, backup)
        root = tree.getroot()
    else:
        root = ET.Element('labwc_config')
        tree = ET.ElementTree(root)
    namespace = root.tag.split('}')[0][1:] if root.tag.startswith('{') else ''
    if namespace:
        ET.register_namespace('', namespace)
    def tag(name):
        return '{' + namespace + '}' + name if namespace else name
    def section(name):
        node = root.find(tag(name))
        return node if node is not None else ET.SubElement(root, tag(name))
    mouse = section('mouse')
    # User rc.xml is merged after the OS defaults. Empty bindings explicitly
    # override the built-in desktop menu, including touch-emulated left clicks.
    for name in ('Root', 'Desktop'):
        contexts = [c for c in mouse.findall(tag('context')) if c.get('name') == name]
        if not contexts:
            contexts = [ET.SubElement(mouse, tag('context'), name=name)]
        for context in contexts:
            for button in ('Left', 'Middle', 'Right'):
                for action in ('Press', 'Click', 'DoubleClick'):
                    for bind in list(context):
                        if bind.tag == tag('mousebind') and bind.get('button') == button and bind.get('action') == action:
                            context.remove(bind)
                    ET.SubElement(context, tag('mousebind'), button=button, action=action)
    keyboard = section('keyboard')
    for key in ('W-space', 'Menu'):
        for bind in list(keyboard):
            if bind.tag == tag('keybind') and bind.get('key') == key:
                keyboard.remove(bind)
        ET.SubElement(keyboard, tag('keybind'), key=key)
    ET.indent(tree, space='  ')
    temporary = path.with_name('rc.xml.ituner-tmp')
    tree.write(temporary, encoding='UTF-8', xml_declaration=True)
    temporary.replace(path)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    print(configure(parser.parse_args().home))
