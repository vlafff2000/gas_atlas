"""Check the interpreter without importing application dependencies. CPython 3.8 or newer, 64-bit."""
import struct
import sys

MINIMUM=(3,8)

def check(quiet=False):
    valid=sys.version_info[:2]>=MINIMUM and sys.implementation.name=='cpython' and struct.calcsize('P')==8
    if not quiet or not valid:
        print('Python {}.{}.{} / {}-bit'.format(*sys.version_info[:3],struct.calcsize('P')*8))
    if not valid:
        print('This build requires 64-bit CPython {}.{} or newer (tested on 3.8, 3.11 and 3.13). Select a suitable interpreter.'.format(*MINIMUM))
    return valid

def requirements_name():
    """Python 3.8 keeps the exact tested lock; newer interpreters use version ranges (wheels exist for them).
    Both cover 5.8 and Gas Atlas 6."""
    return 'requirements-lock-py38.txt' if sys.version_info[:2]==(3,8) else 'requirements-atlas.txt'

if __name__=='__main__':
    sys.exit(0 if check('--quiet' in sys.argv) else 1)
