# windirstat-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant scan Windows drives with
[WinDirStat](https://windirstat.net) and report what can be cleaned up.

- **Read-only.** It reports; it never deletes anything.
- **Zero dependencies.** One Python file, standard library only.
- Uses WinDirStat 2.x's headless `/saveto` switch, so no window opens during a scan.

## How it works

WinDirStat 2.x has an undocumented command-line mode (found by inspecting the binary's strings):

```
WinDirStat.exe /saveto out.csv C:\
```

It scans the path, writes one CSV row per file and folder, and exits. The server runs this, then:

- matches paths against known-safe-to-clean patterns (temp folders, browser/app caches, package-manager
  caches, crash dumps, Windows Update downloads, `node_modules`, `*.old`/`*.tmp` files, ...)
- reports only the outermost match, so nested caches aren't double counted
- lists the largest individual files

## Install

Requirements: Windows, Python 3.9+, [WinDirStat 2.x](https://github.com/windirstat/windirstat/releases).

```
pip install git+https://github.com/<you>/windirstat-mcp
```

The server finds `WinDirStat.exe` in this order: `WINDIRSTAT_EXE` env var, next to the script, `PATH`,
`%ProgramFiles%\WinDirStat\`.

### Claude Code

```
claude mcp add windirstat --scope user -e WINDIRSTAT_EXE="C:\path\to\WinDirStat.exe" -- windirstat-mcp
```

### Claude Desktop / other clients

```json
{
  "mcpServers": {
    "windirstat": {
      "command": "windirstat-mcp",
      "env": { "WINDIRSTAT_EXE": "C:\\path\\to\\WinDirStat.exe" }
    }
  }
}
```

## Tool

`windirstat_scan(path, top=30, min_mb=100)`

```json
{
  "root": "C:\\",
  "total_mb": 417204.5,
  "cleanup_candidates_mb": 81234.0,
  "cleanup_candidates": [
    { "path": "C:\\Users\\me\\AppData\\Local\\uv\\cache", "mb": 20098.6, "reason": "package cache" }
  ],
  "largest_files": [
    { "path": "C:\\pagefile.sys", "mb": 18432.0 }
  ]
}
```

Candidates are heuristics. Review before deleting: a `.cache` folder may hold downloaded ML models, and
some caches belong to running programs. Prefer each tool's own command (`pip cache purge`,
`uv cache clean`, `npm cache clean --force`) over deleting folders by hand.

## CLI

```
windirstat-mcp D:\
```

prints the same JSON without starting the server.

## Notes

- A full scan of a large drive takes a few minutes. Run as administrator to see system folders.
- WinDirStat is GPL-2.0 and is not bundled; this project only invokes it.

## Development

```
python -m unittest -v
```

## License

MIT
