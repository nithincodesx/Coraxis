"""
Single-command Unified Launcher for Kimi Multi-Agent Research Laboratory.
Launches the FastAPI Thick Backend on port 8000 and Next.js Frontend on port 3000.
Access the application at: http://localhost:3000
"""

import subprocess
import sys
import time
import os

def main():
    print("=" * 60)
    print("Launch Synapse Multi-Agent Research Laboratory")
    print("=" * 60)
    print("  * Thick Python Backend : http://127.0.0.1:8000")
    print("  * Unified Frontend     : http://localhost:3000")
    print("=" * 60)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.join(root_dir, "frontend")

    python_exe = sys.executable
    venv_python = os.path.join(root_dir, ".venv", "Scripts", "python.exe")
    user_python = r"C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe"
    if os.path.exists(venv_python):
        python_exe = venv_python
    elif os.path.exists(user_python):
        python_exe = user_python

    # Ensure UTF-8 output encoding for Windows subprocesses
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # 1. Start FastAPI backend server
    print("\n[1/2] Starting FastAPI backend on port 8000...")
    backend_cmd = [python_exe, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"]
    backend_proc = subprocess.Popen(backend_cmd, cwd=root_dir, env=env)

    time.sleep(2)

    # 2. Start Next.js frontend server
    print("[2/2] Starting Next.js frontend on port 3000...")
    frontend_cmd = "npm run dev"
    frontend_proc = subprocess.Popen(frontend_cmd, cwd=frontend_dir, shell=True)

    print("\nApplication initialized!")
    print("Open your browser to: http://localhost:3000\n")

    try:
        backend_proc.wait()
        frontend_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down servers...")
        backend_proc.terminate()
        frontend_proc.terminate()
        sys.exit(0)

if __name__ == "__main__":
    main()
