#!/usr/bin/env python3
# @summary
# TCP proxy to expose host-local Ollama (127.0.0.1:11434) to Docker containers.
# Exports: main
# Deps: argparse, asyncio
# @end-summary

from __future__ import annotations

import argparse
import asyncio


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
) -> None:
    try:
        target_reader, target_writer = await asyncio.open_connection(target_host, target_port)
    except Exception:
        client_writer.close()
        await client_writer.wait_closed()
        return

    await asyncio.gather(
        _pipe(client_reader, target_writer),
        _pipe(target_reader, client_writer),
        return_exceptions=True,
    )


async def _run(listen_host: str, listen_port: int, target_host: str, target_port: int) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, target_host, target_port),
        host=listen_host,
        port=listen_port,
    )
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"ollama-proxy listening={sockets} target={target_host}:{target_port}")
    async with server:
        await server.serve_forever()


def main() -> int:
    import os

    parser = argparse.ArgumentParser(
        description="Expose localhost Ollama to Docker via host-gateway reachable port."
    )
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument(
        "--listen-port",
        type=int,
        default=int(os.environ.get("RAG_OLLAMA_PROXY_PORT", "11435")),
    )
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument(
        "--target-port",
        type=int,
        default=int(os.environ.get("RAG_OLLAMA_PORT", "11434")),
    )
    args = parser.parse_args()
    try:
        asyncio.run(
            _run(
                listen_host=args.listen_host,
                listen_port=args.listen_port,
                target_host=args.target_host,
                target_port=args.target_port,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
