# dsh-cpp-probe

为 **DeepSeek Harness** 提供 **C++ 程序运行时信息** 的插件。两个配合使用的工具：

| 工具 | 机制 | 用途 |
|---|---|---|
| **`cpp_trace`** | 一次 cdb 会话设**多个断点**，每个命中按 `print` 模板**打印变量**，保留运行时序 | **替换手打 print**，大批量观察运行时状态 |
| **`cpp_probe`** | 一次 cdb 会话打**一个条件断点**，命中**输出调用堆栈** | 用 `cpp_trace` 分析出可疑点后，**往下钻看调用路径** |

**共同点**：实时运行（无 TTD 录制/重放）、不改源码、不重编、改配置即可增删断点、互不干扰。

## 依赖

- **Windows** + **WinDbg/CDB**（Windows Debugging Tools）
- **Python 3.10+**（默认 `python`，可用配置覆盖）
- 一个**带符号/源码的 Debug 构建**（PDB，源码行断点用）

## 安装

```sh
dsh plugin --profile web add dsh-cpp-probe
```

## 配置

在 agent 预设的 `agent.cordis.yml` 里加一行：

```yaml
- id: cpp-probe
  name: 'dsh-cpp-probe'
  config:
    python: python                                    # python 可执行(默认 python)
    cdbPath: 'C:\\Windows Kits\\10\\Debuggers\\x64\\cdb.exe'   # cdb 绝对路径
    symbolPaths: ['C:\\path\\to\\build\\bin\\Debug']  # 你的 PDB/DLL 目录
    sourcePaths: ['C:\\path\\to\\src']                # 源码根目录
```

> cdb/符号/源码路径通过插件配置注入（`cdbPath`/`symbolPaths`/`sourcePaths`），执行时动态生成 config.json。也可以直接改插件目录 `config.json` 作为默认值。

## 用法

**`cpp_trace`**（多断点打印变量，替换 print）：

```jsonc
{
  "exe": "C:\\path\\to\\yourapp.exe",
  "breakpoints": [
    { "name": "Merge", "at": "C:\\path\\to\\YourClass.cpp:43",
      "print": "pass={pass} e1.id={e1->id}" }
  ]
}
```
命中输出：`Merge #1 pass=1 e1.id=6`（按运行时序）。

**`cpp_probe`**（条件断点看栈）：

```jsonc
{
  "exe": "C:\\path\\to\\yourapp.exe",
  "breakpoints": [
    { "name": "Merge", "at": "C:\\path\\to\\YourClass.cpp:43",
      "condition": "e1->id > 0", "stack": true }
  ]
}
```
命中输出：`Merge #1` + 完整调用栈（`module!function` 帧，按运行时序）。

## 许可

MIT
