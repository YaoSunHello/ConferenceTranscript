const url = process.argv[2];
const outText = process.argv[3];
const outHtml = process.argv[4];
const port = process.argv[5] || "9224";

if (!url || !outText || !outHtml) {
  console.error("Usage: node extract_chatgpt_share.mjs <url> <out-text> <out-html> [port]");
  process.exit(2);
}

const fs = await import("node:fs");
const http = await import("node:http");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function getJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ hostname: "127.0.0.1", port, path }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => (body += chunk));
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode > 299) {
          reject(new Error(`HTTP ${response.statusCode}: ${body.slice(0, 200)}`));
        } else {
          resolve(JSON.parse(body));
        }
      });
    }).on("error", reject);
  });
}

async function waitForBrowser() {
  for (let i = 0; i < 80; i++) {
    try {
      return await getJson("/json/version");
    } catch {}
    await sleep(500);
  }
  throw new Error("Chrome DevTools endpoint did not become available.");
}

function connect(webSocketDebuggerUrl) {
  const socket = new WebSocket(webSocketDebuggerUrl);
  let nextId = 1;
  const pending = new Map();

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result || {});
    }
  });

  return new Promise((resolve, reject) => {
    socket.addEventListener("open", () => {
      resolve({
        send(method, params = {}) {
          const id = nextId++;
          socket.send(JSON.stringify({ id, method, params }));
          return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
        },
        close() {
          socket.close();
        },
      });
    });
    socket.addEventListener("error", reject);
  });
}

async function waitForReady(cdp) {
  for (let i = 0; i < 100; i++) {
    const result = await cdp.send("Runtime.evaluate", {
      expression: "document.readyState",
      returnByValue: true,
    });
    if (result.result?.value === "complete") return;
    await sleep(500);
  }
}

async function dismissCookies(cdp) {
  const result = await cdp.send("Runtime.evaluate", {
    expression: `
      (() => {
        const buttons = [...document.querySelectorAll('button')];
        const target = buttons.find((button) => /reject non-essential/i.test(button.innerText || ""))
          || buttons.find((button) => /accept all/i.test(button.innerText || ""))
          || buttons.find((button) => /close/i.test(button.ariaLabel || button.innerText || ""));
        if (target) {
          target.click();
          return target.innerText || target.ariaLabel || "clicked";
        }
        return "";
      })()
    `,
    returnByValue: true,
  });
  await sleep(1500);
  return result.result?.value || "";
}

async function scrollToLoad(cdp) {
  for (let pass = 0; pass < 5; pass++) {
    await cdp.send("Runtime.evaluate", {
      expression: `
        new Promise(async (resolve) => {
          const step = Math.max(600, Math.floor(window.innerHeight * 0.8));
          for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
            window.scrollTo(0, y);
            await new Promise((r) => setTimeout(r, 120));
          }
          window.scrollTo(0, 0);
          setTimeout(resolve, 500);
        })
      `,
      awaitPromise: true,
    });
    await sleep(750);
  }
}

const browser = await waitForBrowser();
const browserCdp = await connect(browser.webSocketDebuggerUrl);
const created = await browserCdp.send("Target.createTarget", { url });
browserCdp.close();

await sleep(1000);
const targets = await getJson("/json/list");
const target = targets.find((candidate) => candidate.id === created.targetId);
if (!target?.webSocketDebuggerUrl) throw new Error("Could not find the created page target.");

const cdp = await connect(target.webSocketDebuggerUrl);
try {
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await waitForReady(cdp);
  await sleep(6000);
  const cookieAction = await dismissCookies(cdp);
  await scrollToLoad(cdp);
  const extracted = await cdp.send("Runtime.evaluate", {
    expression: `
      (() => {
        const clone = document.body.cloneNode(true);
        for (const element of [...clone.querySelectorAll('script, style, svg')]) element.remove();
        return {
          title: document.title,
          url: location.href,
          text: clone.innerText,
          html: document.documentElement.outerHTML
        };
      })()
    `,
    returnByValue: true,
  });

  const value = extracted.result?.value || {};
  fs.writeFileSync(outText, value.text || "", "utf8");
  fs.writeFileSync(outHtml, value.html || "", "utf8");
  console.log(JSON.stringify({
    title: value.title,
    url: value.url,
    cookieAction,
    textLength: (value.text || "").length,
    htmlLength: (value.html || "").length,
  }));
} finally {
  cdp.close();
}
