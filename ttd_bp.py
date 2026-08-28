"""
ttd_bp.py - TTD 源码行延迟断点，打印命中时的变量值

配置 JSON:
{
    "trace": "trace/old/MainApp-old01.run",
    "output": "output/ttd_bp_out/old.txt",
    "breakpoints": [
        {
            "name": "InnerLoop",
            "at": "C:\\path\\to\\file.cpp:31",
            "print": "i={i} e1.id={e1->id}"
        }
    ]
}

输出每行:
    name #N i=0 e1.id=6
"""

import json
import os
import re
import sys
from pathlib import Path
from cbd_runner import CbdRunner


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
DML_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_markup(text: str) -> str:
    """去除 ANSI/DML 颜色和格式化字符"""
    text = ANSI_ESCAPE.sub("", text)
    text = DML_ESCAPE.sub("", text)
    return text


def parse_print_exprs(template: str) -> list[tuple[str, str]]:
    """解析 {var} {ptr->field} 为 [(标记, dx表达式)], 跳过 {name} {n}"""
    result = []
    for m in re.finditer(r"\{([^{}]+)\}", template):
        expr = m.group(1)
        if expr in ("name", "n"):
            continue
        result.append((m.group(0), expr))
    return result


def build_dx_cmd(expr: str) -> str:
    """{var} -> dx var; {ptr->field} -> dx ptr->field"""
    return f"dx {expr}"


def parse_dx_value(output: str, var_name: str) -> str:
    """从dx输出提取简单值"""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(var_name) or (var_name in stripped and ":" in stripped):
            parts = stripped.split(":", 1)
            if len(parts) >= 2:
                val = parts[1].strip()
                if "[" in val:
                    val = val[:val.index("[")].strip()
                return val
    return "?"


def format_output(name: str, n: int, template: str, dx_results: dict) -> str:
    """替换模板中的{name} {n} {expr}"""
    result = template
    result = result.replace("{name}", name)
    result = result.replace("{n}", str(n))
    for placeholder, expr in parse_print_exprs(template):
        val = dx_results.get(expr, "?")
        result = result.replace(placeholder, str(val))
    return result


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    cfg_path = sys.argv[1]
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    root = Path(cfg_path).parent
    cdb_cfg = CbdRunner.load_config(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    )
    runner = CbdRunner(cdb_cfg)

    trace = str(root / config["trace"])
    output_path = str(root / config["output"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    all_lines = []

    for bp in config["breakpoints"]:
        name = bp["name"]
        at = bp["at"]
        pfmt = bp.get("print", "")

        exprs = parse_print_exprs(pfmt)

        dx_cmds = ";".join(build_dx_cmd(e) for _, e in exprs)
        if dx_cmds:
            dx_cmds = dx_cmds + ";"

        bu_cmd = (
            f'bu `{at}` '
            f'"r $t0=@$t0+1;.echo ---HIT---;'
            f'{dx_cmds}'
            f'gc"'
        )

        print(f"[{name}] {at} ({len(exprs)} exprs)")

        output = runner.run(trace, [bu_cmd, "!tt 0:0", "g", "bc *"])

        hits = []
        current_dx = {}
        in_hit = False

        for line in output.splitlines():
            stripped = strip_markup(line).strip()

            if "---HIT---" in stripped:
                if current_dx:
                    hits.append(current_dx)
                current_dx = {}
                in_hit = True
                continue

            if in_hit:
                m = re.match(r"(\S+(?:->\S+)*)\s*:\s*(.+)", stripped)
                if m:
                    var = m.group(1).strip()
                    val = m.group(2).strip()
                    if "[" in val:
                        val = val[:val.index("[")].strip()
                    current_dx[var] = val
                    continue

        if current_dx:
            hits.append(current_dx)

        print(f"  {len(hits)} hits")

        for n, dx_vals in enumerate(hits, 1):
            line = format_output(name, n, pfmt, dx_vals)
            all_lines.append(line)
            if n <= 3 or n > len(hits) - 2:
                print(f"  {line}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines) + "\n")

    print(f"\nWritten: {output_path} ({len(all_lines)} lines)")


if __name__ == "__main__":
    main()
