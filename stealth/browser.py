"""
stealth/browser.py — Stealth Playwright browser factory.

Launches a Chromium instance with:
- playwright-stealth patches (spoofs navigator, plugins, WebGL, etc.)
- Randomised User-Agent, viewport, locale, timezone
- Optional residential proxy
- Comprehensive fingerprint spoofing to pass Cloudflare Turnstile
"""
from __future__ import annotations

import random
from typing import Optional

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Playwright
from playwright_stealth import stealth_async

from config.settings import settings

# Pool of realistic User-Agents (Chrome 122-124 range, common platforms)
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

_TIMEZONES = [
    "Australia/Sydney",
    "Australia/Melbourne",
    "Australia/Brisbane",
]

# Comprehensive stealth script that defeats Cloudflare Turnstile bot detection.
# Patches the most common automation fingerprints that CF checks:
#   - navigator.webdriver (most critical)
#   - chrome runtime object
#   - plugins / mimeTypes (empty in headless)
#   - permissions API
#   - navigator.languages
#   - WebGL vendor/renderer
#   - Canvas fingerprint noise
#   - window.outerWidth/Height
#   - navigator.hardwareConcurrency / deviceMemory
_STEALTH_INIT_SCRIPT = """
(function () {
    'use strict';

    // ── 1. Remove navigator.webdriver ────────────────────────────────────────
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });

    // ── 2. Restore chrome runtime (missing in headless) ──────────────────────
    if (!window.chrome) {
        window.chrome = {
            app: { isInstalled: false, InstallState: {}, RunningState: {} },
            runtime: {
                OnInstalledReason: {},
                OnRestartRequiredReason: {},
                PlatformArch: {},
                PlatformNaclArch: {},
                PlatformOs: {},
                RequestUpdateCheckStatus: {},
                connect: function() {},
                sendMessage: function() {},
            },
            loadTimes: function() {},
            csi: function() {},
        };
    }

    // ── 3. Spoof plugins (headless has none) ─────────────────────────────────
    const makePlugin = (name, desc, filename, mimeTypes) => {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperties(plugin, {
            name:        { value: name, enumerable: true },
            description: { value: desc, enumerable: true },
            filename:    { value: filename, enumerable: true },
            length:      { value: mimeTypes.length, enumerable: true },
        });
        mimeTypes.forEach((mt, i) => {
            const mime = Object.create(MimeType.prototype);
            Object.defineProperties(mime, {
                type:        { value: mt.type, enumerable: true },
                description: { value: mt.description, enumerable: true },
                suffixes:    { value: mt.suffixes, enumerable: true },
                enabledPlugin: { value: plugin, enumerable: true },
            });
            plugin[i] = mime;
            plugin[mt.type] = mime;
        });
        return plugin;
    };

    const pdfPlugin = makePlugin(
        'PDF Viewer', 'Portable Document Format',
        'internal-pdf-viewer',
        [{ type: 'application/pdf', description: 'Portable Document Format', suffixes: 'pdf' }]
    );
    const chromePdf = makePlugin(
        'Chrome PDF Viewer', 'Portable Document Format',
        'internal-pdf-viewer',
        [{ type: 'application/pdf', description: 'Portable Document Format', suffixes: 'pdf' }]
    );
    const nativePdf = makePlugin(
        'Chromium PDF Plugin', 'Portable Document Format',
        'internal-pdf-viewer',
        [{ type: 'application/x-google-chrome-pdf', description: 'Portable Document Format', suffixes: 'pdf' }]
    );

    const pluginArray = Object.create(PluginArray.prototype);
    [pdfPlugin, chromePdf, nativePdf].forEach((p, i) => {
        pluginArray[i] = p;
        pluginArray[p.name] = p;
    });
    Object.defineProperty(pluginArray, 'length', { value: 3 });
    Object.defineProperty(navigator, 'plugins', {
        get: () => pluginArray,
        configurable: true,
    });

    // ── 4. Permissions API — don't reveal automation ─────────────────────────
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(parameters)
        );
    }

    // ── 5. Languages ─────────────────────────────────────────────────────────
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-AU', 'en-GB', 'en'],
        configurable: true,
    });

    // ── 6. Hardware signals ──────────────────────────────────────────────────
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
        configurable: true,
    });
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
        configurable: true,
    });

    // ── 7. Window size (headless has no outer size) ──────────────────────────
    if (window.outerWidth === 0) {
        Object.defineProperty(window, 'outerWidth',  { get: () => window.innerWidth,  configurable: true });
        Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 85, configurable: true });
    }

    // ── 8. WebGL vendor/renderer ─────────────────────────────────────────────
    const getCtx = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, ...args) {
        const ctx = getCtx.call(this, type, ...args);
        if (!ctx) return ctx;
        if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') {
            const getParam = ctx.getParameter.bind(ctx);
            ctx.getParameter = function(param) {
                if (param === 37445) return 'Google Inc. (Intel)';     // UNMASKED_VENDOR_WEBGL
                if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)'; // UNMASKED_RENDERER_WEBGL
                return getParam(param);
            };
        }
        return ctx;
    };

    // ── 9. Canvas fingerprint noise ──────────────────────────────────────────
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, ...args) {
        if (this.width > 16 && this.height > 16) {
            const ctx2d = getCtx.call(this, '2d');
            if (ctx2d) {
                const imageData = ctx2d.getImageData(0, 0, 1, 1);
                imageData.data[0] = imageData.data[0] ^ 1;
                ctx2d.putImageData(imageData, 0, 0);
            }
        }
        return origToDataURL.apply(this, [type, ...args]);
    };

    // ── 10. iframe contentWindow access ─────────────────────────────────────
    // Some detectors check if iframes have same-origin restrictions
    // This is a no-op but signals normal browser behaviour
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() {
            return this.contentWindow;
        },
    });

})();
"""

# Manual login / visible CAPTCHA: heavy patches (canvas, iframe, WebGL) can prevent
# Cloudflare Turnstile from rendering. Use this tiny patch only.
_MIN_STEALTH_INIT_SCRIPT = """
(function () {
    'use strict';
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });
})();
"""


async def make_browser_context(
    playwright: Playwright,
    storage_state: Optional[str] = None,
    *,
    headless: bool = True,
    channel: Optional[str] = None,
    trust_browser_defaults: bool = False,
    minimal_stealth: bool = False,
) -> tuple[Browser, BrowserContext]:
    """
    Launch a stealth-patched browser and create a context.

    For **manual login** on Windows/macOS, use ``channel="chrome"`` and
    ``trust_browser_defaults=True`` so Playwright drives **installed Google Chrome**
    with native UA / client hints — Cloudflare Turnstile often fails on bundled
    Chromium with synthetic ``sec-ch-ua`` headers.

    Set ``minimal_stealth=True`` when the user must **see or solve** Turnstile in the
    UI: full stealth + playwright-stealth can stop the challenge iframe from loading.

    Returns (browser, context).
    """
    timezone = random.choice(_TIMEZONES)
    locale = "en-AU"

    if trust_browser_defaults:
        viewport = {"width": 1440, "height": 900}
        logger.debug(
            f"[BROWSER] Using installed browser channel={channel!r} — native UA/client hints; "
            f"viewport={viewport} tz={timezone}"
        )
    else:
        ua = random.choice(_USER_AGENTS)
        viewport = random.choice(_VIEWPORTS)
        logger.debug(
            f"[BROWSER] UA={ua[:40]}... viewport={viewport} tz={timezone}"
        )

    launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-automation",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--metrics-recording-only",
        "--safebrowsing-disable-auto-update",
        "--password-store=basic",
        "--use-mock-keychain",
        "--window-size=1440,900",
        "--start-maximized",
    ]
    # Full stealth stack disables extensions; keep them for minimal / real-Chrome CAPTCHA UX.
    if not minimal_stealth:
        launch_args.insert(5, "--disable-extensions")

    launch_kwargs: dict = {
        "headless": headless,
        "args": launch_args,
    }
    if channel:
        launch_kwargs["channel"] = channel

    proxy_cfg = settings.proxy_config
    if proxy_cfg:
        launch_kwargs["proxy"] = proxy_cfg
        logger.info(f"[BROWSER] Proxy enabled: {proxy_cfg['server']}")
    else:
        logger.warning("[BROWSER] No proxy configured — detection risk elevated")

    browser = await playwright.chromium.launch(**launch_kwargs)

    context_kwargs: dict = {
        "viewport": viewport,
        "locale": locale,
        "timezone_id": timezone,
        "java_script_enabled": True,
        "bypass_csp": True,
        "ignore_https_errors": True,  # BrightData uses custom SSL cert
        "extra_http_headers": {
            "Accept-Language": "en-AU,en-GB;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
        },
    }
    if trust_browser_defaults:
        # Do not override UA / sec-ch-* — must match real Chrome for Turnstile.
        pass
    else:
        context_kwargs["user_agent"] = ua
        context_kwargs["extra_http_headers"].update(
            {
                "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        )

    if storage_state:
        context_kwargs["storage_state"] = storage_state
        logger.info(f"[BROWSER] Loading stored session: {storage_state}")

    context = await browser.new_context(**context_kwargs)

    if minimal_stealth:
        await context.add_init_script(_MIN_STEALTH_INIT_SCRIPT)
        logger.info("[BROWSER] Minimal stealth (webdriver patch only) — Turnstile / CAPTCHA friendly")
    else:
        await context.add_init_script(_STEALTH_INIT_SCRIPT)
        context.on("page", lambda page: _apply_stealth(page))

    return browser, context


def _apply_stealth(page) -> None:
    """Schedule playwright-stealth patches on a newly opened page."""
    import asyncio
    asyncio.ensure_future(stealth_async(page))