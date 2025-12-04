#!/usr/bin/env python3
"""CLI for managing the open-claude-router server."""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

PID_FILE = Path('.router.pid')
LOG_FILE = Path('.router.log')


def get_pid() -> int | None:
    """Get the running server PID if any."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    return None


def start_server(detached: bool = False) -> None:
    """Start the router server."""
    if get_pid():
        print('Server is already running')
        return

    if detached:
        with Path(LOG_FILE).open('w') as log:
            proc = subprocess.Popen(
                [sys.executable, '-m', 'src.main'],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        PID_FILE.write_text(str(proc.pid))
        print(f'Server started in background (PID: {proc.pid})')
        print(f'Logs: {LOG_FILE}')
    else:
        try:
            subprocess.run([sys.executable, '-m', 'src.main'], check=False)
        except KeyboardInterrupt:
            print('\nServer stopped')


def stop_server() -> None:
    """Stop the running server."""
    pid = get_pid()
    if not pid:
        print('Server is not running')
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f'Server stopped (PID: {pid})')
    except ProcessLookupError:
        print('Server process not found')
    finally:
        PID_FILE.unlink(missing_ok=True)


def status() -> None:
    """Show server status."""
    pid = get_pid()
    if pid:
        print(f'Server is running (PID: {pid})')
    else:
        print('Server is not running')


def logs(follow: bool = False, lines: int = 50) -> None:
    """Show server logs."""
    if not LOG_FILE.exists():
        print('No log file found')
        return

    if follow:
        subprocess.run(['tail', '-f', str(LOG_FILE)], check=False)
    else:
        subprocess.run(['tail', '-n', str(lines), str(LOG_FILE)], check=False)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Manage the open-claude-router server',
        prog='router',
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    start_parser = subparsers.add_parser('start', help='Start the server')
    start_parser.add_argument(
        '-d', '--detached',
        action='store_true',
        help='Run in background',
    )

    subparsers.add_parser('stop', help='Stop the server')
    subparsers.add_parser('status', help='Show server status')

    logs_parser = subparsers.add_parser('logs', help='Show server logs')
    logs_parser.add_argument(
        '-f', '--follow',
        action='store_true',
        help='Follow log output',
    )
    logs_parser.add_argument(
        '-n', '--lines',
        type=int,
        default=50,
        help='Number of lines to show',
    )

    args = parser.parse_args()

    if args.command == 'start':
        start_server(detached=args.detached)
    elif args.command == 'stop':
        stop_server()
    elif args.command == 'status':
        status()
    elif args.command == 'logs':
        logs(follow=args.follow, lines=args.lines)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
