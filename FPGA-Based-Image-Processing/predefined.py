
# coding: utf-8

# In[ ]:


import time
import queue
import threading
import socket
import subprocess
import collections
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import numpy as np
import cv2
from PIL import Image
import matplotlib.pyplot as plt
import ipywidgets as widgets
from IPython.display import display
from pynq import Overlay, allocate


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ======================================================================
#  SETTINGS
# ======================================================================
TARGET_FPS = 200.0                # target output fps
LOOP = False                      # True = play the file again and again
REMOVE_TITLE = True               # remove the "SOBEL TEST" heading (files only)
TITLE_X0, TITLE_X1 = 78, 162      # heading area on the 256 x 256 frame
TITLE_Y0, TITLE_Y1 = 23, 40

CAM_W, CAM_H = 640, 480           # USB camera size
CAM_FPS = 30                      # USB camera speed (a camera cannot give more)
CAMERA_FLIP = "rotate180"         # fixes an inverted camera picture:
                                  #   "none" | "updown" | "leftright" | "rotate180"
_FLIP_CODES = {"updown": 0, "leftright": 1, "rotate180": -1}
LIVE_VIDEO = "live_video"         # input_video("live_video") = USB camera

RESIZE_INTERP = cv2.INTER_LINEAR  # OpenCV reader only
FAST_DECODE = False               # True = decoder skips B-frames (much less CPU work);
                                  #        output stays at TARGET_FPS, some frames are repeated

WEB_PORT = 8000
WEB_JPEG_QUALITY = 80
NOTEBOOK_PREVIEW = True           # side-by-side picture in the notebook
PREVIEW_FPS = 5                   # (own thread, never slows the output clock)

cv2.setNumThreads(2)

# ======================================================================
#  HARDWARE
# ======================================================================
overlay = Overlay("Image_processing_system_test.bit")

dma_input = overlay.axi_dma_4
dma_sobel = overlay.axi_dma_1
dma_laplacian = overlay.axi_dma_2
dma_canny = overlay.axi_dma_3
gpio = overlay.axi_gpio_0

WIDTH = 256
HEIGHT = 256
SIZE = WIDTH * HEIGHT

input_buffer = allocate(shape=(SIZE,), dtype=np.uint8)
output_buffer = allocate(shape=(SIZE,), dtype=np.uint8)

gpio.write(0x00, 0x00)

FILTERS = {
    "gaussian":  (0x01, dma_input),
    "sobel":     (0x02, dma_sobel),
    "laplacian": (0x04, dma_laplacian),
    "canny":     (0x08, dma_canny),
}


def fpga_frame(gray, rx_dma):
    """One 256x256 gray frame through the FPGA."""
    input_buffer[:] = gray.reshape(-1)
    input_buffer.flush()

    rx_dma.recvchannel.transfer(output_buffer)
    dma_input.sendchannel.transfer(input_buffer)

    dma_input.sendchannel.wait()
    rx_dma.recvchannel.wait()

    output_buffer.invalidate()
    return np.array(output_buffer, dtype=np.uint8).reshape(HEIGHT, WIDTH)


# ======================================================================
#  WEB PAGE
# ======================================================================
_WEB_PAGE = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>FPGA Output</title>
<style>
  html,body{margin:0;height:100%;background:#000;overflow:hidden}
  img{width:100vw;height:100vh;object-fit:fill;display:block}
</style></head>
<body>
<img src="/stream" alt="">
<script>
  document.addEventListener('dblclick', function () {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  });
</script>
</body></html>"""


class _WebHub:
    """Tiny MJPEG server. Sends the newest JPEG to every browser."""

    def __init__(self):
        self._cond = threading.Condition()
        self._seq = 0
        self._latest = cv2.imencode(
            ".jpg", np.zeros((16, 16), dtype=np.uint8))[1].tobytes()
        self._started = False
        self._server = None

    def show(self, jpg):
        with self._cond:
            self._latest = jpg
            self._seq += 1
            self._cond.notify_all()

    def start(self, port):
        if self._started:
            return
        self._started = True
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/stream"):
                    self._stream()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(_WEB_PAGE)))
                    self.end_headers()
                    self.wfile.write(_WEB_PAGE)

            def _stream(self):
                try:
                    self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass

                self.send_response(200)
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()

                last = -1
                try:
                    while True:
                        with hub._cond:
                            hub._cond.wait_for(lambda: hub._seq != last, timeout=5)
                            jpg, last = hub._latest, hub._seq
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpg)).encode() +
                            b"\r\n\r\n" + jpg + b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        server = None
        for p in range(port, port + 11):
            try:
                server = ThreadingHTTPServer(("0.0.0.0", p), Handler)
                port = p
                break
            except OSError:
                continue

        if server is None:
            self._started = False
            raise OSError("No free port between %d and %d" % (port, port + 10))

        self._server = server
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

        ip = None
        for target in (("8.8.8.8", 80), ("192.168.2.1", 80), ("10.255.255.255", 1)):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(target)
                ip = s.getsockname()[0]
                s.close()
                break
            except OSError:
                pass

        if not ip:
            try:
                out = subprocess.check_output(["hostname", "-I"]).decode().split()
                ip = out[0] if out else None
            except Exception:
                ip = None

        print("Web video page : http://%s:%d/" % (ip or "<board-ip>", port))


# If this cell is run again, close the server left by the previous run
try:
    _web._server.shutdown()
    _web._server.server_close()
except Exception:
    pass

_web = _WebHub()


def web_start(port=WEB_PORT):
    _web.start(port)


# ======================================================================
#  IMAGE PROCESSING
# ======================================================================
input_img = None


def input_image(filename):
    global input_img
    input_img = Image.open(filename).convert("RGB").resize((WIDTH, HEIGHT))


def show_result(title, data):
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 2, 1)
    plt.imshow(input_img)
    plt.title("INPUT IMAGE - 256 x 256")
    plt.axis("off")
    plt.subplot(1, 2, 2)
    plt.imshow(data, cmap="gray")
    plt.title(title + " - 256 x 256")
    plt.axis("off")
    plt.tight_layout()
    plt.show()


def _image_run(name):
    if input_img is None:
        raise RuntimeError("Call input_image('file.png') first")

    sel, rx_dma = FILTERS[name]
    gray = np.array(input_img.convert("L"), dtype=np.uint8)
    gpio.write(0x00, sel)
    out = fpga_frame(gray, rx_dma)
    gpio.write(0x00, 0x00)
    show_result(name.upper() + " OUTPUT", out)


def image_gaussian():
    _image_run("gaussian")


def image_sobel():
    _image_run("sobel")


def image_laplacian():
    _image_run("laplacian")


def image_canny():
    _image_run("canny")


def image_all():
    for name in FILTERS:
        _image_run(name)


# ======================================================================
#  VIDEO INPUT
# ======================================================================
_source = None
_live = False          # camera / stream / function
_remove = False
_src_fps = 30.0
_STOP = object()
_ffmpeg_state = [None]


class _FnCap:
    """Lets any function (for example an HDMI-in reader) act like a camera."""

    def __init__(self, fn):
        self.fn = fn

    def read(self):
        fr = self.fn()
        return (fr is not None), fr

    def grab(self):
        return True

    def get(self, prop):
        return 0

    def set(self, prop, value):
        pass

    def isOpened(self):
        return True

    def release(self):
        pass


def _open_usb_camera(index):
    """Opens one USB camera. Tries MJPG first (fast), then the normal mode.
    Returns None if this camera number does not work."""
    for use_mjpg in (True, False):
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            return None

        if use_mjpg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
        cap.set(cv2.CAP_PROP_FPS, CAM_FPS)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        ok, _ = cap.read()
        if ok:
            return cap
        cap.release()

    return None


def _open_cv():
    if callable(_source):
        return _FnCap(_source)

    if isinstance(_source, int):                      # USB camera
        cap = _open_usb_camera(_source)
        return cap if cap is not None else cv2.VideoCapture()   # closed = not opened

    cap = cv2.VideoCapture(_source)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


def _ffmpeg_exe():
    if _ffmpeg_state[0] is None:
        found = None
        candidates = ["ffmpeg"]
        try:
            import imageio_ffmpeg
            candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:
            pass
        for exe in candidates:
            try:
                subprocess.check_output([exe, "-version"], stderr=subprocess.STDOUT)
                found = exe
                break
            except Exception:
                continue
        _ffmpeg_state[0] = found if found else False
    return _ffmpeg_state[0] or None


def _use_ffmpeg():
    return (not _live) and bool(_ffmpeg_exe())


def input_video(source):
    global _source, _live, _remove, _src_fps

    if isinstance(source, str) and source.lower() == LIVE_VIDEO:
        input_camera()                      # USB camera (found automatically)
        return

    if isinstance(source, str) and source.isdigit():
        source = int(source)

    _source = source
    _live = callable(source) or isinstance(source, int) or "://" in str(source)
    _remove = REMOVE_TITLE and not _live

    cap = _open_cv()
    if not cap.isOpened():
        raise IOError("Cannot open source: %s" % (source,))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    _src_fps = fps if (fps and 1.0 <= fps <= 120.0) else 30.0

    if not _live and not _ffmpeg_exe():
        print("ffmpeg not found -> slow OpenCV decoder is used.")
        print("Install it once:  sudo apt-get install ffmpeg")

    if not _live and _ffmpeg_exe():
        _preload()


def input_camera(index=None):
    """USB camera as the input. index=None -> finds it automatically (/dev/video0..3)."""
    indexes = range(4) if index is None else [index]

    for i in indexes:
        cap = _open_usb_camera(i)
        if cap is not None:
            cap.release()
            input_video(i)
            return

    raise IOError("USB camera not found. Plug it in and check with:  ls /dev/video*")


def set_camera_flip(mode):
    """Fixes an inverted camera picture: 'none', 'updown', 'leftright' or 'rotate180'."""
    global CAMERA_FLIP
    if mode not in ("none", "updown", "leftright", "rotate180"):
        raise ValueError("mode must be 'none', 'updown', 'leftright' or 'rotate180'")
    CAMERA_FLIP = mode


def camera_view(seconds=None):
    """Live camera picture only (no filter) in the notebook. Stop button = stop."""
    cap = None
    for index in range(4):
        cap = _open_usb_camera(index)
        if cap is not None:
            break
    if cap is None:
        raise IOError("USB camera not found. Plug it in and check with:  ls /dev/video*")

    view = widgets.Image(format="jpeg")
    status = widgets.HTML()
    display(widgets.VBox([view, status]))

    t0 = fps_t = time.time()
    n = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            code = _FLIP_CODES.get(CAMERA_FLIP)
            if code is not None:
                frame = cv2.flip(frame, code)

            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                view.value = jpg.tobytes()

            n += 1
            now = time.time()

            if now - fps_t >= 1.0:
                status.value = "USB camera &nbsp; %.1f FPS" % (n / (now - fps_t))
                fps_t, n = now, 0

            if seconds and now - t0 >= seconds:
                break

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()


# ----------------------------------------------------------------------
#  RAM CACHE: the file is decoded ONCE, then played from memory.
#  Input reading is then a memory copy (far above 40 FPS).
# ----------------------------------------------------------------------
MAX_CACHE_MB = 400                # videos bigger than this are streamed as before
_cache = {}


def _cache_key():
    return (str(_source), _remove, TITLE_X0, TITLE_Y0, TITLE_X1, TITLE_Y1)


def _preload():
    key = _cache_key()
    if key in _cache:
        return

    ff = _ffmpeg_exe()
    fsize = SIZE * 3
    vf = "fps=%g,scale=%d:%d:flags=fast_bilinear" % (_src_fps, WIDTH, HEIGHT)
    if _remove:
        vf += ",delogo=x=%d:y=%d:w=%d:h=%d" % (
            max(TITLE_X0, 1), max(TITLE_Y0, 1),
            TITLE_X1 - TITLE_X0, TITLE_Y1 - TITLE_Y0)

    cmd = [ff, "-v", "error", "-threads", "4", "-skip_loop_filter", "all",
           "-i", str(_source), "-an", "-sn", "-vf", vf,
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]

    print("Loading video into memory (one time) ...")
    t = time.perf_counter()
    frames = []
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=fsize * 4)
    too_big = False
    try:
        while True:
            flat = np.empty(fsize, dtype=np.uint8)
            if not _read_into(proc.stdout, memoryview(flat)):
                break
            frames.append(flat.reshape(HEIGHT, WIDTH, 3))
            if len(frames) * fsize > MAX_CACHE_MB * 1024 * 1024:
                too_big = True
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()

    if too_big or not frames:
        print("Video not cached (%s) -> it will be streamed." %
              ("too big" if too_big else "no frames"))
        return

    _cache[key] = frames
    print("Loaded %d frames in %.1f s. Input reading is now from memory." %
          (len(frames), time.perf_counter() - t))


def _cache_stream(q, stop, ctx, drop):
    """Plays the cached frames, repeating them to reach TARGET_FPS."""
    frames = _cache.get(_cache_key())
    if not frames:
        return False

    step = TARGET_FPS / _src_fps
    acc = 0.0
    t_mark = time.perf_counter()

    while not stop.is_set():
        for fr in frames:
            acc += step
            copies = int(acc)
            acc -= copies
            for _ in range(copies):
                ctx["rd_t"] = ctx.get("rd_t", 0.0) + time.perf_counter() - t_mark
                ctx["rd_n"] = ctx.get("rd_n", 0) + 1
                if not _push(q, fr, stop, drop):
                    return True
                t_mark = time.perf_counter()
            if stop.is_set():
                return True
        if not LOOP:
            break
    return True


def set_title_box(x0, y0, x1, y1):
    global TITLE_X0, TITLE_Y0, TITLE_X1, TITLE_Y1
    TITLE_X0, TITLE_Y0, TITLE_X1, TITLE_Y1 = x0, y0, x1, y1


def _remove_title(frame):
    """Cover the heading with the clean rows just above it."""
    h = TITLE_Y1 - TITLE_Y0
    if TITLE_Y0 - h >= 0:
        src = frame[TITLE_Y0 - h:TITLE_Y0, TITLE_X0:TITLE_X1]
    else:
        src = frame[TITLE_Y1:TITLE_Y1 + h, TITLE_X0:TITLE_X1]
    frame[TITLE_Y0:TITLE_Y1, TITLE_X0:TITLE_X1] = src
    return frame


def show_first_frame():
    """One frame with the heading box (red) and a grid, to read coordinates."""
    if _source is None:
        raise RuntimeError("Call input_video(...) first")

    cap = _open_cv()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Cannot read a frame")

    frame = cv2.resize(frame, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)

    plt.figure(figsize=(8, 8))
    plt.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    plt.gca().add_patch(plt.Rectangle(
        (TITLE_X0, TITLE_Y0), TITLE_X1 - TITLE_X0, TITLE_Y1 - TITLE_Y0,
        fill=False, edgecolor="red", linewidth=2))
    plt.xticks(range(0, WIDTH + 1, 16))
    plt.yticks(range(0, HEIGHT + 1, 16))
    plt.grid(True, alpha=0.4)
    plt.title("Red box = area that will be removed")
    plt.show()


# ======================================================================
#  PIPELINE:  reader -> FPGA + JPEG -> fixed output clock
# ======================================================================
def _push(q, item, stop, drop):
    """drop=True: camera style, the oldest frame is thrown away, never waits."""
    if drop:
        while True:
            try:
                q.put_nowait(item)
                return True
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass

    while not stop.is_set():
        try:
            q.put(item, timeout=0.1)
            return True
        except queue.Full:
            pass
    return False


def _take(q, stop):
    while not stop.is_set():
        try:
            return q.get(timeout=0.1)
        except queue.Empty:
            pass
    return None


def _read_into(stream, mv):
    got, size = 0, len(mv)
    while got < size:
        r = stream.readinto(mv[got:])
        if not r:
            return False
        got += r
    return True


def _drain(f, buf):
    """Keep ffmpeg's error lines (so its pipe never fills up)."""
    try:
        for line in f:
            buf.append(line.decode("utf-8", "ignore").strip())
    except Exception:
        pass


def _ffmpeg_cmd(ff):
    vf = "fps=%g,scale=%d:%d:flags=fast_bilinear" % (TARGET_FPS, WIDTH, HEIGHT)
    if _remove:
        vf += ",delogo=x=%d:y=%d:w=%d:h=%d" % (
            max(TITLE_X0, 1), max(TITLE_Y0, 1),
            TITLE_X1 - TITLE_X0, TITLE_Y1 - TITLE_Y0)

    cmd = [ff, "-v", "error", "-threads", "2", "-skip_loop_filter", "all"]
    if FAST_DECODE:
        cmd += ["-skip_frame", "noref"]           # skip B-frames: less decode work
    return cmd + ["-i", str(_source), "-an", "-sn", "-vf", vf,
                  "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]


def _ffmpeg_stream(q, stop, ctx, drop):
    """Returns False only if ffmpeg could not deliver a single frame."""
    ff = _ffmpeg_exe()
    fsize = SIZE * 3
    err = collections.deque(maxlen=4)
    total = 0

    while not stop.is_set():
        proc = subprocess.Popen(_ffmpeg_cmd(ff), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=fsize * 4)
        ctx["proc"] = proc
        threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True).start()

        try:                                       # bigger pipe = smoother
            import fcntl
            fcntl.fcntl(proc.stdout.fileno(), 1031, 1 << 20)
        except Exception:
            pass

        try:
            t_mark = time.perf_counter()
            while not stop.is_set():
                flat = np.empty(fsize, dtype=np.uint8)
                if not _read_into(proc.stdout, memoryview(flat)):
                    break
                if total > 0:                      # time spent waiting for ffmpeg
                    ctx["rd_t"] = ctx.get("rd_t", 0.0) + time.perf_counter() - t_mark
                    ctx["rd_n"] = ctx.get("rd_n", 0) + 1
                total += 1
                if not _push(q, flat.reshape(HEIGHT, WIDTH, 3), stop, drop):
                    return True
                t_mark = time.perf_counter()
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

        if not LOOP or total == 0:
            break

    if total == 0 and not stop.is_set():
        for line in err:
            print("ffmpeg:", line)
        return False
    return True


def _cv_stream(q, stop, ctx, drop):
    """OpenCV reader: camera, stream, function (or file if ffmpeg fails)."""
    cap = _open_cv()
    acc = 0.0
    step = TARGET_FPS / _src_fps
    t_mark = time.perf_counter()
    try:
        while not stop.is_set():
            if _live:
                ok, fr = cap.read()
                if not ok:
                    break
                copies = 1
            else:
                if not cap.grab():
                    if LOOP:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    break
                acc += step                       # drop / repeat to match TARGET_FPS
                if acc < 1.0:
                    continue
                ok, fr = cap.retrieve()
                if not ok:
                    break
                copies = int(acc)
                acc -= copies

            fr = cv2.resize(fr, (WIDTH, HEIGHT), interpolation=RESIZE_INTERP)
            if _remove:
                fr = _remove_title(fr)

            if isinstance(_source, int):          # USB camera: fix the inverted picture
                code = _FLIP_CODES.get(CAMERA_FLIP)
                if code is not None:
                    fr = cv2.flip(fr, code)

            ctx["rd_t"] = ctx.get("rd_t", 0.0) + time.perf_counter() - t_mark
            ctx["rd_n"] = ctx.get("rd_n", 0) + 1

            for _ in range(copies):
                if not _push(q, fr, stop, drop):
                    return
            t_mark = time.perf_counter()
    finally:
        cap.release()


def _reader(q, stop, ctx, drop):
    """Stage 1: ffmpeg process for files, OpenCV for camera / stream / function."""
    try:
        if _use_ffmpeg():
            if _cache_stream(q, stop, ctx, drop):
                return
            if _ffmpeg_stream(q, stop, ctx, drop):
                return
            print("ffmpeg could not decode this video -> using OpenCV (slow).")
        _cv_stream(q, stop, ctx, drop)
    finally:
        _push(q, _STOP, stop, True)


def _fpga_worker(q_in, q_out, sel, rx_dma, stop, drop, box, jpeg_quality, ctx):
    """Stage 2: FPGA filter + JPEG."""
    web_enc = [cv2.IMWRITE_JPEG_QUALITY, WEB_JPEG_QUALITY]
    pre_enc = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
    every = max(1, int(round(TARGET_FPS / float(PREVIEW_FPS))))
    idx = 0

    try:
        gpio.write(0x00, sel)

        while True:
            color = _take(q_in, stop)
            if color is None or color is _STOP:
                break

            t_f = time.perf_counter()
            gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
            out = fpga_frame(gray, rx_dma)

            ok, jpg = cv2.imencode(".jpg", out, web_enc)
            ctx["fp_t"] = ctx.get("fp_t", 0.0) + time.perf_counter() - t_f
            ctx["fp_n"] = ctx.get("fp_n", 0) + 1

            if ok and not _push(q_out, jpg.tobytes(), stop, drop):
                break

            if NOTEBOOK_PREVIEW and idx % every == 0:
                canvas = np.hstack([color, cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)])
                ok2, pj = cv2.imencode(".jpg", canvas, pre_enc)
                if ok2:
                    box["jpg"] = pj.tobytes()
                    box["seq"] += 1
            idx += 1
    finally:
        _push(q_out, _STOP, stop, True)


def _preview_worker(view, status, box, stop):
    """Sends the newest notebook picture + status. Own thread: never blocks the clock."""
    last_seq = -1
    last_jpg = None

    while not stop.is_set():
        seq = box["seq"]
        if seq != last_seq:
            last_seq = seq
            try:
                jpg = box["jpg"]
                if jpg is not None and jpg is not last_jpg:
                    view.value = jpg
                    last_jpg = jpg
                status.value = box["status"]
            except Exception:
                pass
        time.sleep(0.05)


def _run(title, sel, rx_dma, seconds, jpeg_quality):
    if _source is None:
        raise RuntimeError("Call input_video(...) first")

    web_start()

    drop = _live
    q_in = queue.Queue(maxsize=3)
    q_out = queue.Queue(maxsize=4)
    stop = threading.Event()
    prev_stop = threading.Event()
    ctx = {"proc": None}
    box = {"jpg": None, "seq": 0, "status": ""}

    threads = [
        threading.Thread(target=_reader, args=(q_in, stop, ctx, drop), daemon=True),
        threading.Thread(target=_fpga_worker,
                         args=(q_in, q_out, sel, rx_dma, stop, drop, box, jpeg_quality, ctx),
                         daemon=True),
    ]

    if NOTEBOOK_PREVIEW:
        view = widgets.Image(format="jpeg")
        status = widgets.HTML()
        display(widgets.VBox([view, status]))
        threading.Thread(target=_preview_worker,
                         args=(view, status, box, prev_stop), daemon=True).start()

    for t in threads:
        t.start()

    # wait until a few frames are ready (a few ms when the source is fast)
    t_w = time.time()
    while q_out.qsize() < 3 and time.time() - t_w < 3.0:
        time.sleep(0.002)

    period = 1.0 / TARGET_FPS
    t0 = time.perf_counter()
    next_t = t0
    fresh = 0                                    # frames that really were NEW
    fps_t, fps_n = t0, 0

    try:
        # ---- ONE fixed clock: exactly TARGET_FPS output ticks per second ----
        while True:
            if seconds and time.perf_counter() - t0 >= seconds:
                break

            try:
                item = q_out.get_nowait()
            except queue.Empty:
                item = None                      # no new frame yet: previous one stays

            if item is _STOP:
                break

            if item is not None:
                _web.show(item)
                fresh += 1
                fps_n += 1

            next_t += period
            now = time.perf_counter()
            d = next_t - now

            if now - fps_t >= 1.0:
                box["status"] = ("<b>%s</b> &nbsp; LIVE &nbsp; Frame %d &nbsp; %.1f FPS" %
                                 (title, fresh, fps_n / (now - fps_t)))
                box["seq"] += 1
                fps_t, fps_n = now, 0

            if d > 0:
                time.sleep(d)
            elif d < -2 * period:
                next_t = time.perf_counter()

    except KeyboardInterrupt:
        pass

    finally:
        stop.set()
        p = ctx.get("proc")
        if p is not None and p.poll() is None:
            p.kill()
        for t in threads:
            t.join(timeout=2.0)

        box["status"] = "<b>%s</b> &nbsp; Finished: %d frames" % (title, fresh)
        box["seq"] += 1
        time.sleep(0.2)
        prev_stop.set()
        gpio.write(0x00, 0x00)

    # shown only when the output was below TARGET_FPS: which part is the limit?
    avg = fresh / max(time.perf_counter() - t0, 1e-9)
    if avg < TARGET_FPS - 1.0 and ctx.get("rd_n") and ctx.get("fp_n"):
        print("%.1f FPS.   Limit of input decode: %.1f FPS   |   limit of FPGA+JPEG: %.1f FPS" %
              (avg, ctx["rd_n"] / max(ctx["rd_t"], 1e-9),
               ctx["fp_n"] / max(ctx["fp_t"], 1e-9)))


def video_gaussian(seconds=None, jpeg_quality=80):
    _run("GAUSSIAN", 0x01, dma_input, seconds, jpeg_quality)


def video_sobel(seconds=None, jpeg_quality=80):
    _run("SOBEL", 0x02, dma_sobel, seconds, jpeg_quality)


def video_laplacian(seconds=None, jpeg_quality=80):
    _run("LAPLACIAN", 0x04, dma_laplacian, seconds, jpeg_quality)


def video_canny(seconds=None, jpeg_quality=80):
    _run("CANNY", 0x08, dma_canny, seconds, jpeg_quality)


def video_all(seconds=None):
    video_gaussian(seconds)
    video_sobel(seconds)
    video_laplacian(seconds)
    video_canny(seconds)


# ======================================================================
#  CHECK TOOL  (prints only when you call it)
# ======================================================================
def profile(filter_name="sobel", frames=90):
    """Real speed of the two parts: input reading, and FPGA + JPEG."""
    if _source is None:
        raise RuntimeError("Call input_video(...) first")

    q = queue.Queue(maxsize=frames + 5)
    stop = threading.Event()
    ctx = {"proc": None}

    t = time.perf_counter()
    th = threading.Thread(target=_reader, args=(q, stop, ctx, False), daemon=True)
    th.start()

    n = 0
    while n < frames:
        if q.get() is _STOP:
            break
        n += 1
    el = time.perf_counter() - t

    stop.set()
    p = ctx.get("proc")
    if p is not None and p.poll() is None:
        p.kill()
    th.join(timeout=2.0)

    print("Input reading : %.1f FPS   (%s)" %
          (n / max(el, 1e-9), "ffmpeg" if _use_ffmpeg() else "OpenCV"))

    sel, rx = FILTERS[filter_name]
    gpio.write(0x00, sel)
    gray = np.random.randint(0, 256, (HEIGHT, WIDTH), dtype=np.uint8)
    enc = [cv2.IMWRITE_JPEG_QUALITY, WEB_JPEG_QUALITY]

    t = time.perf_counter()
    for _ in range(100):
        cv2.imencode(".jpg", fpga_frame(gray, rx), enc)
    el = time.perf_counter() - t
    gpio.write(0x00, 0x00)

    print("FPGA + JPEG   : %.1f FPS" % (100 / el))


# ======================================================================
#  BANNER
# ======================================================================
web_start()

print()
print("System initialized successfully")
print()



