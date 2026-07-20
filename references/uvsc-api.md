# UVSC notes

## Native installation

Keil MDK normally provides these beside `UV4.exe`:

- `UVSC64.dll` for 64-bit clients
- `UVSC.dll` for 32-bit clients
- `UVSCWrapper.dll` as a higher-level 32-bit C++/JNI wrapper

Launch uVision with `UV4.exe <project> -s <port>` to create a real UVSOCK listener. A random TCP listener owned by `UV4.exe` is not necessarily UVSOCK; validate it with `UVSC_GEN_UVSOCK_VERSION` and `UVSC_PRJ_GET_CUR_TARGET`.

## Operations used by the bridge

- Connection: `UVSC_Init`, `UVSC_OpenConnection`, `UVSC_CloseConnection`, `UVSC_UnInit`
- Project: `UVSC_PRJ_GET_CUR_TARGET`, `UVSC_PRJ_GET_OUTPUTNAME`
- State/control: `UVSC_DBG_STATUS`, `UVSC_DBG_ENTER`, `UVSC_DBG_EXIT`, `UVSC_DBG_START_EXECUTION`, `UVSC_DBG_STOP_EXECUTION`, `UVSC_DBG_RESET`, and step operations
- Inspection: `UVSC_DBG_ENUM_REGISTER_GROUPS`, `UVSC_DBG_ENUM_REGISTERS`, `UVSC_DBG_READ_REGISTERS`, `UVSC_DBG_ENUM_STACK`, `UVSC_DBG_ADR_TOFILELINE`, `UVSC_DBG_MEM_READ`
- Command window: `UVSC_DBG_EXEC_CMD`, `UVSC_GetCmdOutputSize`, `UVSC_GetCmdOutput`

The protocol uses packed structures and ASCII/local-code-page strings. The bridge definitions follow UVSC/UVSOCK 2.29 and the Qt Creator UVSC debugger plugin.

## Keil command examples

- `EVAL expression` reads an expression.
- `BL` lists breakpoints.
- `BS expression` creates a breakpoint.
- `BK expression` removes a breakpoint.
- `LOG >file`, `SLOG >file`, and `ITMLOG channel >file` can persist command, serial, and ITM output.

## Debug-session guidance

- Build the exact `.uvprojx` target first and keep the AXF with symbols.
- Start a dedicated listener with the bridge's `launch` command and verify `status` before calling `enter`.
- A probe can be owned by only one active uVision debug instance. Close stale sessions before starting another one.
- `enter` follows the project's Load Application, Flash Download, and Run to main settings; it may change the target and should be treated as a side-effecting operation.
- If `UVSC Internal Error` appears, the selected port is usually an ordinary uVision listener rather than a UVSOCK endpoint. Pick a free port and use `launch`.

## ABI reference

The packed structure declarations and command dispatch are implemented in [`scripts/keil_uvsc.py`](../scripts/keil_uvsc.py). Keep the DLL bitness aligned with the Python process and use the 64-bit DLL when available. The bridge intentionally keeps the API surface small so that Codex can inspect a live target without depending on GUI scraping or proprietary third-party packages.
