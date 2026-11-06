"""Configure Windows rendering before importing Qt or creating a QApplication."""
from __future__ import annotations
import os
import sys


def prepare_rendering(environ=None,platform=None):
    env=os.environ if environ is None else environ
    platform=sys.platform if platform is None else platform
    software=platform=='win32' or '--software-rendering' in sys.argv
    if software:
        env['QT_OPENGL']='software'
        env['QT_QUICK_BACKEND']='software'
        flags=env.get('QTWEBENGINE_CHROMIUM_FLAGS','').split()
        # Keep Chromium's CPU rasterizer available. Never disable its sandbox.
        flags=[f for f in flags if f not in ('--disable-software-rasterizer','--enable-gpu')]
        for flag in ('--disable-gpu','--disable-gpu-compositing'):
            if flag not in flags:flags.append(flag)
        env['QTWEBENGINE_CHROMIUM_FLAGS']=' '.join(flags)
    return software
