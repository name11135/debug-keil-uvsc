---
name: debug-keil-uvsc
description: Connect Codex to native Keil uVision debug sessions through UVSC/UVSOCK. Use for Keil Debug, uVision online debugging, reading registers, call stacks, variables or memory, evaluating expressions, inspecting breakpoints, and controlling run, halt, reset or step operations on .uvprojx/.uvproj projects.
---

# Keil UVSC Debug

Use `scripts/keil_uvsc.py` as the only control surface. It emits JSON and uses the official `UVSC64.dll`/`UVSC.dll`; it does not scrape the Keil GUI.

## Workflow

1. Identify the exact `.uvprojx`/`.uvproj`, target, probe and current AXF.
2. Build first when the AXF is older than the project/source files. Use `build-keil` and keep the AXF with debug information.
3. Start a dedicated UVSOCK instance if the existing uVision process was not launched with `-s <port>`:

   ```powershell
   python scripts/keil_uvsc.py --port 4328 launch --project "D:\path\Project.uvprojx"
   ```

4. Verify the handshake before any debug side effect:

   ```powershell
   python scripts/keil_uvsc.py --port 4328 status
   ```

   A `-s` uVision server can terminate when the UVSC client disconnects. For an interactive debug session, keep one connection open:

   ```powershell
   python scripts/keil_uvsc.py --port 4328 serve
   ```

   Send one JSON object per line, for example `{"action":"status"}`, `{"action":"registers"}`, `{"action":"eval","expression":"fault"}`, or `{"action":"quit"}`. When running through Codex, keep the exec session ID and use `write_stdin` for subsequent requests.

5. Prefer read-only commands:

   ```powershell
   python scripts/keil_uvsc.py --port 4328 registers
   python scripts/keil_uvsc.py --port 4328 stack
   python scripts/keil_uvsc.py --port 4328 eval "variable_name"
   python scripts/keil_uvsc.py --port 4328 memory 0x20000000 64
   python scripts/keil_uvsc.py --port 4328 breakpoints
   ```

6. Use control commands only when the user asks to alter execution:

   ```powershell
   python scripts/keil_uvsc.py --port 4328 enter
   python scripts/keil_uvsc.py --port 4328 halt
   python scripts/keil_uvsc.py --port 4328 run
   python scripts/keil_uvsc.py --port 4328 reset
   python scripts/keil_uvsc.py --port 4328 step
   python scripts/keil_uvsc.py --port 4328 step-into
   python scripts/keil_uvsc.py --port 4328 step-out
   ```

`enter` starts the project's configured hardware debug session. Keil may download Flash and run to `main` according to the project settings. Do not issue it merely to test connectivity.

## Interpretation

- `not_debugging`: UVSOCK works, but Keil has not entered Debug mode.
- `target_executing`: halt before requesting registers, stack or memory.
- `target_stopped`: registers, stack, expressions and memory are stable to read.
- `UVSC Internal Error`: the port is usually another uVision internal listener rather than a UVSOCK server; launch a dedicated `-s` port.
- A J-Link/ST-Link/ULINK session can be owned by only one active uVision debug instance. Do not start a second hardware session while another instance owns the probe.

## Output

Report the project, target, AXF freshness, UVSOCK port, debug state, probe, requested observations and exact failures. Preserve absolute paths.

See [references/uvsc-api.md](references/uvsc-api.md) when extending the bridge or diagnosing protocol errors.
