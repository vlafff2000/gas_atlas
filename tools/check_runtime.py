"""Check the supported interpreter without importing application dependencies."""
import struct
import sys

def check(quiet=False):
    valid=sys.version_info[:2]==(3,8) and sys.implementation.name=='cpython' and struct.calcsize('P')==8
    if not quiet or not valid:
        print('Python {}.{}.{} / {}-bit'.format(*sys.version_info[:3],struct.calcsize('P')*8))
    if not valid:
        print('This build requires CPython 3.8, 64-bit; verified with 3.8.20. Select the correct interpreter.')
    return valid

if __name__=='__main__':
    sys.exit(0 if check('--quiet' in sys.argv) else 1)
