// @dsh-plugins/cpp-probe —— 给 AI 提供 C++ 程序运行时信息(两个配合使用的工具)
//
//   cpp_trace : 一次 cdb 会话设多个断点, 每个命中按 print 模板打印预设变量(替换打 print), 保留运行时序
//   cpp_probe : 一次 cdb 会话打一个条件断点, 命中时输出调用堆栈(配合 cpp_trace 深入分析)
//
// 可移植性: cdb/符号/源码路径由插件 Config 注入(cdbPath/symbolPaths/sourcePaths),
// 执行时动态生成 config.json(经 CPP_PROBE_CONFIG 传给 python 脚本), 不再依赖写死的 config.json。
// 依赖: 部署机需 Python 3.10+ 与 Windows Debugging Tools(cdb), 见 README。

import { spawn } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineTool } from '@deepseek-ai/dsh-tools'
import z from '@deepseek-ai/schemastery'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))

export const name = 'cpp-probe'

/** 插件级默认配置(可由 agent.cordis.yml 的插件行 config 覆盖)。 */
export const Config = z.object({
  python: z.string().default('python'),
  defaultTimeoutSeconds: z.number().default(120),
  cdbPath: z.string().default(''),
  symbolPaths: z.array(z.string()).default([]),
  sourcePaths: z.array(z.string()).default([]),
})

export const inject = ['tools']

function runProc({ argv, cwd, timeoutMs, env }) {
  return new Promise((resolve, reject) => {
    let child
    try {
      child = spawn(argv[0], argv.slice(1), {
        cwd,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        shell: false,
        env,
      })
    } catch (err) {
      reject(err)
      return
    }
    let out = ''
    let err = ''
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (d) => { out += d })
    child.stderr.on('data', (d) => { err += d })
    const timer = timeoutMs > 0 ? setTimeout(() => { try { child.kill('SIGKILL') } catch {} }, timeoutMs) : null
    child.on('error', (e) => { if (timer) clearTimeout(timer); reject(e) })
    child.on('close', (code) => { if (timer) clearTimeout(timer); resolve({ code: code ?? -1, out, err }) })
  })
}

/** 合并默认 config.json 与插件 Config, 得到 cdb/符号/源码配置。 */
function resolveProbeConfig(config) {
  let base = {}
  const baseFile = join(ROOT, 'config.json')
  if (existsSync(baseFile)) {
    try { base = JSON.parse(readFileSync(baseFile, 'utf8')) } catch { /* 忽略 */ }
  }
  return {
    cdb_path: config.cdbPath || base.cdb_path || '',
    symbol_paths: config.symbolPaths && config.symbolPaths.length
      ? config.symbolPaths
      : (base.symbol_paths || []),
    source_paths: config.sourcePaths && config.sourcePaths.length
      ? config.sourcePaths
      : (base.source_paths || []),
    timeout: null,
  }
}

/** 跑一个 python 探针脚本, 注入动态 config.json, 读回 output 文件。 */
async function runProbe(script, payload, config, pythonOverride, timeoutSec) {
  const python = pythonOverride || config.python || 'python'
  const tmpid = `${script.replace(/\.py$/, '')}_${process.pid}_${Date.now()}`
  const cfgFile = join(ROOT, `.tmp-${tmpid}.config.json`)
  const payloadFile = join(ROOT, `.tmp-${tmpid}.payload.json`)
  const outFile = join(ROOT, `.tmp-${tmpid}.out.txt`)

  payload.output = outFile
  writeFileSync(cfgFile, JSON.stringify(resolveProbeConfig(config)))
  writeFileSync(payloadFile, JSON.stringify(payload))

  try {
    const r = await runProc({
      argv: [python, script, payloadFile],
      cwd: ROOT,
      timeoutMs: (timeoutSec || config.defaultTimeoutSeconds || 120) * 1000,
      env: { ...process.env, CPP_PROBE_CONFIG: cfgFile },
    })
    const text = existsSync(outFile)
      ? readFileSync(outFile, 'utf8')
      : (r.err || '(no output / no hits)')
    return text.trim() || '(no hits)'
  } catch (e) {
    return `[cpp-probe 失败] ${e.message}`
  } finally {
    rmSync(cfgFile, { force: true })
    rmSync(payloadFile, { force: true })
    rmSync(outFile, { force: true })
  }
}

export function apply(ctx, config) {
  // 工具一: cpp_trace —— 多断点打印变量(替换 print)
  ctx.tools.register(defineTool({
    name: 'cpp_trace',
    description:
      '一次 cdb 会话设【多个断点】, 每个断点命中时按 print 模板打印预设变量(替换手打 print)。' +
      '不改源码、不重编、保留运行时序。用于大批量观察运行时状态, 供人/AI 分析。',
    parameters: {
      exe: { type: 'string', required: true, description: '目标可执行文件绝对路径' },
      workdir: { type: 'string', description: '程序工作目录(默认 exe 所在目录)' },
      breakpoints: {
        type: 'array',
        required: true,
        description: '断点列表。每个含 name(名称), at(源码位置 file.cpp:行号), print(打印模板, 如 "i={i} e1.id={e1->id}"), condition(可选)',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string' },
            at: { type: 'string' },
            print: { type: 'string' },
            condition: { type: 'string' },
          },
          required: ['name', 'at'],
        },
      },
      timeoutSeconds: { type: 'integer', description: '整次超时(秒), 默认 120' },
      python: { type: 'string', description: 'python 可执行路径(可选, 覆盖插件配置)' },
    },
    output: { schema: { type: 'string' }, render: (_a, v) => [{ type: 'text', text: String(v) }] },
    timeoutMs: 3600_000,
    async execute(args, exec) {
      const timeSec = args.timeoutSeconds || config.defaultTimeoutSeconds || 120
      return runProbe('trace_bp.py', {
        exe: args.exe,
        workdir: args.workdir,
        args: [],
        timeout: timeSec,
        output: '',
        breakpoints: args.breakpoints || [],
      }, config, args.python, timeSec)
    },
    presentCall: (args) => ({
      card: 'terminal',
      title: `cpp_trace: ${(args.breakpoints || []).map((b) => b.name).join(',')}`,
      description: args.exe,
    }),
    presentResult: (_a, r) => {
      const t = r.content.map((b) => (b.type === 'text' ? b.text : '')).join('\n')
      return { card: 'terminal', output: t, exitCode: r.isError ? 1 : 0 }
    },
  }))

  // 工具二: cpp_probe —— 一个条件断点, 命中输出调用堆栈
  ctx.tools.register(defineTool({
    name: 'cpp_probe',
    description:
      '一次 cdb 会话打【一个条件断点】, 命中时输出调用堆栈。' +
      '先由 cpp_trace 批量打印变量定位可疑点后, 用本工具查看该点的完整调用路径。',
    parameters: {
      exe: { type: 'string', required: true, description: '目标可执行文件绝对路径' },
      workdir: { type: 'string', description: '程序工作目录(默认 exe 所在目录)' },
      breakpoints: {
        type: 'array',
        required: true,
        description: '通常一个断点。每个含 name, at(源码位置), condition(可选, C++ 条件, 为真才命中, 如 e1->id > 0), stack(可选, 默认 true)',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string' },
            at: { type: 'string' },
            condition: { type: 'string' },
            stack: { type: 'boolean' },
          },
          required: ['name', 'at'],
        },
      },
      timeoutSeconds: { type: 'integer', description: '整次超时(秒), 默认 120' },
      python: { type: 'string', description: 'python 可执行路径(可选, 覆盖插件配置)' },
    },
    output: { schema: { type: 'string' }, render: (_a, v) => [{ type: 'text', text: String(v) }] },
    timeoutMs: 3600_000,
    async execute(args, exec) {
      const timeSec = args.timeoutSeconds || config.defaultTimeoutSeconds || 120
      return runProbe('live_bp.py', {
        exe: args.exe,
        workdir: args.workdir,
        args: [],
        timeout: timeSec,
        output: '',
        breakpoints: args.breakpoints || [],
      }, config, args.python, timeSec)
    },
    presentCall: (args) => ({
      card: 'terminal',
      title: `cpp_probe: ${(args.breakpoints || []).map((b) => b.name).join(',')}`,
      description: args.exe,
    }),
    presentResult: (_a, r) => {
      const t = r.content.map((b) => (b.type === 'text' ? b.text : '')).join('\n')
      return { card: 'terminal', output: t, exitCode: r.isError ? 1 : 0 }
    },
  }))
}
