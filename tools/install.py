"""Shared installer; creates a local environment and never updates system packages."""
from pathlib import Path
import os
import subprocess
import sys
import venv
from check_runtime import check

ROOT=Path(__file__).resolve().parents[1]

def main():
    if not check(): return 1
    os.chdir(str(ROOT))
    environment=ROOT/'.venv'
    executable=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if executable.exists():
        subprocess.check_call([str(executable),'tools/check_runtime.py'])
    else:
        print('Creating .venv ...',flush=True)
        venv.EnvBuilder(with_pip=True,symlinks=os.name!='nt').create(str(environment))
    subprocess.check_call([str(executable),'-m','pip','install','--disable-pip-version-check','pip==24.3.1'])
    lock=ROOT/'requirements-lock-py38.txt'
    requirements=lock.name if lock.exists() else 'requirements_py38.txt'
    subprocess.check_call([str(executable),'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','-r',requirements])
    subprocess.check_call([str(executable),'-m','pip','check'])
    subprocess.check_call([str(executable),'-m','compileall','-q','app','tools'])
    print('Installation complete. Start run_windows.bat or bash run.sh.')
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,subprocess.CalledProcessError) as error:
        print('Installation failed: {}'.format(error));sys.exit(1)
