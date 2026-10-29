"""Minimal stdio MCP server wrapping WinDirStat's headless `/saveto` CSV export.

WinDirStat 2.x accepts `WinDirStat.exe /saveto <out.csv> <path>`: it scans without
showing a window, writes one CSV row per file/folder and exits.
"""
import csv, json, os, re, shutil, subprocess, sys, tempfile

__version__ = "0.1.0"

# Paths commonly safe to clean (caches, temp, crash dumps, update leftovers).
# Matching is advisory only: the server never deletes anything.
CLEANUP = [
    (r"\\AppData\\Local\\Temp(\\|$)", "user temp"),
    (r"^[A-Z]:\\Windows\\Temp(\\|$)", "windows temp"),
    (r"\\AppData\\Local\\(npm-cache|pip\\cache|uv\\cache|yarn\\Cache|pnpm-cache|NuGet\\v3-cache)(\\|$)", "package cache"),
    (r"\\\.bun\\install\\cache(\\|$)", "package cache"),
    (r"\\(Cache|Code Cache|GPUCache|ShaderCache|DawnCache|GrShaderCache|cache2)(\\|$)", "app cache"),
    (r"\\\.cache(\\|$)", "dev cache (may hold downloaded models)"),
    (r"\\AppData\\Local\\CrashDumps(\\|$)|\\Minidump(\\|$)|\.dmp$", "crash dump"),
    (r"^[A-Z]:\\Windows\\SoftwareDistribution\\Download(\\|$)", "windows update download"),
    (r"^[A-Z]:\\\$Recycle\.Bin(\\|$)", "recycle bin"),
    (r"^[A-Z]:\\Windows\.old(\\|$)", "old windows install"),
    (r"\\node_modules$", "node_modules (rebuildable)"),
    (r"\.(tmp|old|bak)$", "temp/backup file"),
    (r"\.log$", "log file"),
]
CLEANUP = [(re.compile(rx, re.I), why) for rx, why in CLEANUP]


def find_exe():
    """WINDIRSTAT_EXE env var, then next to this script, then PATH, then default install dir."""
    for p in (os.environ.get("WINDIRSTAT_EXE"),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "WinDirStat.exe"),
              shutil.which("WinDirStat.exe"),
              os.path.expandvars(r"%ProgramFiles%\WinDirStat\WinDirStat.exe")):
        if p and os.path.isfile(p):
            return p
    raise FileNotFoundError("WinDirStat.exe not found; set WINDIRSTAT_EXE")


def run_windirstat(path, out_csv, timeout=1800):
    subprocess.run([find_exe(), "/saveto", out_csv, path], check=True, timeout=timeout)


def analyze(csv_path, top=30, min_mb=100):
    rows = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            # ponytail: folders are told apart by child counts, so an empty folder counts as a file (size 0, harmless)
            is_dir = int(r["Folders"]) > 0 or int(r["Files"]) > 0
            rows.append((r["Name"], int(r["Physical Size"]), is_dir))
    if not rows:
        raise ValueError("WinDirStat produced an empty CSV")
    mb = lambda b: round(b / 2**20, 1)

    # Walk shortest paths first so only the outermost match is reported; sizes aren't double counted.
    hits, seen = [], []
    for name, size, _ in sorted(rows, key=lambda r: len(r[0])):
        if size < min_mb * 2**20 or any(name.startswith(s + "\\") for s in seen):
            continue
        for rx, why in CLEANUP:
            if rx.search(name):
                hits.append({"path": name, "mb": mb(size), "reason": why})
                seen.append(name)
                break

    files = sorted((r for r in rows if not r[2]), key=lambda r: -r[1])[:top]
    return {
        "root": rows[0][0],
        "total_mb": mb(rows[0][1]),
        "cleanup_candidates_mb": round(sum(h["mb"] for h in hits), 1),
        "cleanup_candidates": sorted(hits, key=lambda h: -h["mb"]),
        "largest_files": [{"path": n, "mb": mb(s)} for n, s, _ in files],
    }


def scan(path, top=30, min_mb=100):
    if not os.path.isdir(path):
        raise ValueError(f"not a directory: {path}")
    fd, out = tempfile.mkstemp(suffix=".csv", prefix="windirstat_")
    os.close(fd)
    try:
        run_windirstat(path, out)
        return analyze(out, int(top), float(min_mb))
    finally:
        os.remove(out)


TOOLS = [{
    "name": "windirstat_scan",
    "description": "Scan a drive or folder with WinDirStat (read-only). Returns cleanup candidates "
                   "(temp, caches, crash dumps, node_modules, ...) and the largest files. Never deletes anything.",
    "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Drive or folder, e.g. C:\\ or D:\\Projects"},
        "top": {"type": "integer", "default": 30, "description": "How many largest files to return"},
        "min_mb": {"type": "number", "default": 100, "description": "Ignore cleanup candidates smaller than this"},
    }, "required": ["path"]},
}]


def handle(msg):
    """Return (result, error) for one JSON-RPC request."""
    m, params = msg.get("method"), msg.get("params") or {}
    if m == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "windirstat", "version": __version__}}, None
    if m == "ping":
        return {}, None
    if m == "tools/list":
        return {"tools": TOOLS}, None
    if m == "tools/call":
        if params.get("name") != "windirstat_scan":
            return None, {"code": -32602, "message": f"unknown tool: {params.get('name')}"}
        try:
            res = scan(**params.get("arguments", {}))
            return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]}, None
        except Exception as e:  # tool errors go back to the model, not the protocol
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}, None
    return None, {"code": -32601, "message": f"method not found: {m}"}


def serve():
    for line in sys.stdin:
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            print(json.dumps(reply), flush=True)
            continue
        if "id" not in msg:  # notification
            continue
        result, error = handle(msg)
        reply = {"jsonrpc": "2.0", "id": msg["id"]}
        reply.update({"error": error} if error else {"result": result})
        print(json.dumps(reply), flush=True)


def main():
    if len(sys.argv) > 1:  # CLI: windirstat-mcp C:\some\folder
        print(json.dumps(scan(sys.argv[1]), ensure_ascii=False, indent=1))
    else:
        serve()


if __name__ == "__main__":
    main()
