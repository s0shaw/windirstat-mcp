import json, os, tempfile, unittest

import windirstat_mcp as w

HEADER = '"Name","Files","Folders","Logical Size","Physical Size","Attributes","Last Change","WinDirStat Attributes","Index"\n'
MB = 2**20


def row(name, size, files=0, folders=0):
    return f'"{name}",{files},{folders},{size},{size},"A",2026-01-01T00:00:00Z,0x0,0x0\n'


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        fd, self.csv = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(HEADER)
            f.write(row("C:\\", 1000 * MB, 5, 4))
            f.write(row("C:\\Users\\a\\AppData\\Local\\Temp", 300 * MB, 2, 1))
            f.write(row("C:\\Users\\a\\AppData\\Local\\Temp\\Cache", 200 * MB, 1, 0))  # nested: must not double count
            f.write(row("C:\\Users\\a\\AppData\\Local\\Temp\\Cache\\big.bin", 200 * MB))
            f.write(row("C:\\Users\\a\\game.exe.old", 150 * MB))
            f.write(row("C:\\Users\\a\\small.tmp", 1 * MB))  # below min_mb
            f.write(row("C:\\Users\\a\\movie.mkv", 400 * MB))

    def tearDown(self):
        os.remove(self.csv)

    def test_analyze(self):
        r = w.analyze(self.csv, top=2, min_mb=100)
        self.assertEqual(r["root"], "C:\\")
        self.assertEqual([(h["path"], h["reason"]) for h in r["cleanup_candidates"]], [
            ("C:\\Users\\a\\AppData\\Local\\Temp", "user temp"),
            ("C:\\Users\\a\\game.exe.old", "temp/backup file"),
        ])
        self.assertEqual(r["cleanup_candidates_mb"], 450.0)
        self.assertEqual([f["path"] for f in r["largest_files"]],
                         ["C:\\Users\\a\\movie.mkv", "C:\\Users\\a\\AppData\\Local\\Temp\\Cache\\big.bin"])


class ProtocolTest(unittest.TestCase):
    def test_handshake_and_errors(self):
        res, err = w.handle({"method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(res["protocolVersion"], "2025-06-18")
        res, _ = w.handle({"method": "tools/list"})
        self.assertEqual(res["tools"][0]["name"], "windirstat_scan")
        _, err = w.handle({"method": "nope"})
        self.assertEqual(err["code"], -32601)
        res, _ = w.handle({"method": "tools/call", "params": {"name": "windirstat_scan",
                                                             "arguments": {"path": "Z:\\does\\not\\exist"}}})
        self.assertTrue(res["isError"])
        json.dumps(res)


if __name__ == "__main__":
    unittest.main()
