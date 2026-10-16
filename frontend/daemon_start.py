import os
import sys

pid = os.fork()
if pid > 0:
    sys.exit(0)

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.setsid()
os.umask(0)

pid = os.fork()
if pid > 0:
    sys.exit(0)

sys.stdout.flush()
sys.stderr.flush()

with open(os.devnull, 'r') as devnull:
    os.dup2(devnull.fileno(), sys.stdin.fileno())

log_file = open("vite.log", "a+")
os.dup2(log_file.fileno(), sys.stdout.fileno())
os.dup2(log_file.fileno(), sys.stderr.fileno())

os.execvp("npx", ["npx", "vite", "--host", "0.0.0.0", "--port", "5173"])
