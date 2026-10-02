"""Launch from any working directory. Wait for readiness before opening a browser."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from check_runtime import check

def main():
    if not check(): return 1
    root=Path(__file__).resolve().parents[1];os.chdir(str(root))
    port=int(os.environ.get('GAS_ATLAS_PORT','8501'))
    if not 1024<=port<=65535: raise ValueError('GAS_ATLAS_PORT must be between 1024 and 65535')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',port))==0:
            print('Port {} is in use. Stop the previous app or set GAS_ATLAS_PORT.'.format(port));return 1
    env=dict(os.environ,MPLBACKEND='Agg',PYTHONUTF8='1')
    command=[sys.executable,'-m','streamlit','run','app/main.py','--server.address=127.0.0.1',
             '--server.port='+str(port),'--server.headless=true','--browser.gatherUsageStats=false']
    process=subprocess.Popen(command,env=env)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        url='http://127.0.0.1:'+str(port)
        for _ in range(150):
            if process.poll() is not None: return process.returncode or 1
            try:
                with opener.open(url+'/_stcore/health',timeout=.5) as response:
                    if response.status==200:
                        print('Gas Atlas: '+url,flush=True)
                        if '--no-browser' not in sys.argv: webbrowser.open(url)
                        return process.wait()
            except OSError: time.sleep(.2)
        print('Server did not become ready within 30 seconds. See the messages above.')
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill();process.wait()

if __name__=='__main__':
    try: sys.exit(main())
    except (OSError,ValueError) as error: print('Startup failed: {}'.format(error));sys.exit(1)
