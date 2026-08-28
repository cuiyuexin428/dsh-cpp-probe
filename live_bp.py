"""
live_bp.py - 【非 TTD】条件断点 · 命中输出调用栈

给 AI 提供程序运行时信息：在真实 exe 上设源码行断点, 命中(且条件满足)时
输出调用堆栈。不改源码、不重编、无 trace 重放。json 配置简单。

一次 cdb 会话加载全部断点后运行一次, 保留运行时序。

配置 JSON:
{
    "exe": "..\\cat-code\\build\\bin\\Debug\\MainApp-old.exe",
    "workdir": "..\\cat-code\\build\\bin\\Debug",
    "timeout": 90,
    "output": "output\\live_bp_out\\out.txt",
    "breakpoints": [
        {"name": "Merge", "at": "C:\\...\\CATEdgeCleaner.cpp:43",
         "condition": "e1->id > 0",   // 可选: 条件断点, 为真才记录
         "stack": true}                // 命中输出调用栈
    ]
}

输出(按运行时序):
    <name> #<seq>
        module!function
        module!function
        ...
"""

import json
import os
import re
import sys
from pathlib import Path
from cbd_runner import CbdRunner
from ttd_bp import strip_markup


MAX_BP = 20


def resolve_root_path(root, p):
    if not p:
        return None
    if not os.path.isabs(p):
        p = str(root / p)
    return os.path.normpath(p)


def _frame(line: str):
    """从 cdb k 输出行提取 module!function 栈帧, 匹配不到返回 None。"""
    m = re.search(r"(?:[0-9a-f`]+[ ]+){1,2}([a-zA-Z_][\w<>:]+![^\s+]+)", line)
    return m.group(1) if m else None


def parse_hits_stack(output: str, bp_names: list[str]) -> list[dict]:
    """按输出顺序(运行时序)收集命中, 每断点独立 seq, 各带堆栈帧。"""
    segments = []
    cur = None
    for line in output.splitlines():
        s = strip_markup(line).strip()
        m = re.match(r"---HIT:(\d+)---", s)
        if m:
            if cur is not None:
                segments.append(cur)
            cur = {"bp": int(m.group(1)), "frames": []}
            continue
        if cur is not None:
            f = _frame(s)
            if f:
                cur["frames"].append(f)
                continue
    if cur is not None:
        segments.append(cur)

    seq_by_bp = {}
    ordered = []
    for h in segments:
        i = h["bp"]
        seq_by_bp[i] = seq_by_bp.get(i, 0) + 1
        ordered.append({"name": bp_names[i], "seq": seq_by_bp[i], "frames": h["frames"]})
    return ordered


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    cfg_path = sys.argv[1]
    with open(cfg_path, encoding="utf-8") as f:
        config = json.load(f)
    root = Path(os.path.abspath(cfg_path)).parent

    runner = CbdRunner(CbdRunner.load_config(os.environ.get("CPP_PROBE_CONFIG") or str(Path(__file__).parent / "config.json")))

    exe = resolve_root_path(root, config["exe"])
    workdir = resolve_root_path(root, config.get("workdir"))
    args = config.get("args", [])
    timeout = config.get("timeout")
    output_path = resolve_root_path(root, config["output"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    bps = config["breakpoints"]
    if len(bps) > MAX_BP:
        print(f"ERROR: too many breakpoints ({len(bps)} > {MAX_BP})")
        sys.exit(1)

    bu_cmds = []
    for i, bp in enumerate(bps):
        at = bp["at"]
        cond = bp.get("condition", "").strip()
        if cond:
            # 条件断点: .if (@@c++(cond)) {...}, @@c++ 强制 C++ 求值器才能解析局部成员
            bu = f'bu `{at}` ".if (@@c++({cond})) {{.echo ---HIT:{i}---;k}};gc"'
        else:
            bu = f'bu `{at}` ".echo ---HIT:{i}---;k;gc"'
        bu_cmds.append(bu)
        print(f"[{bp['name']}] {at}  cond={{'{cond}'}}")

    print(f"Running ONE cdb session with {len(bps)} breakpoint(s)...")
    output = runner.run_exe(exe, bu_cmds + ["g"], timeout=timeout, args=args, workdir=workdir)

    bp_names = [b["name"] for b in bps]
    ordered = parse_hits_stack(output, bp_names)

    lines = []
    for h in ordered:
        lines.append(f"{h['name']} #{h['seq']}")
        for f in h["frames"]:
            lines.append(f"    {f}")

    print(f"  total hits: {len(ordered)}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Written: {output_path} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
