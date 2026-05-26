import glob
import re
import time
from dataclasses import dataclass


POLICY_HASH_RE = re.compile(r"<policy\.approved=buffer:([0-9a-fA-F]{64}) \(32 bytes\)")
PAYMENT_APPROVED_RE = re.compile(r"<payment\.approved=buffer:([0-9a-fA-F]{64}) \(32 bytes\)")
PAYMENT_REJECTED_RE = re.compile(r"<payment\.(?:rejected|timeout)=buffer:([0-9a-fA-F]{64}) \(32 bytes\)")
MODEL_RE = re.compile(r"<device\.model=number:(\d+)")
SERIAL_RE = re.compile(r"<device\.serial=number:(\d+)")


def find_firefly_port() -> str:
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        raise RuntimeError("No Firefly serial port found. Expected /dev/cu.usbmodem*.")
    if len(ports) > 1:
        joined = ", ".join(ports)
        raise RuntimeError(f"Multiple USB modem ports found: {joined}. Set FIREFLY_PORT.")
    return ports[0]


def parse_policy_approval(raw: str) -> dict[str, object]:
    if "<OK" not in raw:
        raise ValueError(f"Firefly response did not contain <OK. Raw response: {raw!r}")

    hash_match = POLICY_HASH_RE.search(raw)
    model_match = MODEL_RE.search(raw)
    serial_match = SERIAL_RE.search(raw)

    if not hash_match:
        raise ValueError("Firefly response did not contain policy.approved.")
    if not model_match:
        raise ValueError("Firefly response did not contain device.model.")
    if not serial_match:
        raise ValueError("Firefly response did not contain device.serial.")

    return {
        "approved": True,
        "approvedHash": hash_match.group(1).lower(),
        "deviceModel": int(model_match.group(1)),
        "deviceSerial": int(serial_match.group(1)),
        "raw": raw,
    }


def parse_payment_approval(raw: str) -> dict[str, object]:
    approved_match = PAYMENT_APPROVED_RE.search(raw)
    rejected_match = PAYMENT_REJECTED_RE.search(raw)

    if approved_match and "<OK" in raw:
        model_match = MODEL_RE.search(raw)
        serial_match = SERIAL_RE.search(raw)
        if not model_match:
            raise ValueError("Firefly response did not contain device.model.")
        if not serial_match:
            raise ValueError("Firefly response did not contain device.serial.")

        return {
            "approved": True,
            "approvedHash": approved_match.group(1).lower(),
            "deviceModel": int(model_match.group(1)),
            "deviceSerial": int(serial_match.group(1)),
            "raw": raw,
        }

    if rejected_match and "<ERROR" in raw:
        error = "PAYMENT rejected by user"
        for line in raw.splitlines():
            if line.startswith("! "):
                error = line[2:]
                break
        return {
            "approved": False,
            "approvedHash": rejected_match.group(1).lower(),
            "error": error,
            "raw": raw,
        }

    raise ValueError(f"Firefly response did not contain payment approval. Raw response: {raw!r}")


@dataclass
class FireflyClient:
    port: str
    baudrate: int = 115200
    timeout: float = 0.2
    settle_seconds: float = 2.0
    read_seconds: float = 5.0
    payment_read_seconds: float = 35.0

    def approve_policy_hash(self, policy_hash: str) -> dict[str, object]:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", policy_hash):
            raise ValueError("policy_hash must be 64 hex characters.")

        raw = self._send_command(f"POLICY={policy_hash.lower()}", self.read_seconds)
        return parse_policy_approval(raw)

    def approve_payment_hash(self, payment_hash: str) -> dict[str, object]:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", payment_hash):
            raise ValueError("payment_hash must be 64 hex characters.")

        raw = self._send_command(f"PAYMENT={payment_hash.lower()}", self.payment_read_seconds)
        return parse_payment_approval(raw)

    def _send_command(self, command: str, read_seconds: float) -> str:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required. Install it with: python3 -m pip install pyserial") from exc

        with serial.Serial(
            self.port,
            self.baudrate,
            timeout=self.timeout,
            write_timeout=2,
        ) as serial_port:
            boot_raw = self._read_until_ready(serial_port, self.settle_seconds)
            serial_port.write(f"{command}\n".encode("ascii"))
            time.sleep(0.1)
            raw = self._read_until_ok(serial_port, read_seconds)

        if not raw:
            raw = f"[boot/readiness before command: {boot_raw!r}]"

        return raw

    def _read_for(self, serial_port, seconds: float) -> str:
        end = time.time() + seconds
        chunks: list[bytes] = []
        while time.time() < end:
            chunk = serial_port.read(4096)
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks).decode("latin1", "replace")

    def _read_until_ok(self, serial_port, seconds: float) -> str:
        end = time.time() + seconds
        chunks: list[bytes] = []
        while time.time() < end:
            chunk = serial_port.read(4096)
            if chunk:
                chunks.append(chunk)
                raw = b"".join(chunks).decode("latin1", "replace")
                if "<OK" in raw or "<ERROR" in raw:
                    return raw
        return b"".join(chunks).decode("latin1", "replace")

    def _read_until_ready(self, serial_port, seconds: float) -> str:
        end = time.time() + seconds
        chunks: list[bytes] = []
        while time.time() < end:
            chunk = serial_port.read(4096)
            if chunk:
                chunks.append(chunk)
                raw = b"".join(chunks).decode("latin1", "replace")
                if "<READY" in raw:
                    return raw
        return b"".join(chunks).decode("latin1", "replace")
