"""Tiny Chrome DevTools driver (aiohttp only): open a page, press keys, run JS, take screenshots.
Used to capture site/docs/walk.gif. Uses the Playwright headless shell if cached, else Google Chrome; no other install."""
import asyncio, base64, json, os, subprocess, tempfile, urllib.request
import aiohttp

import glob
_SHELL = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell")))
CHROME = os.environ.get("CDP_CHROME") or (_SHELL[-1] if _SHELL else "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


class Page:
    def __init__(self, ws, proc, tmp):
        self.ws, self.proc, self.tmp, self.n = ws, proc, tmp, 0

    @classmethod
    async def open(cls, url, w=1280, h=720, port=9333, extra=()):
        tmp = tempfile.mkdtemp(prefix="cdp-", dir=os.environ.get("KIROCREW_SCRATCH"))
        proc = subprocess.Popen([CHROME, *([] if "headless-shell" in CHROME else ["--headless=new"]), f"--remote-debugging-port={port}", f"--user-data-dir={tmp}",
                                 f"--window-size={w},{h}", "--hide-scrollbars", "--remote-allow-origins=*", "--mute-audio", "--no-sandbox", "--disable-gpu-sandbox", "--no-first-run", *extra,
                                 "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
                tab = json.load(urllib.request.urlopen(req))
                break
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.25)
        await asyncio.sleep(1.0)  # a tab opened during startup can be dropped; let Chrome settle
        sess = aiohttp.ClientSession()
        ws = await sess.ws_connect(tab["webSocketDebuggerUrl"], max_msg_size=64 * 1024 * 1024)
        p = cls(ws, proc, tmp)
        p.sess = sess
        await p.send("Page.enable")
        await p.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
        await p.send("Page.navigate", url=url)
        return p

    async def _reader(self):
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            m = json.loads(msg.data)
            f = self.waiting.pop(m.get("id"), None)
            if f and not f.done():
                f.set_exception(RuntimeError(m["error"])) if "error" in m else f.set_result(m.get("result", {}))
        for f in self.waiting.values():
            if not f.done():
                f.set_exception(RuntimeError("browser closed"))

    async def send(self, method, **params):
        """Many callers may send at once (a frame recorder plus the driver): one reader task routes replies by id."""
        if not hasattr(self, "waiting"):
            self.waiting = {}
            self.reader = asyncio.create_task(self._reader())
        self.n += 1
        f = asyncio.get_running_loop().create_future()
        self.waiting[self.n] = f
        await self.ws.send_json({"id": self.n, "method": method, "params": params})
        return await f

    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    async def key(self, key, down=True, text=None):
        codes = {"ArrowUp": 38, "ArrowDown": 40, "ArrowLeft": 37, "ArrowRight": 39, "Escape": 27, "Enter": 13, "Shift": 16}
        vk = codes.get(key, ord(key.upper()) if len(key) == 1 else 0)
        await self.send("Input.dispatchKeyEvent", type="keyDown" if down else "keyUp", key=key, windowsVirtualKeyCode=vk,
                        text=(text if text is not None else (key if len(key) == 1 and down else "")), code=("Key" + key.upper()) if len(key) == 1 else key)

    async def type(self, s):
        for c in s:
            await self.send("Input.dispatchKeyEvent", type="keyDown", key=c, text=c)
            await self.send("Input.dispatchKeyEvent", type="keyUp", key=c)

    async def insert(self, text):
        await self.send("Input.insertText", text=text)

    async def shot(self, path=None, fmt="png"):
        r = await self.send("Page.captureScreenshot", format=fmt, **({"quality": 80} if fmt == "jpeg" else {}))
        data = base64.b64decode(r["data"])
        if path:
            open(path, "wb").write(data)
        return data

    async def close(self):
        try:
            await self.sess.close()
        finally:
            self.proc.terminate()
