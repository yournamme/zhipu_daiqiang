const fs = require('fs');
const vm = require('vm');

function readInput() {
  const inputPath = process.argv[2];
  if (!inputPath) {
    throw new Error('missing_input_path');
  }
  return JSON.parse(fs.readFileSync(inputPath, 'utf8'));
}

function makeStorage() {
  const store = new Map();
  return {
    getItem(key) {
      return store.has(String(key)) ? store.get(String(key)) : null;
    },
    setItem(key, value) {
      store.set(String(key), String(value));
    },
    removeItem(key) {
      store.delete(String(key));
    },
    clear() {
      store.clear();
    },
    key(index) {
      return [...store.keys()][index] ?? null;
    },
    get length() {
      return store.size;
    },
  };
}

function makeNoopProxy(target = {}) {
  return new Proxy(target, {
    get(obj, prop) {
      if (prop === Symbol.toPrimitive) {
        return () => '';
      }
      if (prop in obj) {
        return obj[prop];
      }
      return function noop() {
        return undefined;
      };
    },
  });
}

function createElementStub(extra = {}) {
  return makeNoopProxy({
    style: {},
    classList: makeNoopProxy({
      add() {},
      remove() {},
      contains() {
        return false;
      },
    }),
    children: [],
    childNodes: [],
    attributes: {},
    appendChild() {},
    removeChild() {},
    insertBefore() {},
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return this.attributes[name] ?? null;
    },
    getBoundingClientRect() {
      return { width: 300, height: 150, top: 0, left: 0, right: 300, bottom: 150 };
    },
    addEventListener() {},
    removeEventListener() {},
    ...extra,
  });
}

function buildWindow(input) {
  const localStorage = makeStorage();
  const sessionStorage = makeStorage();
  const entryUrl = input.entryUrl || 'https://www.bigmodel.cn/glm-coding';
  const url = new URL(entryUrl);

  const document = makeNoopProxy({
    cookie: input.cookieHeader || '',
    referrer: entryUrl,
    URL: entryUrl,
    charset: 'UTF-8',
    hidden: false,
    visibilityState: 'visible',
    documentElement: createElementStub({ clientWidth: 1920, clientHeight: 1080 }),
    body: createElementStub({ clientWidth: 1920, clientHeight: 1080 }),
    createElement(tag) {
      const normalized = String(tag).toLowerCase();
      if (normalized === 'canvas') {
        return createElementStub({
          getContext() {
            return makeNoopProxy({
              fillRect() {},
              clearRect() {},
              getImageData() {
                return { data: new Uint8ClampedArray(4) };
              },
              putImageData() {},
              createImageData() {
                return [];
              },
              setTransform() {},
              drawImage() {},
              save() {},
              fillText() {},
              restore() {},
              beginPath() {},
              moveTo() {},
              lineTo() {},
              closePath() {},
              stroke() {},
              translate() {},
              scale() {},
              rotate() {},
              arc() {},
              fill() {},
              measureText(text) {
                return { width: String(text).length * 8 };
              },
              transform() {},
              rect() {},
              clip() {},
            });
          },
          toDataURL() {
            return 'data:image/png;base64,AAAA';
          },
          width: 300,
          height: 150,
        });
      }
      if (normalized === 'audio' || normalized === 'video') {
        return createElementStub({
          canPlayType() {
            return 'probably';
          },
        });
      }
      return createElementStub({
        tagName: normalized.toUpperCase(),
        getContext() {
          return makeNoopProxy({});
        },
      });
    },
    getElementsByTagName() {
      return [createElementStub()];
    },
    createRange() {
      return makeNoopProxy({
        setStart() {},
        setEnd() {},
        getBoundingClientRect() {
          return { width: 100, height: 20 };
        },
      });
    },
    querySelector() {
      return createElementStub();
    },
    querySelectorAll() {
      return [];
    },
    getElementById() {
      return createElementStub();
    },
    addEventListener() {},
    removeEventListener() {},
  });

  function XMLHttpRequestStub() {
    this.readyState = 4;
    this.status = 200;
    this.responseText = '';
  }
  XMLHttpRequestStub.prototype.open = function open() {};
  XMLHttpRequestStub.prototype.send = function send() {
    if (typeof this.onload === 'function') {
      this.onload();
    }
  };
  XMLHttpRequestStub.prototype.setRequestHeader = function setRequestHeader() {};
  XMLHttpRequestStub.prototype.abort = function abort() {};

  const safeConsole = {
    log() {},
    info() {},
    warn() {},
    error() {},
    debug() {},
  };

  const windowObj = {
    window: null,
    self: null,
    globalThis: null,
    console: safeConsole,
    Date,
    Math,
    JSON,
    String,
    Number,
    Boolean,
    Array,
    Object,
    RegExp,
    Error,
    TypeError,
    Promise,
    Uint8Array,
    Uint8ClampedArray,
    ArrayBuffer,
    Buffer,
    URL,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    encodeURIComponent,
    decodeURIComponent,
    escape,
    unescape,
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {},
    setTimeout(fn) {
      if (typeof fn === 'function') {
        try {
          fn();
        } catch (_) {}
      }
      return 1;
    },
    clearTimeout() {},
    setInterval(fn) {
      if (typeof fn === 'function') {
        try {
          fn();
        } catch (_) {}
      }
      return 1;
    },
    clearInterval() {},
    requestAnimationFrame(fn) {
      if (typeof fn === 'function') {
        fn(1);
      }
      return 1;
    },
    cancelAnimationFrame() {},
    atob(value) {
      return Buffer.from(String(value), 'base64').toString('binary');
    },
    btoa(value) {
      return Buffer.from(String(value), 'binary').toString('base64');
    },
    location: {
      href: entryUrl,
      protocol: `${url.protocol}`,
      host: url.host,
      hostname: url.hostname,
      pathname: url.pathname,
      search: url.search,
      hash: url.hash,
    },
    innerWidth: 1920,
    innerHeight: 1080,
    outerWidth: 1920,
    outerHeight: 1080,
    screenX: 0,
    screenY: 0,
    devicePixelRatio: 1,
    screen: {
      width: 1920,
      height: 1080,
      availWidth: 1920,
      availHeight: 1040,
      colorDepth: 24,
      pixelDepth: 24,
      orientation: { angle: 0, type: 'landscape-primary' },
    },
    navigator: {
      userAgent:
        input.userAgent ||
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      language: 'zh-CN',
      languages: ['zh-CN', 'zh'],
      platform: 'Win32',
      hardwareConcurrency: 8,
      deviceMemory: 8,
      cookieEnabled: true,
      onLine: true,
      maxTouchPoints: 0,
      webdriver: false,
      vibrate() {
        return false;
      },
      geolocation: makeNoopProxy({}),
      mediaDevices: makeNoopProxy({}),
    },
    document,
    localStorage,
    sessionStorage,
    performance: {
      timing: {},
      now: () => 1234.56,
      getEntriesByType: () => [],
    },
    history: {
      pushState() {},
      replaceState() {},
    },
    CSS: {
      supports() {
        return true;
      },
    },
    crypto: {
      getRandomValues(array) {
        for (let i = 0; i < array.length; i += 1) {
          array[i] = (i * 17 + 29) % 256;
        }
        return array;
      },
    },
    XMLHttpRequest: XMLHttpRequestStub,
    Image: function Image() {
      return createElementStub();
    },
    Audio: function Audio() {
      return createElementStub();
    },
    HTMLElement: function HTMLElement() {},
    MutationObserver: function MutationObserver() {
      return makeNoopProxy({ observe() {}, disconnect() {} });
    },
    IntersectionObserver: function IntersectionObserver() {
      return makeNoopProxy({ observe() {}, disconnect() {} });
    },
    EventSource: function EventSource() {},
    WebSocket: function WebSocket() {},
    FileReader: function FileReader() {},
    TextEncoder,
  };

  windowObj.window = windowObj;
  windowObj.self = windowObj;
  windowObj.globalThis = windowObj;
  windowObj.parent = windowObj;
  return windowObj;
}

function runScript(code, ctx, label) {
  if (!code) {
    return;
  }
  vm.runInContext(code, ctx, { timeout: 5000, filename: label });
}

function main() {
  const input = readInput();
  const tdcCode = fs.readFileSync(input.tdcCodePath, 'utf8');
  const ftCode = input.ftCodePath && fs.existsSync(input.ftCodePath) ? fs.readFileSync(input.ftCodePath, 'utf8') : '';
  const windowObj = buildWindow(input);
  const ctx = vm.createContext(windowObj);

  runScript(tdcCode, ctx, 'tdc.js');
  runScript(ftCode, ctx, 'ft.js');

  const tdc = windowObj.TDC;
  if (!tdc || typeof tdc.getData !== 'function' || typeof tdc.getInfo !== 'function') {
    throw new Error('tdc_not_ready');
  }

  if (typeof tdc.setData === 'function') {
    tdc.setData('refreshcnt', 0);
    if (input.setData && typeof input.setData === 'object') {
      tdc.setData(input.setData);
    }
  }

  const collectRaw = tdc.getData(true) || '';
  const collect = decodeURIComponent(collectRaw);
  const info = tdc.getInfo() || {};
  const result = {
    ok: true,
    collectRaw,
    collect,
    tlg: collect.length,
    eks: info.info || '',
    tokenid: info.tokenid || '',
    info,
  };
  process.stdout.write(JSON.stringify(result));
}

try {
  main();
} catch (error) {
  process.stderr.write((error && error.stack) || String(error));
  process.exit(1);
}
