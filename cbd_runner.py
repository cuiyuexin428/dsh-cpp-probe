import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional


_SENTINEL_CMD = ".echo __S_{}__"


def _make_sentinel() -> str:
    return f"__S_{uuid.uuid4().hex[:8]}__"


def escape_dx_name(name: str) -> str:
    """转义函数名，防止 C++ 模板/命名空间字符破坏 CDB 命令"""
    return name.replace("\\", "\\\\").replace('"', '\\"')


_CRT_LEAK_RE = re.compile(
    r"(?:Detected memory leaks|"
    r"Dumping objects|"
    r"\{\-?\d+\}\s+(?:normal|client) block at 0x[0-9A-Fa-f]+|"
    r"Object dump complete)"
)


def _strip_crt_leaks(output: str) -> str:
    return "\n".join(
        line for line in output.splitlines()
        if not _CRT_LEAK_RE.search(line)
    )


class CbdRunner:
    def __init__(self, config: dict, timeout: Optional[float] = None):
        root = Path(__file__).parent
        self.cdb_path = str(root / config["cdb_path"])
        self.symbol_paths = [str(root / p) for p in config.get("symbol_paths", [])]
        self.source_paths = [str(root / p) for p in config.get("source_paths", [])]
        self.timeout = config.get("timeout", timeout)
        self._reload_done = {}


    @staticmethod
    def load_config(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_reload_commands(self) -> list[str]:
        cmds = []
        for sp in self.symbol_paths:
            cmds.append(f".sympath+ {sp}")
        for sp in self.source_paths:
            cmds.append(f".srcpath+ {sp}")
        if self.symbol_paths or self.source_paths:
            cmds.append(".reload /f")
        return cmds

    def _invoke_cdb(self, trace_file: str, commands: list[str],
                    with_reload: bool = True) -> str:
        all_cmds = []
        if with_reload:
            all_cmds.extend(self._build_reload_commands())
        all_cmds.extend(commands)
        all_cmds.append("q")

        stdin = "\n".join(all_cmds) + "\n"

        proc = subprocess.run(
            [self.cdb_path, "-z", trace_file],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return _strip_crt_leaks(proc.stdout)

    def run(self, trace_file: str, commands: list[str],
            with_reload: bool = True) -> str:
        return self._invoke_cdb(trace_file, commands, with_reload)

    def run_exe(self, exe_path: str, commands: list[str],
                with_reload: bool = True, timeout=None,
                args=None, workdir=None) -> str:
        """在【实时运行】的 exe 上执行命令(非 TTD trace)。

        等价于 cdb <exe>: 设日志断点后 `g` 运行, 程序实时执行, 无 trace 重放。
        用于"自动加输出语句"式的观测: 不改源码、不重编、改 json 即可增删输出。
        """
        cmds = []
        if with_reload:
            cmds.extend(self._build_reload_commands())
        cmds.extend(commands)
        cmds.append("q")
        stdin = "\n".join(cmds) + "\n"

        cmd = [self.cdb_path, exe_path]
        if args:
            cmd.extend(args)

        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout if timeout is not None else self.timeout,
            cwd=workdir,
        )
        return _strip_crt_leaks(proc.stdout)

    def run_batch(self, trace_file: str,
                  command_groups: list[list[str]]) -> list[str]:
        """一次 CDB 会话运行多组命令，返回各组输出"""
        all_cmds = list(self._build_reload_commands())
        sentinels = []

        for group in command_groups:
            all_cmds.extend(group)
            s = _make_sentinel()
            all_cmds.append(_SENTINEL_CMD.format(s))
            sentinels.append(s)

        all_cmds.append("q")
        stdin = "\n".join(all_cmds) + "\n"

        proc = subprocess.run(
            [self.cdb_path, "-z", trace_file],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        output = proc.stdout

        results = []
        prev = 0
        for s in sentinels:
            idx = output.find(s, prev)
            if idx >= 0:
                results.append(output[prev:idx])
                prev = idx + len(s)
            else:
                results.append(output[prev:])
                break
        return results

    def _parse_call_grid(self, output: str) -> list[dict]:
        result = []
        for line in output.splitlines():
            if not re.match(r"=\s+\[0x[0-9a-fA-F]+\]", line):
                continue
            cols = [c.strip() for c in line.split(" - ")]
            if len(cols) >= 10:
                result.append({
                    "func": cols[6],
                    "time_start": cols[4],
                    "time_end": cols[5],
                })
        return result

    def get_call_grid(self, trace_file: str, func: str) -> list[dict]:
        safe_func = escape_dx_name(func)
        cmd = f'dx -g @$cursession.TTD.Calls("{safe_func}")'
        output = self.run(trace_file, [cmd])
        return self._parse_call_grid(output)

    def get_call_grid_batch(self, trace_file: str,
                            funcs: list[str]) -> list[list[dict]]:
        """批量查询多个函数的调用网格"""
        groups = []
        for func in funcs:
            safe_func = escape_dx_name(func)
            groups.append([f'dx -g @$cursession.TTD.Calls("{safe_func}")'])
        outputs = self.run_batch(trace_file, groups)
        return [self._parse_call_grid(o) for o in outputs]

    def get_call_count(self, trace_file: str, func: str) -> int:
        return len(self.get_call_grid(trace_file, func))

    def get_call_times(self, trace_file: str, func: str) -> list[str]:
        grid = self.get_call_grid(trace_file, func)
        return [row["time_start"] for row in grid]

    def get_call_times_batch(self, trace_file: str,
                             funcs: list[str]) -> list[list[str]]:
        """批量查询多个函数的调用时间"""
        grids = self.get_call_grid_batch(trace_file, funcs)
        return [[row["time_start"] for row in g] for g in grids]

    def ttd_cmd(self, trace_file: str, position: str, cmd: str) -> str:
        commands = [f"!tt {position}", cmd]
        return self.run(trace_file, commands)
