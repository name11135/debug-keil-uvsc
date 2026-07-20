# Codex Keil UVSC Debug

**通过 Keil uVision 原生 UVSC/UVSOCK 连接让 Codex 读取和控制硬件调试会话 / Native Keil debug bridge for Codex**

[中文说明](#中文) · [English](#english)

> 本项目只调用 Keil MDK 自带的 `UVSC64.dll` / `UVSC.dll`，不抓取 uVision GUI，也不把工程、AXF、探头序列号或登录凭据打包进仓库。

## 中文

### 1. 项目用途

`debug-keil-uvsc` 是一个可安装到 Codex 的 skill，同时提供一个零第三方依赖的 Python CLI。它通过 uVision 的 UVSOCK 端口和官方 UVSC DLL，把 Keil Debug 的关键状态暴露给 Codex：

- 当前工程、Target 和输出 AXF。
- 调试状态（未进入 Debug、运行中、已暂停、硬件错误等）。
- CPU 寄存器、调用栈、表达式和内存。
- 断点列表以及原生 Keil 命令窗口。
- 进入/退出 Debug、运行、暂停、复位和单步。

### 2. 目录结构

```text
debug-keil-uvsc/
├─ SKILL.md                  # Codex skill 入口和工作流
├─ agents/openai.yaml        # Codex UI 元数据
├─ scripts/keil_uvsc.py      # 唯一控制面：JSON CLI + UVSC ctypes bridge
├─ references/uvsc-api.md    # UVSC/UVSOCK API 和故障排查笔记
├─ README.md                 # 本文档
└─ LICENSE
```

### 3. 环境要求

1. Windows。
2. Keil MDK/uVision 已安装，默认目录为 `E:\KEIL5\UV4`；其他目录通过 `--uv4-dir` 指定。
3. Python 3.10+（脚本只使用标准库：`ctypes`、`socket`、`argparse` 等）。
4. 一个可由当前 uVision 工程使用的 J-Link、ULINK、ST-Link 或其他 Keil 调试器。
5. 使用带 debug information 的新 AXF；如果工程源码已经更新，先重新 Build。

### 4. 安装为 Codex skill

解压 Release 包后，在 PowerShell 执行：

```powershell
$skill = Join-Path $env:USERPROFILE '.codex\skills\debug-keil-uvsc'
New-Item -ItemType Directory -Force -Path $skill | Out-Null
Get-ChildItem -LiteralPath 'D:\Downloads\debug-keil-uvsc' -Force |
  Copy-Item -Destination $skill -Recurse -Force

python "$skill\scripts\keil_uvsc.py" --help
```

也可以直接把当前仓库目录复制到 `%USERPROFILE%\.codex\skills\debug-keil-uvsc`。安装后重新打开 Codex，让 skill 列表刷新。

### 5. 最短调试流程

下面示例使用端口 `4328`；项目路径、Target 和探头由 `.uvprojx` 中的 Keil 配置决定：

```powershell
$py = 'python'
$bridge = "$env:USERPROFILE\.codex\skills\debug-keil-uvsc\scripts\keil_uvsc.py"
$project = 'D:\path\to\Project.uvprojx'

# 启动专用 uVision UVSOCK 实例
& $py $bridge --port 4328 launch --project $project --show

# 先确认握手和工程信息
& $py $bridge --port 4328 status

# 进入真实硬件 Debug（可能按工程设置下载 Flash 并 Run to main）
& $py $bridge --port 4328 enter

# 目标暂停后读取信息
& $py $bridge --port 4328 halt
& $py $bridge --port 4328 registers
& $py $bridge --port 4328 stack
& $py $bridge --port 4328 eval 'my_variable'
& $py $bridge --port 4328 memory 0x20000000 64
& $py $bridge --port 4328 breakpoints
```

`enter` 会产生真实调试副作用；不要仅为了测试端口连接而调用它。若已有 uVision 实例占用探头，不要同时启动第二个硬件会话。

### 6. 完整命令

全局参数：

```text
--uv4-dir <path>     Keil UV4 目录，默认 E:\KEIL5\UV4
--port <number>      UVSOCK 端口，默认 4328
```

子命令：

| 命令 | 作用 |
|---|---|
| `launch --project <file> [--show]` | 启动带 `-s <port> -sg` 的专用 uVision 实例。 |
| `status` | 读取 UVSC 连接、工程、Target 和调试状态。 |
| `serve` | 保持一条连接，逐行接收 JSON 请求。 |
| `enter` / `exit` | 进入或退出 Debug。 |
| `run` / `halt` / `reset` | 运行、暂停、复位目标。 |
| `step` / `step-into` / `step-instruction` / `step-out` | 源码级、指令级或函数级单步。 |
| `registers` | 枚举并读取寄存器。 |
| `stack` | 读取调用栈。 |
| `eval <expression>` | 执行 `EVAL <expression>`。 |
| `memory <address> <count>` | 读取内存，例如 `memory 0x20000000 64`。 |
| `breakpoints` | 执行 `BL` 列出断点。 |
| `command <text>` | 执行任意 Keil 调试命令，例如 `command 'BS main'`。 |

每个一次性命令都会输出 JSON，并以 `ok` 字段表示成功或失败：

```json
{
  "ok": true,
  "result": {
    "status": "target_stopped"
  }
}
```

### 7. 长连接 `serve`

需要连续观察调试状态时，启动：

```powershell
python .\scripts\keil_uvsc.py --port 4328 serve
```

然后逐行发送 JSON：

```text
{"action":"status"}
{"action":"registers"}
{"action":"eval","expression":"fault_code"}
{"action":"memory","address":"0x20000000","count":32}
{"action":"command","text":"BL"}
{"action":"quit"}
```

`serve` 会保持同一条 UVSC 连接，适合 Codex 通过持久终端持续读取寄存器、变量或日志。

### 8. 状态解释

| 状态 | 含义 |
|---|---|
| `not_debugging` | UVSOCK 握手成功，但还没有进入 Keil Debug。 |
| `target_executing` | 目标正在运行；读取寄存器、栈或内存前先 `halt`。 |
| `target_stopped` | 目标已暂停，可以稳定读取寄存器、栈、表达式和内存。 |
| `UVSC Internal Error` | 端口可能是普通 uVision listener，而不是 UVSOCK；使用专用 `launch` 端口。 |
| hardware error | 调试探头、目标板供电、复位线或当前 uVision 实例占用冲突。 |

### 9. Keil 工程建议

- 先 Build，确认 AXF 的时间戳晚于源码和工程文件，并且没有丢失 debug information。
- 先执行 `status`，确认工程和 Target，再执行 `enter`。
- 一个 J-Link/ULINK 只能被一个活动硬件 Debug 实例拥有；如果上一次 Codex 或 uVision 未退出，先关闭旧实例。
- 工程的 `Load Application`、`Run to main` 和 Flash Download 配置会影响 `enter` 的副作用。
- 端口可改为任意空闲本机端口，但 `launch` 和后续所有命令必须使用同一个端口。

### 10. 开发和自检

```powershell
python -m py_compile .\scripts\keil_uvsc.py
python .\scripts\keil_uvsc.py --help
```

没有 Keil 硬件时可以完成语法和 CLI 自检；`status`、寄存器读取以及 `enter` 需要实际运行的 UVSOCK/uVision 会话。

### 11. Release 包

Release 页面提供：

```text
debug-keil-uvsc-v1.0.0.zip
```

压缩包包含 skill 文件和 Python bridge，不包含 Keil 安装文件、`UVSC*.dll`、工程源码、AXF/HEX/MAP、调试探头序列号或目标板固件。

### 12. 许可

本仓库使用 MIT License。Keil MDK、uVision 和其中的 UVSC DLL 仍受 Arm/Keil 的许可证约束。

## English

### 1. What it does

`debug-keil-uvsc` is a Codex skill plus a dependency-free Python CLI for native Keil uVision debugging. It connects to a real UVSOCK listener and calls the official `UVSC64.dll` or `UVSC.dll` instead of scraping the GUI.

It exposes project/target information, debug state, registers, call stacks, expressions, memory, breakpoints, and the Keil command window. It also supports entering and leaving Debug, run, halt, reset, and step operations.

### 2. Requirements

- Windows with Keil MDK/uVision installed (default `E:\KEIL5\UV4`, override with `--uv4-dir`).
- Python 3.10+; the bridge uses only the standard library.
- A debug probe configured by the Keil project.
- A freshly built AXF that still contains debug information.

### 3. Install

Extract the release archive and copy the directory to `%USERPROFILE%\.codex\skills\debug-keil-uvsc`, then verify it with:

```powershell
python "$env:USERPROFILE\.codex\skills\debug-keil-uvsc\scripts\keil_uvsc.py" --help
```

Restart Codex after installing so the skill is discovered.

### 4. Quick start

```powershell
$bridge = "$env:USERPROFILE\.codex\skills\debug-keil-uvsc\scripts\keil_uvsc.py"
$project = 'D:\path\to\Project.uvprojx'

python $bridge --port 4328 launch --project $project --show
python $bridge --port 4328 status
python $bridge --port 4328 enter
python $bridge --port 4328 halt
python $bridge --port 4328 registers
python $bridge --port 4328 stack
python $bridge --port 4328 eval 'my_variable'
python $bridge --port 4328 memory 0x20000000 64
python $bridge --port 4328 breakpoints
```

`enter` starts the real project debug session and may program Flash or run to `main` according to the project settings. Do not use it as a connectivity-only probe.

### 5. CLI reference

The bridge accepts `--uv4-dir` and `--port` followed by `launch`, `status`, `serve`, `enter`, `exit`, `run`, `halt`, `reset`, `step`, `step-into`, `step-instruction`, `step-out`, `registers`, `stack`, `breakpoints`, `command`, `eval`, or `memory`.

Examples:

```powershell
python .\scripts\keil_uvsc.py --uv4-dir 'C:\Keil_v5\UV4' --port 5000 status
python .\scripts\keil_uvsc.py --port 4328 command 'BS main'
python .\scripts\keil_uvsc.py --port 4328 memory 0x20000000 128
```

All one-shot commands return JSON with an `ok` flag. `serve` accepts one JSON request per line, for example `{"action":"status"}`, `{"action":"registers"}`, `{"action":"eval","expression":"fault_code"}`, and `{"action":"quit"}`.

### 6. Troubleshooting

- `not_debugging`: the UVSOCK connection works, but Debug has not been entered.
- `target_executing`: halt the target before reading stable registers, stack, expressions, or memory.
- `UVSC Internal Error`: use `launch` with a dedicated `-s` port rather than an arbitrary uVision TCP listener.
- Hardware errors: check probe ownership, board power, reset wiring, and whether another uVision instance is active.
- Rebuild the AXF before debugging when source timestamps are newer or symbols are missing.

### 7. Release and license

The release asset is `debug-keil-uvsc-v1.0.0.zip`. It contains only the skill and bridge source; Keil binaries, projects, firmware, and probe identifiers are intentionally excluded. The repository is MIT licensed, while Keil MDK/uVision remains governed by its Arm/Keil license.

