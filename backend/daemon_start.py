import os
import sys

# First fork
pid = os.fork()
if pid > 0:
    sys.exit(0)

# Decouple from parent environment
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.setsid()
os.umask(0)

# Second fork
pid = os.fork()
if pid > 0:
    sys.exit(0)

# Redirect standard file descriptors
sys.stdout.flush()
sys.stderr.flush()

with open(os.devnull, 'r') as devnull:
    os.dup2(devnull.fileno(), sys.stdin.fileno())

log_file = open("server.log", "a+")
os.dup2(log_file.fileno(), sys.stdout.fileno())
os.dup2(log_file.fileno(), sys.stderr.fileno())

# Execute python app.py
os.execv(sys.executable, [sys.executable, "app.py"])
