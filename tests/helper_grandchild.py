import subprocess
import sys
import time

gc = subprocess.Popen(
    [sys.executable, '-c', 'import time; time.sleep(30)']
)
print(f'GC_PID:{gc.pid}', flush=True)
time.sleep(30)
