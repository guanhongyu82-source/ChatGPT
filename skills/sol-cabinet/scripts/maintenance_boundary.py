#!/usr/bin/env python3
"""Process-scoped, fail-closed write boundary for Sol automatic maintenance.

No global ACL, model setting, external configuration, or discovery entry changes.
Explicit user-directed external work runs separately, never by bypassing this guard.
"""
from __future__ import annotations

import ctypes
import functools
import json
import os
from pathlib import Path
import sys
import tempfile

OWNED_ROOT = Path('/Users/macbook/ChatGPT')
PROTECTED_ROOTS = tuple(Path('/Users/macbook') / name
                       for name in ('Grok', '.grok', 'Cursor', '.cursor'))
_ACTIVE = False


def require_owned(path):
    """Validate both spelled and resolved paths, including absent leaf names."""
    raw = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    real = raw.resolve(strict=False)
    for protected in PROTECTED_ROOTS:
        if raw.is_relative_to(protected) or real.is_relative_to(protected.resolve()):
            raise PermissionError('Sol automatic maintenance cannot mutate another runtime')
    if not real.is_relative_to(OWNED_ROOT.resolve()):
        raise PermissionError('Sol automatic maintenance writes only inside ChatGPT')
    return real


def _profile(owned, protected):
    # Kernel enforcement covers child processes and filesystem aliases; no shell parsing.
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    denied = sorted({str(p) for root in protected
                     for p in (Path(root).absolute(), Path(root).resolve())})
    return ('(version 1)\n(allow default)\n(deny file-write*)\n'
            '(allow file-write* (subpath ' + quote(Path(owned).resolve()) + ')'
            ' (literal "/dev/null") (literal "/dev/tty"))\n'
            '(deny file-write* ' + ' '.join('(subpath ' + quote(p) + ')' for p in denied) + ')\n')


def _apply(profile):
    if sys.platform != 'darwin':
        raise PermissionError('Sol maintenance boundary unavailable on this host; no write authorized')
    try:
        library = ctypes.CDLL('/usr/lib/libsandbox.dylib', use_errno=True)
        library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64,
                                        ctypes.POINTER(ctypes.c_char_p)]
        library.sandbox_init.restype = ctypes.c_int
        error = ctypes.c_char_p()
        if library.sandbox_init(profile.encode(), 0, ctypes.byref(error)) != 0:
            raise PermissionError('Sol maintenance sandbox could not be activated')
    except (OSError, AttributeError) as exc:
        raise PermissionError('Sol maintenance boundary unavailable; refusing mutation') from exc


def activate():
    """Restrict this process and descendants; never modify other runtime permissions."""
    global _ACTIVE
    if _ACTIVE:
        return
    if OWNED_ROOT.is_symlink() or not OWNED_ROOT.is_dir():
        raise PermissionError('Sol physical root changed; explicit maintenance review required')
    _apply(_profile(OWNED_ROOT, PROTECTED_ROOTS))
    _ACTIVE = True
    # Reuse the existing Sol scratch root; activation itself performs zero filesystem writes.
    scratch = require_owned(OWNED_ROOT / '.scratch')
    if not scratch.is_dir():
        raise PermissionError('Sol scratch root missing; no external temporary fallback')
    os.environ['TMPDIR'] = str(scratch)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    tempfile.tempdir = str(scratch)


def guarded(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        activate()
        return function(*args, **kwargs)
    return run


def main():
    command = sys.argv[1:]
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        raise SystemExit('usage: maintenance_boundary.py -- command [args...]')
    activate()
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
