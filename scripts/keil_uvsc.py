#!/usr/bin/env python3
"""Small JSON CLI for Keil uVision's native UVSC/UVSOCK interface.

ABI declarations follow Keil UVSC 2.29 and the Qt Creator UVSC plugin:
https://github.com/qt-creator/qt-creator/tree/master/src/plugins/debugger/uvsc
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


UVSC_SUCCESS = 0
UVSC_COMMAND_ERROR = 9
UV_STATUS = {
    0: "success",
    1: "failed",
    2: "no_project",
    6: "not_debugging",
    10: "debugging",
    11: "target_executing",
    12: "target_stopped",
    29: "timeout",
    34: "no_memory_access",
    37: "hardware",
    38: "simulator",
}


CALLBACK = C.CFUNCTYPE(None, C.c_void_p, C.c_int32, C.c_void_p)


@CALLBACK
def _callback(_custom, _kind, _data):
    return


class SSTR(C.Structure):
    _pack_ = 1
    _fields_ = [("length", C.c_int32), ("data", C.c_char * 256)]


class EXECCMD(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", C.c_uint32),
        ("reserved", C.c_uint32 * 7),
        ("command", SSTR),
    ]


class IPATHREQ(C.Structure):
    _pack_ = 1
    _fields_ = [("flags", C.c_uint32), ("reserved", C.c_uint32 * 7)]


class UVSOCK_OPTIONS(C.Structure):
    _pack_ = 1
    _fields_ = [("flags", C.c_uint32)]


class REGENUM(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("group_index", C.c_uint16),
        ("item", C.c_uint16),
        ("name", C.c_char * 16),
        ("flags", C.c_uint8),
        ("value", C.c_char * 32),
    ]


class ISTKENUM(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", C.c_uint32),
        ("task", C.c_uint32),
        ("reserved", C.c_uint32 * 6),
    ]


class STACKENUM(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("number", C.c_uint32),
        ("current_address", C.c_uint64),
        ("return_address", C.c_uint64),
        ("variables_count", C.c_uint32),
        ("equal_frames_count", C.c_uint32),
        ("total_frames_count", C.c_uint32),
        ("task", C.c_uint32),
        ("reserved", C.c_uint32 * 3),
    ]


class ADRMTFL(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", C.c_uint32),
        ("address", C.c_uint64),
        ("reserved", C.c_uint32 * 7),
    ]


class AFLMAP_HEAD(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("line", C.c_uint32),
        ("address", C.c_uint64),
        ("file_index", C.c_uint32),
        ("function_index", C.c_uint32),
        ("reserved", C.c_int32 * 5),
    ]


class AMEM_HEAD(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("address", C.c_uint64),
        ("count", C.c_uint32),
        ("error_address", C.c_uint64),
        ("error_code", C.c_uint32),
    ]


assert C.sizeof(SSTR) == 260
assert C.sizeof(EXECCMD) == 292
assert C.sizeof(REGENUM) == 53
assert C.sizeof(ISTKENUM) == 32
assert C.sizeof(STACKENUM) == 48
assert C.sizeof(ADRMTFL) == 40
assert C.sizeof(AFLMAP_HEAD) == 40
assert C.sizeof(AMEM_HEAD) == 24


def _decode(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("mbcs", errors="replace")


def _sstr(value: str) -> SSTR:
    raw = value.encode("mbcs")
    if len(raw) > 255:
        raise ValueError("UVSC strings are limited to 255 bytes")
    out = SSTR()
    out.length = len(raw)
    C.memmove(C.addressof(out) + SSTR.data.offset, raw, len(raw))
    return out


class UvscError(RuntimeError):
    def __init__(self, api_status: int, detail: dict):
        super().__init__(detail.get("message") or f"UVSC status {api_status}")
        self.api_status = api_status
        self.detail = detail


class Uvsc:
    def __init__(self, port: int, uv4_dir: Path):
        self.port = port
        self.uv4_dir = uv4_dir
        dll_path = uv4_dir / ("UVSC64.dll" if C.sizeof(C.c_void_p) == 8 else "UVSC.dll")
        if not dll_path.is_file():
            raise FileNotFoundError(dll_path)
        self.dll = C.CDLL(str(dll_path))
        self.handle = C.c_int32(-1)
        self._bind()

    def _bind(self):
        d = self.dll
        d.UVSC_Version.argtypes = [C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]
        d.UVSC_Version.restype = None
        d.UVSC_Init.argtypes = [C.c_int32, C.c_int32]
        d.UVSC_Init.restype = C.c_int32
        d.UVSC_UnInit.argtypes = []
        d.UVSC_UnInit.restype = C.c_int32
        d.UVSC_OpenConnection.argtypes = [
            C.c_char_p,
            C.POINTER(C.c_int32),
            C.POINTER(C.c_int32),
            C.c_char_p,
            C.c_int32,
            CALLBACK,
            C.c_void_p,
            C.c_char_p,
            C.c_uint8,
            C.c_void_p,
        ]
        d.UVSC_OpenConnection.restype = C.c_int32
        d.UVSC_CloseConnection.argtypes = [C.c_int32, C.c_uint8]
        d.UVSC_CloseConnection.restype = C.c_int32
        d.UVSC_GetLastError.argtypes = [
            C.c_int32,
            C.POINTER(C.c_int32),
            C.POINTER(C.c_int32),
            C.c_void_p,
            C.c_int32,
        ]
        d.UVSC_GetLastError.restype = C.c_int32
        d.UVSC_GEN_SET_OPTIONS.argtypes = [C.c_int32, C.POINTER(UVSOCK_OPTIONS)]
        d.UVSC_GEN_SET_OPTIONS.restype = C.c_int32
        d.UVSC_GEN_UVSOCK_VERSION.argtypes = [
            C.c_int32,
            C.POINTER(C.c_int32),
            C.POINTER(C.c_int32),
        ]
        d.UVSC_GEN_UVSOCK_VERSION.restype = C.c_int32
        for name in ("UVSC_PRJ_GET_CUR_TARGET", "UVSC_PRJ_GET_OUTPUTNAME"):
            fn = getattr(d, name)
            fn.argtypes = [C.c_int32, C.POINTER(IPATHREQ), C.POINTER(SSTR), C.c_int32]
            fn.restype = C.c_int32
        d.UVSC_DBG_STATUS.argtypes = [C.c_int32, C.POINTER(C.c_int32)]
        d.UVSC_DBG_STATUS.restype = C.c_int32
        for name in (
            "UVSC_DBG_ENTER",
            "UVSC_DBG_EXIT",
            "UVSC_DBG_START_EXECUTION",
            "UVSC_DBG_STOP_EXECUTION",
            "UVSC_DBG_RESET",
            "UVSC_DBG_STEP_HLL",
            "UVSC_DBG_STEP_INTO",
            "UVSC_DBG_STEP_INSTRUCTION",
            "UVSC_DBG_STEP_OUT",
        ):
            fn = getattr(d, name)
            fn.argtypes = [C.c_int32]
            fn.restype = C.c_int32
        d.UVSC_DBG_EXEC_CMD.argtypes = [C.c_int32, C.POINTER(EXECCMD), C.c_int32]
        d.UVSC_DBG_EXEC_CMD.restype = C.c_int32
        d.UVSC_GetCmdOutputSize.argtypes = [C.c_int32, C.POINTER(C.c_int32)]
        d.UVSC_GetCmdOutputSize.restype = C.c_int32
        d.UVSC_GetCmdOutput.argtypes = [C.c_int32, C.c_void_p, C.c_int32]
        d.UVSC_GetCmdOutput.restype = C.c_int32
        d.UVSC_DBG_ENUM_REGISTER_GROUPS.argtypes = [
            C.c_int32,
            C.POINTER(SSTR),
            C.POINTER(C.c_int32),
        ]
        d.UVSC_DBG_ENUM_REGISTER_GROUPS.restype = C.c_int32
        d.UVSC_DBG_ENUM_REGISTERS.argtypes = [
            C.c_int32,
            C.POINTER(REGENUM),
            C.POINTER(C.c_int32),
        ]
        d.UVSC_DBG_ENUM_REGISTERS.restype = C.c_int32
        d.UVSC_DBG_READ_REGISTERS.argtypes = [C.c_int32, C.c_void_p, C.POINTER(C.c_int32)]
        d.UVSC_DBG_READ_REGISTERS.restype = C.c_int32
        d.UVSC_DBG_ENUM_STACK.argtypes = [
            C.c_int32,
            C.POINTER(ISTKENUM),
            C.POINTER(STACKENUM),
            C.POINTER(C.c_int32),
        ]
        d.UVSC_DBG_ENUM_STACK.restype = C.c_int32
        d.UVSC_DBG_ADR_TOFILELINE.argtypes = [
            C.c_int32,
            C.POINTER(ADRMTFL),
            C.c_void_p,
            C.POINTER(C.c_int32),
        ]
        d.UVSC_DBG_ADR_TOFILELINE.restype = C.c_int32
        d.UVSC_DBG_MEM_READ.argtypes = [C.c_int32, C.c_void_p, C.c_int32]
        d.UVSC_DBG_MEM_READ.restype = C.c_int32

    def __enter__(self):
        status = self.dll.UVSC_Init(self.port, self.port + 1)
        if status != UVSC_SUCCESS:
            raise UvscError(status, {"message": "UVSC_Init failed"})
        server_port = C.c_int32(self.port)
        status = self.dll.UVSC_OpenConnection(
            None,
            C.byref(self.handle),
            C.byref(server_port),
            None,
            0,
            _callback,
            None,
            None,
            0,
            None,
        )
        if status != UVSC_SUCCESS:
            self.dll.UVSC_UnInit()
            raise UvscError(status, {"message": f"Cannot connect to UVSOCK port {self.port}"})
        options = UVSOCK_OPTIONS(1)
        self._check(self.dll.UVSC_GEN_SET_OPTIONS(self.handle.value, C.byref(options)))
        return self

    def __exit__(self, _type, _value, _traceback):
        if self.handle.value >= 0:
            self.dll.UVSC_CloseConnection(self.handle.value, 0)
        self.dll.UVSC_UnInit()

    def last_error(self) -> dict:
        operation = C.c_int32()
        target_status = C.c_int32()
        message = C.create_string_buffer(2048)
        self.dll.UVSC_GetLastError(
            self.handle.value,
            C.byref(operation),
            C.byref(target_status),
            message,
            len(message),
        )
        return {
            "operation": operation.value,
            "target_status": target_status.value,
            "target_status_name": UV_STATUS.get(target_status.value, "unknown"),
            "message": _decode(message.raw).strip(),
        }

    def _check(self, status: int):
        if status != UVSC_SUCCESS:
            raise UvscError(status, self.last_error())

    def version(self) -> dict:
        client = C.c_uint32()
        protocol = C.c_uint32()
        self.dll.UVSC_Version(C.byref(client), C.byref(protocol))
        major = C.c_int32()
        minor = C.c_int32()
        self._check(
            self.dll.UVSC_GEN_UVSOCK_VERSION(
                self.handle.value, C.byref(major), C.byref(minor)
            )
        )
        return {
            "client": client.value,
            "protocol": protocol.value,
            "server": f"{major.value}.{minor.value:02d}",
        }

    def _project_string(self, api_name: str) -> str:
        request = IPATHREQ(1)
        value = SSTR()
        self._check(
            getattr(self.dll, api_name)(
                self.handle.value, C.byref(request), C.byref(value), C.sizeof(value)
            )
        )
        return _decode(bytes(value.data[: value.length]))

    def status(self) -> dict:
        result = {
            "port": self.port,
            "version": self.version(),
            "target": self._project_string("UVSC_PRJ_GET_CUR_TARGET"),
            "application": self._project_string("UVSC_PRJ_GET_OUTPUTNAME"),
        }
        target_status = C.c_int32(-1)
        call_status = self.dll.UVSC_DBG_STATUS(self.handle.value, C.byref(target_status))
        if call_status == UVSC_SUCCESS:
            result["debug"] = {
                "api_status": call_status,
                "target_status": target_status.value,
                "state": UV_STATUS.get(target_status.value, "unknown"),
            }
        else:
            detail = self.last_error()
            result["debug"] = {
                "api_status": call_status,
                "target_status": detail["target_status"],
                "state": detail["target_status_name"],
                "message": detail["message"],
            }
        return result

    def control(self, operation: str) -> dict:
        api = {
            "enter": "UVSC_DBG_ENTER",
            "exit": "UVSC_DBG_EXIT",
            "run": "UVSC_DBG_START_EXECUTION",
            "halt": "UVSC_DBG_STOP_EXECUTION",
            "reset": "UVSC_DBG_RESET",
            "step": "UVSC_DBG_STEP_HLL",
            "step-into": "UVSC_DBG_STEP_INTO",
            "step-instruction": "UVSC_DBG_STEP_INSTRUCTION",
            "step-out": "UVSC_DBG_STEP_OUT",
        }[operation]
        self._check(getattr(self.dll, api)(self.handle.value))
        return {"operation": operation, "ok": True}

    def command(self, command: str) -> dict:
        request = EXECCMD()
        request.command = _sstr(command)
        self._check(
            self.dll.UVSC_DBG_EXEC_CMD(
                self.handle.value, C.byref(request), C.sizeof(SSTR)
            )
        )
        output_size = C.c_int32()
        for _ in range(30):
            self._check(
                self.dll.UVSC_GetCmdOutputSize(self.handle.value, C.byref(output_size))
            )
            if output_size.value > 1:
                break
            time.sleep(0.1)
        output = C.create_string_buffer(max(1, output_size.value))
        self._check(
            self.dll.UVSC_GetCmdOutput(self.handle.value, output, len(output))
        )
        return {"command": command, "output": _decode(output.raw).strip()}

    def registers(self) -> list[dict]:
        groups = (SSTR * 128)()
        group_count = C.c_int32(len(groups))
        self._check(
            self.dll.UVSC_DBG_ENUM_REGISTER_GROUPS(
                self.handle.value, groups, C.byref(group_count)
            )
        )
        group_names = [_decode(bytes(groups[i].data[: groups[i].length])) for i in range(group_count.value)]

        metadata = (REGENUM * 512)()
        register_count = C.c_int32(len(metadata))
        self._check(
            self.dll.UVSC_DBG_ENUM_REGISTERS(
                self.handle.value, metadata, C.byref(register_count)
            )
        )
        values = C.create_string_buffer(register_count.value * 32)
        values_length = C.c_int32(len(values))
        self._check(
            self.dll.UVSC_DBG_READ_REGISTERS(
                self.handle.value, values, C.byref(values_length)
            )
        )
        raw_values = values.raw[: values_length.value]
        result = []
        for index in range(register_count.value):
            reg = metadata[index]
            name = _decode(bytes(reg.name))
            if not name:
                continue
            value = _decode(raw_values[index * 32 : (index + 1) * 32])
            group = group_names[reg.group_index] if reg.group_index < len(group_names) else ""
            result.append(
                {
                    "index": index,
                    "name": name,
                    "value": value,
                    "group": group,
                    "item": reg.item,
                    "is_pc": bool(reg.flags & 1),
                    "editable": bool(reg.flags & 2),
                }
            )
        return result

    def _address_info(self, address: int) -> dict:
        request = ADRMTFL(1, address)
        size = C.c_int32(65536)
        buffer = C.create_string_buffer(size.value)
        status = self.dll.UVSC_DBG_ADR_TOFILELINE(
            self.handle.value, C.byref(request), buffer, C.byref(size)
        )
        if status != UVSC_SUCCESS:
            return {}
        head = AFLMAP_HEAD.from_buffer(buffer)
        strings = buffer.raw[C.sizeof(AFLMAP_HEAD) : size.value]
        return {
            "file": _decode(strings[head.file_index :]),
            "function": _decode(strings[head.function_index :]),
            "line": head.line,
        }

    def stack(self, task: int = 0) -> list[dict]:
        request = ISTKENUM(3, task)
        frames = (STACKENUM * 512)()
        count = C.c_int32(len(frames))
        self._check(
            self.dll.UVSC_DBG_ENUM_STACK(
                self.handle.value, C.byref(request), frames, C.byref(count)
            )
        )
        result = []
        for frame in reversed(frames[: count.value]):
            item = {
                "level": frame.number,
                "address": f"0x{frame.current_address:08X}",
                "return_address": f"0x{frame.return_address:08X}",
                "variables": frame.variables_count,
                "task": frame.task,
            }
            item.update(self._address_info(frame.current_address))
            result.append(item)
        return result

    def memory(self, address: int, count: int) -> dict:
        if not 1 <= count <= 32762:
            raise ValueError("count must be between 1 and 32762")
        buffer = C.create_string_buffer(C.sizeof(AMEM_HEAD) + count)
        head = AMEM_HEAD.from_buffer(buffer)
        head.address = address
        head.count = count
        self._check(
            self.dll.UVSC_DBG_MEM_READ(self.handle.value, buffer, len(buffer))
        )
        data = buffer.raw[C.sizeof(AMEM_HEAD) : C.sizeof(AMEM_HEAD) + head.count]
        return {
            "address": f"0x{address:X}",
            "count": head.count,
            "hex": data.hex(" "),
            "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in data),
            "error_address": f"0x{head.error_address:X}",
            "error_code": head.error_code,
        }


def launch_uv4(uv4: Path, project: Path, port: int, show: bool) -> dict:
    if not uv4.is_file():
        raise FileNotFoundError(uv4)
    if not project.is_file():
        raise FileNotFoundError(project)
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            return {"port": port, "already_listening": True}
    startup = None
    if os.name == "nt" and not show:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    process = subprocess.Popen(
        [str(uv4), str(project), "-s", str(port), "-sg"],
        cwd=str(project.parent),
        startupinfo=startup,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"uVision exited with code {process.returncode}")
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return {"pid": process.pid, "port": port, "project": str(project)}
        time.sleep(0.25)
    raise TimeoutError(f"uVision did not open UVSOCK port {port}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Control Keil uVision through UVSC/UVSOCK")
    p.add_argument("--uv4-dir", default=r"E:\KEIL5\UV4")
    p.add_argument("--port", type=int, default=4328)
    sub = p.add_subparsers(dest="action", required=True)
    launch = sub.add_parser("launch", help="Open a dedicated uVision UVSOCK instance")
    launch.add_argument("--project", required=True)
    launch.add_argument("--show", action="store_true")
    sub.add_parser("status")
    sub.add_parser("serve", help="Keep one UVSC connection open and accept JSON lines on stdin")
    for name in (
        "enter",
        "exit",
        "run",
        "halt",
        "reset",
        "step",
        "step-into",
        "step-instruction",
        "step-out",
        "registers",
        "stack",
        "breakpoints",
    ):
        sub.add_parser(name)
    command = sub.add_parser("command")
    command.add_argument("text")
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("expression")
    memory = sub.add_parser("memory")
    memory.add_argument("address")
    memory.add_argument("count", type=int)
    return p


def dispatch(uvsc: Uvsc, action: str, payload: dict | None = None):
    payload = payload or {}
    if action == "status":
        return uvsc.status()
    if action in {
        "enter",
        "exit",
        "run",
        "halt",
        "reset",
        "step",
        "step-into",
        "step-instruction",
        "step-out",
    }:
        return uvsc.control(action)
    if action == "command":
        return uvsc.command(payload["text"])
    if action == "eval":
        return uvsc.command(f"EVAL {payload['expression']}")
    if action == "registers":
        return {"registers": uvsc.registers()}
    if action == "stack":
        return {"stack": uvsc.stack(int(payload.get("task", 0)))}
    if action == "memory":
        address = payload["address"]
        if isinstance(address, str):
            address = int(address, 0)
        return uvsc.memory(address, int(payload["count"]))
    if action == "breakpoints":
        return uvsc.command("BL")
    raise ValueError(f"Unknown action: {action}")


def serve(uvsc: Uvsc) -> int:
    print(json.dumps({"ok": True, "ready": uvsc.status()}, ensure_ascii=False), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            action = request.get("action")
            if action == "quit":
                print(json.dumps({"ok": True, "result": "bye"}), flush=True)
                return 0
            result = dispatch(uvsc, action, request)
            response = {"ok": True, "result": result}
        except UvscError as exc:
            response = {"ok": False, "api_status": exc.api_status, "error": exc.detail}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    args = parser().parse_args()
    try:
        uv4_dir = Path(args.uv4_dir)
        if args.action == "launch":
            result = launch_uv4(uv4_dir / "UV4.exe", Path(args.project), args.port, args.show)
        else:
            with Uvsc(args.port, uv4_dir) as uvsc:
                if args.action == "serve":
                    return serve(uvsc)
                payload = vars(args)
                result = dispatch(uvsc, args.action, payload)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
        return 0
    except UvscError as exc:
        print(
            json.dumps(
                {"ok": False, "api_status": exc.api_status, "error": exc.detail},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
