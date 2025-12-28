__version__ = "0.1.4"
import os, sys, time, tempfile, shutil, subprocess, string, requests

# GitHub URLs
GITHUB_RAW_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/microbit_firmware.ts"
GITHUB_PY_URL = "https://raw.githubusercontent.com/ahk4918/Microbit-devices-commands/refs/heads/main/microbit_firmware.py"

def download_github_to_temp(url, suffix):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        if "404: Not Found" in r.text: return None
        fd, path = tempfile.mkstemp(suffix=suffix)
        mode = 'w' if suffix in ['.ts', '.py'] else 'wb'
        with os.fdopen(fd, mode, encoding='utf-8' if mode == 'w' else None) as f: 
            f.write(r.text if mode == 'w' else r.content)
        return path
    except Exception as e:
        print(f"Debug: download error for {url}: {e}", file=sys.stderr)
        return None

def ts_to_python(ts_path):
    """Convert TypeScript to Python (improved conversion)"""
    try:
        with open(ts_path, 'r', encoding='utf-8') as f:
            ts_code = f.read()
        
        # Improved TS to Python conversion for MicroPython
        py_code = ts_code
        
        # Remove TypeScript type annotations
        py_code = __import__('re').sub(r':\s*\w+(?=\s*[=,\)])', '', py_code)
        py_code = __import__('re').sub(r'<\w+>', '', py_code)
        
        # Variable declarations
        py_code = py_code.replace("let ", "")
        py_code = py_code.replace("const ", "")
        py_code = py_code.replace("var ", "")
        
        # Functions
        py_code = py_code.replace("function ", "def ")
        py_code = py_code.replace("=>", "lambda")
        
        # Console/logging
        py_code = py_code.replace("console.log", "print")
        
        # Comparisons
        py_code = py_code.replace("===", "==")
        py_code = py_code.replace("!==", "!=")
        
        # Remove semicolons
        py_code = py_code.replace(";", "")
        
        # Fix braces - convert to proper Python indentation
        lines = py_code.split('\n')
        fixed_lines = []
        indent_level = 0
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                fixed_lines.append("")
                continue
            
            # Decrease indent for closing braces
            if stripped.startswith("}"):
                indent_level = max(0, indent_level - 1)
                continue
            
            # Add proper indentation
            if stripped.endswith("{"):
                fixed_lines.append("    " * indent_level + stripped[:-1] + ":")
                indent_level += 1
            else:
                fixed_lines.append("    " * indent_level + stripped)
            
            # Increase indent after opening braces
            if "{" in stripped and not stripped.endswith("{"):
                indent_level += 1
        
        py_code = "\n".join(fixed_lines)
        
        # Add MicroPython imports if needed
        if "print" in py_code and "from microbit import" not in py_code:
            py_code = "from microbit import *\n\n" + py_code
        
        fd, py_path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(py_code)
        print(f"Debug: Converted TS to Python", file=sys.stderr)
        return py_path
    except Exception as e:
        print(f"Debug: TS to Python conversion failed: {e}", file=sys.stderr)
        return None

def compile_python_to_hex(py_path):
    """Compile Python to HEX using uflash"""
    try:
        # Ensure uflash is installed
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "uflash"],
            timeout=30,
            capture_output=True
        )
        
        # Create a temporary directory for uflash output
        hex_dir = tempfile.mkdtemp()
        
        # uflash expects a directory path, not a file
        result = subprocess.run(
            [sys.executable, "-m", "uflash", py_path, hex_dir],
            capture_output=True,
            timeout=60
        )
        
        # Look for micropython.hex in the directory
        micropython_hex = os.path.join(hex_dir, "micropython.hex")
        if os.path.exists(micropython_hex) and os.path.getsize(micropython_hex) > 100:
            fd, out = tempfile.mkstemp(suffix=".hex")
            with open(micropython_hex, 'rb') as src, os.fdopen(fd, 'wb') as dst:
                dst.write(src.read())
            shutil.rmtree(hex_dir, ignore_errors=True)
            print(f"Debug: Compiled Python to HEX with uflash", file=sys.stderr)
            return out
        
        print(f"Debug: uflash output: {result.stderr.decode()}", file=sys.stderr)
        shutil.rmtree(hex_dir, ignore_errors=True)
    except Exception as e:
        print(f"Debug: Python to HEX compilation failed: {e}", file=sys.stderr)
    
    return None

def flash_with_uflash(bin_path):
    try:
        import uflash; uflash.flash(bin_path); return True
    except (ImportError, Exception):
        try: subprocess.check_call([sys.executable, "-m", "uflash", bin_path]); return True
        except Exception: return False

def find_microbit_drive():
    for d in string.ascii_uppercase:
        root = f"{d}:/"
        if os.path.exists(root):
            try:
                if any(n.upper() == "MICROBIT.HTM" for n in os.listdir(root)): return root
            except Exception: pass
    return None

def flash_to_drive(bin_path):
    drive = find_microbit_drive()
    if not drive: return False
    ext = os.path.splitext(bin_path)[1]
    target = os.path.join(drive, f"firmware{ext}")
    try: 
        shutil.copy2(bin_path, target)
        return True
    except Exception: return False

def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p): os.remove(p)
        except Exception: pass

def flash_latest_immediately():
    # Try downloading pre-compiled Python first
    py = download_github_to_temp(GITHUB_PY_URL, ".py")
    if not py:
        # Fall back to downloading TS and converting
        ts = download_github_to_temp(GITHUB_RAW_URL, ".ts")
        if not ts: print("Status: download-failed"); return 1
        py = ts_to_python(ts)
        cleanup(ts)
    
    if not py: print("Status: download-failed"); return 1
    
    binf = None
    try:
        binf = compile_python_to_hex(py)
        if not binf: print("Status: compile-failed"); return 1
        # Skip uflash.flash() - go straight to drive
        if flash_to_drive(binf): print("Status: flashed-via-drive"); return 0
        print("Status: flash-failed"); return 1
    finally: cleanup(py, binf)

if __name__ == "__main__": 
    sys.exit(flash_latest_immediately())
