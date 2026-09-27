from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone

from ..config import Settings
from .buffer import FleetBuffer
from .parser import NDTPParser
from .recorder import Recorder


class StreamPipeline:
    def __init__(self, parser: NDTPParser, recorder: Recorder | None = None, buffer: FleetBuffer | None = None):
        self.parser = parser
        self.recorder = recorder
        self.buffer = buffer or FleetBuffer()
        self.received = 0
        self.parsed = 0

    def sink(self, payload: bytes) -> None:
        self.received += 1
        records = self.parser.parse(payload)
        self.parsed += len(records)
        if self.recorder:
            for rec in records:
                self.recorder.add(rec)
            self.recorder.flush_if_needed()
        self.buffer.extend(records)

    def stats(self) -> dict:
        return {
            "packets": self.received,
            "records": self.parsed,
            "vehicles": len(self.buffer.vehicles()),
            "files_written": self.recorder.files_written if self.recorder else 0,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
        }


async def run_udp(pipeline: StreamPipeline, host: str, port: int) -> None:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _UdpProtocol(pipeline), local_addr=(host, port)
    )
    print(f"[ingest] udp listening on {host}:{port}")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        transport.close()


async def run_tcp(pipeline: StreamPipeline, host: str, port: int) -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            payload = await reader.read(65536)
            if not payload:
                break
            pipeline.sink(payload)

    server = await asyncio.start_server(handle, host, port)
    print(f"[ingest] tcp listening on {host}:{port}")
    async with server:
        await server.serve_forever()


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, pipeline: StreamPipeline):
        self.pipeline = pipeline

    def datagram_received(self, data: bytes, _addr) -> None:
        self.pipeline.sink(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default=None)
    ap.add_argument("--transport", choices=["udp", "tcp"], default=None)
    args = ap.parse_args()

    settings = Settings.load(args.settings)
    cfg = settings.ingest
    parser = NDTPParser("config/ndtp_fields.yaml")
    recorder = Recorder(cfg["record_dir"])
    pipeline = StreamPipeline(parser, recorder)
    runner = run_udp if (args.transport or cfg.get("transport", "udp")) == "udp" else run_tcp

    async def _stats():
        while True:
            await asyncio.sleep(10)
            print(f"[ingest] {pipeline.stats()}")

    async def _root():
        await asyncio.gather(runner(pipeline, cfg["listen_host"], int(cfg["listen_port"])), _stats())

    asyncio.run(_root())


if __name__ == "__main__":
    main()
