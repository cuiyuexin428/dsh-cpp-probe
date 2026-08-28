"""
trace_bp.py - 【非 TTD】多断点打印变量(对标 ttd_bp.py, 替换打 print 语句)

一次 cdb 会话加载【全部】断点后运行一次, 每个断点命中时按 print 模板打印
变量值, 保留跨断点的运行时序。不改源码、不重编、改 json 增删断点。

配置 JSON:
{
    "exe": "..\\cat-code\\build\\bin\\Debug\\MainApp-old.exe",
    "workdir": "..\\cat-code\\build\\bin\\Debug",
    "timeout": 90,
    "output": "output\\trace_bp_out\\out.txt",
    "breakpoints": [
        {"name": "InnerLoop", "at": "C:\\abs\\file.cpp:31", "print": "i={i} e1.id={e1->id}"},
        {"name": "MergeFound", "at": "C:\\abs\\file.cpp:42", "print": "pass={pass}"}
    ]
}

输出(按运行时序), 每行: name #seq <print 模板替换后的值>
"""

import json
import os
import re
import sys
from pathlib import Path
from cbd_runner import CbdRunner
from ttd_bp import parse_print_exprs, build_dx_cmd, format_output, strip_markup


MAX_BP = 20


def resolve_root_path(root, p):
    if not p:
        return None
    if not os.path.isabs(p):
        p = str(root / p)
    return os.path.normpath(p)


def parse_hits_ordered(output: str, bp_names: list[str]) -> list[dict]:
    """按输出顺序(运行时序)收集命中, 每断点独立 seq, 各带变量 dict。"""
    raw = []
    cur = None
    for line in output.splitlines():
        stripped = strip_markup(line).strip()
        m = re.match(r"---HIT:(\d+)---", stripped)
        if m:
            if cur is not None:
                raw.append(cur)
            cur = {"bp": int(m.group(1)), "vals": {}}
            continue
        if cur is not None:
            m2 = re.match(r"(\S+(?:->\S+)*)\s*:\s*(.+)", stripped)
            if m2:
                var = m2.group(1).strip()
                val = m2.group(2).strip()
                if "[" in val:
                    val = val[:val.index("[")].strip()
                cur["vals"][var] = val
                continue
    if cur is not None:
        raw.append(cur)

    seq_by_bp = {}
    ordered = []
    for h in raw:
        i = h["bp"]
        seq_by_bp[i] = seq_by_bp.get(i, 0) + 1
        ordered.append({"name": bp_names[i], "seq": seq_by_bp[i], "vals": h["vals"]})
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
        pfmt = bp.get("print", "")
        exprs = parse_print_exprs(pfmt)
        dx_cmds = ";".join(build_dx_cmd(e) for _, e in exprs)
        if dx_cmds:
            dx_cmds = dx_cmds + ";"
        bu_cmds.append(
            f'bu `{at}` "r $t{i}=@$t{i}+1;.echo ---HIT:{i}---;{dx_cmds}gc"'
        )
        print(f"[{bp['name']}] {at} ({len(exprs)} exprs)")

    print(f"Running ONE cdb session with {len(bps)} breakpoint(s), runtime order preserved...")
    output = runner.run_exe(exe, bu_cmds + ["g"], timeout=timeout, args=args, workdir=workdir)

    bp_names = [b["name"] for b in bps]
    ordered = parse_hits_ordered(output, bp_names)

    lines = []
    for h in ordered:
        pfmt = next(b["print"] for b in bps if b["name"] == h["name"])
        line = format_output(h["name"], h["seq"], pfmt, h["vals"])
        lines.append(line)

    print(f"  total hits: {len(ordered)}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Written: {output_path} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
