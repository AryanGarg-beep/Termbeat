#!/usr/bin/env python3
"""termbeat whole-system benchmark: real RSS, CPU and pty byte rate for
radio.py + mpv + cava, playing and paused.

Runs the real app in a pty (muted immediately, so nothing comes out of the
speakers). Usage: python3 bench/benchmark_system.py [cols] [rows] [seconds]
"""
import fcntl
import os
import pty
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def proc_stat(pid):
    """-> (rss_bytes, cpu_seconds, threads) or None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            raw = f.read()
        rparen = raw.rindex(")")
        fields = raw[rparen + 2:].split()
        utime, stime = int(fields[11]), int(fields[12])
        threads = int(fields[17])
        with open(f"/proc/{pid}/statm") as f:
            rss_pages = int(f.read().split()[1])
        return rss_pages * PAGE, (utime + stime) / CLK, threads
    except (OSError, ValueError, IndexError):
        return None


def descendants(pid):
    out = {}
    try:
        for line in subprocess.run(
            ["ps", "-eo", "pid=,ppid=,comm="], capture_output=True, text=True
        ).stdout.splitlines():
            p, pp, c = line.split(None, 2)
            out.setdefault(int(pp), []).append((int(p), c.strip()))
    except Exception:
        return []
    found, stack = [], [pid]
    while stack:
        for p, c in out.get(stack.pop(), []):
            found.append((p, c))
            stack.append(p)
    return found


def main():
    cols = int(sys.argv[1]) if len(sys.argv) > 1 else 101
    rows = int(sys.argv[2]) if len(sys.argv) > 2 else 54
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 25.0

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    env = dict(os.environ, TERM="xterm-256color", COLUMNS=str(cols), LINES=str(rows))
    proc = subprocess.Popen(
        [sys.executable, "-u", os.path.join(HERE, "radio.py")],
        stdin=slave, stdout=slave, stderr=slave,
        cwd=HERE, env=env, start_new_session=True,
    )
    os.close(slave)

    counter = {"n": 0}
    stop = threading.Event()

    def drain():
        while not stop.is_set():
            try:
                b = os.read(master, 65536)
            except OSError:
                break
            if not b:
                break
            counter["n"] += len(b)

    t = threading.Thread(target=drain, daemon=True)
    t.start()

    try:
        time.sleep(3.0)                      # let mpv connect + stream start
        os.write(master, b"m")               # mute: no audio out of the speakers
        time.sleep(4.0)                      # settle

        def sample(label, seconds):
            kids = descendants(proc.pid)
            pids = {"radio.py": proc.pid}
            for p, c in kids:
                if "mpv" in c:
                    pids["mpv"] = p
                elif "cava" in c:
                    pids["cava"] = p
            t0 = {k: proc_stat(v) for k, v in pids.items()}
            b0, w0 = counter["n"], time.monotonic()
            time.sleep(seconds)
            t1 = {k: proc_stat(v) for k, v in pids.items()}
            b1, w1 = counter["n"], time.monotonic()
            wall = w1 - w0

            print(f"\n--- {label}  ({cols}x{rows}, {wall:.1f}s) ---")
            print(f"{'process':<12} {'RSS':>10} {'CPU %core':>10} {'threads':>8}")
            tot_rss = tot_cpu = 0
            for k in ("radio.py", "mpv", "cava"):
                if k not in pids or not t0.get(k) or not t1.get(k):
                    print(f"{k:<12} {'not running':>10}")
                    continue
                rss, c1, th = t1[k]
                cpu = (c1 - t0[k][1]) / wall * 100
                tot_rss += rss
                tot_cpu += cpu
                print(f"{k:<12} {rss/1048576:>9.1f}M {cpu:>9.1f}% {th:>8}")
            print(f"{'TOTAL':<12} {tot_rss/1048576:>9.1f}M {tot_cpu:>9.1f}%")
            print(f"pty stdout   {(b1-b0)/wall/1024:>9.1f} KB/s   "
                  f"({(b1-b0)/wall*3600/1048576:.0f} MB/hour of ANSI)")
            return tot_rss, tot_cpu, (b1 - b0) / wall

        play = sample("PLAYING (muted)", dur)
        os.write(master, b" ")               # space = pause
        time.sleep(2.0)
        paused = sample("PAUSED", dur * 0.6)

        print(f"\n--- deltas ---")
        print(f"CPU  playing {play[1]:.1f}%  ->  paused {paused[1]:.1f}%   "
              f"(fixed 22 FPS means paused still costs {paused[1]/max(play[1],.01)*100:.0f}% "
              f"of playing CPU)")
        print(f"pty  playing {play[2]/1024:.1f} KB/s  ->  paused {paused[2]/1024:.1f} KB/s")
    finally:
        stop.set()
        try:
            os.write(master, b"q")
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        try:
            os.close(master)
        except OSError:
            pass
        leftover = [f for f in os.listdir("/tmp") if f.startswith("termbeat_")]
        print(f"\nexit code: {proc.returncode}   "
              f"/tmp leftovers: {leftover if leftover else 'none (clean)'}")


if __name__ == "__main__":
    main()
