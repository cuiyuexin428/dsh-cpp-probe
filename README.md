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

## 安装（标准组合包方式）

这是一个声明了 `dsh.bundle` 的组合包（bundle），直接用 `dsh plugin` 装进 profile：

```sh
dsh plugin --profile web add dsh-cpp-probe
```

装好后它会自动把 `cpp-probe` 插件层加入该 profile 的 bundle 层，并注册 `cpp_trace` / `cpp_probe` 两个工具。安装后需**重启 `dsh web`** 才会生效。

> 发布：本插件发布在 npm（`dsh-cpp-probe`）。也可以用 GitHub 源码规格安装：
> ```sh
> dsh plugin --profile web add github:cuiyuexin428/dsh-cpp-probe
> ```

## 配置

插件默认配置在 `cordis.patch.yml` 的 `config` 里（随包携带）。**不需要**手动改 `agent.cordis.yml`。要覆盖默认值，用你 profile 的 `cordis.patch.yml` 按 id 覆写：

```yaml
# $DSH_HOME/profiles/<name>/cordis.patch.yml
- id: cpp-probe
  config:
    python: python                                    # python 可执行(默认 python)
    defaultTimeoutSeconds: 120                        # 整次超时(秒)
    cdbPath: 'C:\\Windows Kits\\10\\Debuggers\\x64\\cdb.exe'   # cdb 绝对路径(按你的环境改)
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
