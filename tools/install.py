"""Shared installer; creates a local environment and never updates system packages."""
from pathlib import Path
import os
import subprocess
import sys
import venv
from check_runtime import check,requirements_name

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
    # Ask the environment's own interpreter which requirements file fits (it may differ from the one running this script).
    name=subprocess.check_output([str(executable),'-c','import sys;sys.path.insert(0,"tools");from check_runtime import requirements_name;print(requirements_name())'],universal_newlines=True).strip()
    print('Requirements: '+name,flush=True)
    subprocess.check_call([str(executable),'-m','pip','install','--disable-pip-version-check','--upgrade','pip'])
    subprocess.check_call([str(executable),'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','-r',name])
    subprocess.check_call([str(executable),'-m','pip','check'])
    subprocess.check_call([str(executable),'-m','compileall','-q','app','tools'])
    print('Installation complete. Start run_windows.bat or bash run.sh.')
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,subprocess.CalledProcessError) as error:
        print('Installation failed: {}'.format(error));sys.exit(1)
