"""Check the interpreter without importing application dependencies. CPython 3.12 or newer, 64-bit."""
import struct
import sys

MINIMUM=(3,12)

def check(quiet=False):
    valid=sys.version_info[:2]>=MINIMUM and sys.implementation.name=='cpython' and struct.calcsize('P')==8
    if not quiet or not valid:
        print('Python {}.{}.{} / {}-bit'.format(*sys.version_info[:3],struct.calcsize('P')*8))
    if not valid:
        print('This build requires 64-bit CPython {}.{} or newer (tested on 3.12 and 3.13; the portable archives use 3.13). Select a suitable interpreter.'.format(*MINIMUM))
    return valid

def requirements_name():
    """Python 3.13 keeps the exact tested lock (all wheels exist for manylinux2014 = glibc 2.17, РЕД ОС 7.3);
    other interpreters use version ranges."""
    return 'requirements-lock-py313.txt' if sys.version_info[:2]==(3,13) else 'requirements-atlas.txt'

if __name__=='__main__':
    sys.exit(0 if check('--quiet' in sys.argv) else 1)
