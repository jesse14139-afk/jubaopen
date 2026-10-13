"use strict";
/*
 * JubaOpen Threads page probe 210.3.0
 *
 * 运行环境：MAIN world
 * 页面范围：https://www.threads.com/messages/*
 *
 * 该探针只把经过清洗的快照放入 DOM 节点，不直接访问扩展 API。
 * 无法确定身份或消息方向时，输出只读状态，不伪造数据。
 */
(() => {
  const NODE_ID = "jubaopen-threads-page-snapshot-v1";
  const VERSION = 1;
  const MAX_MESSAGES = 500;

  if (window.__jubaThreadsProbe210300) return;
  window.__jubaThreadsProbe210300 = true;

  const state = {
    sequence: 0,
    generation: 1,
    route: "",
    threadId: "",
    observer: null,
    timer: 0,
    seenRoute: "",
    lastError: "",
    scans: 0
  };

  const clean = (value, max = 65536) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .replace(
        /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF\uFFFC]/g,
        ""
      )
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);

  const visible = element => {
    try {
      if (!element || !element.isConnected) return false;
      if (element.getAttribute?.("aria-hidden") === "true") {
        return false;
      }
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return (
        rect.width > 1 &&
        rect.height > 1 &&
        rect.bottom > 0 &&
        rect.right > 0 &&
        rect.top < innerHeight &&
        rect.left < innerWidth &&
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        Number(style.opacity || 1) > 0
      );
    } catch (_) {
      return false;
    }
  };

  const isThreads = () =>
    /^(?:www\.)?threads\.com$/i.test(location.hostname) &&
    location.pathname.startsWith("/messages");

  const route = () =>
    clean(
      location.pathname + location.search + location.hash,
      2048
    );

  const threadId = () => {
    const match = location.pathname.match(
      /^\/messages\/t\/([^/?#]+)/
    );
    if (!match) return "";
    try {
      return clean(decodeURIComponent(match[1]), 256);
    } catch (_) {
      return clean(match[1], 256);
    }
  };

  const username = value => {
    const result = clean(value, 100)
      .replace(/^@/, "")
      .replace(/^\/+|\/+$/g, "")
      .toLowerCase();

    const blocked = new Set([
      "messages",
      "activity",
      "search",
      "settings",
      "privacy",
      "accounts",
      "login",
      "signup"
    ]);

    return (
      /^[a-z0-9._]{1,64}$/.test(result) &&
      !blocked.has(result)
    ) ? result : "";
  };

  const profileUsername = href => {
    try {
      const url = new URL(href, location.href);
      if (!/^(?:www\.)?threads\.com$/i.test(url.hostname)) {
        return "";
      }
      const part = url.pathname.split("/").filter(Boolean)[0] || "";
      return username(part);
    } catch (_) {
      return "";
    }
  };

  function hash(value) {
    let h1 = 0x811c9dc5;
    let h2 = 0x9e3779b9;
    const text = String(value);

    for (let index = 0; index < text.length; index += 1) {
      const code = text.charCodeAt(index);
      h1 ^= code;
      h1 = Math.imul(h1, 0x01000193);
      h2 ^= code + index;
      h2 = Math.imul(h2, 0x85ebca6b);
    }

    return (
      (h1 >>> 0).toString(16).padStart(8, "0") +
      (h2 >>> 0).toString(16).padStart(8, "0")
    );
  }

  function findComposer() {
    const selectors = [
      '[role="textbox"][contenteditable="true"][data-lexical-editor]',
      '[role="textbox"][contenteditable="true"]'
    ];

    const candidates = selectors.flatMap(
      selector => [...document.querySelectorAll(selector)]
    ).filter(visible);

    candidates.sort((left, right) => {
      const a = left.getBoundingClientRect();
      const b = right.getBoundingClientRect();
      return b.top - a.top;
    });

    return candidates[0] || null;
  }

  function scoreGrid(element) {
    if (!visible(element)) return -10000;

    const rect = element.getBoundingClientRect();
    let score = 0;

    if (element.getAttribute("role") === "grid") score += 30;
    if (rect.height > innerHeight * 0.30) score += 15;
    if (rect.width > innerWidth * 0.25) score += 10;
    if (element.querySelector("time")) score += 20;

    score += Math.min(
      20,
      element.querySelectorAll('[role="gridcell"]').length
    );

    const composer = findComposer();
    if (composer) {
      const composerRect = composer.getBoundingClientRect();
      if (rect.bottom <= composerRect.top + 100) score += 10;
    }

    return score;
  }

  function findGrid() {
    const grids = [
      ...document.querySelectorAll('[role="grid"]')
    ];

    grids.sort((left, right) =>
      scoreGrid(right) - scoreGrid(left)
    );

    return grids.length && scoreGrid(grids[0]) > 0
      ? grids[0]
      : null;
  }

  function participantCandidates(grid) {
    if (!grid) return [];

    const result = new Map();

    grid.querySelectorAll('a[href]').forEach(anchor => {
      const name = profileUsername(anchor.href);
      if (!name || !visible(anchor)) return;

      const item = result.get(name) || {
        identityType: "threads_username",
        identityValue: name,
        displayName: "",
        profileUrl: "",
        avatarUrl: "",
        confidence: "medium"
      };

      item.profileUrl = clean(anchor.href, 2048);

      const image = anchor.querySelector("img");
      if (image) {
        item.avatarUrl = clean(
          image.currentSrc || image.src || "",
          4096
        );
        item.displayName = clean(
          image.alt || anchor.textContent || "",
          200
        );
      } else {
        item.displayName = clean(anchor.textContent || "", 200);
      }

      result.set(name, item);
    });

    return [...result.values()].slice(0, 20);
  }

  function findMessageNodes(grid) {
    if (!grid) return [];

    let nodes = [
      ...grid.querySelectorAll('[role="gridcell"]')
    ].filter(visible);

    if (!nodes.length) {
      nodes = [
        ...grid.querySelectorAll("time[datetime], time")
      ].map(time =>
        time.closest('[role="gridcell"]') ||
        time.parentElement?.parentElement ||
        time.parentElement
      ).filter(Boolean).filter(visible);
    }

    return [...new Set(nodes)].slice(-MAX_MESSAGES);
  }

  function directionOf(node, grid) {
    try {
      const nodeRect = node.getBoundingClientRect();
      const gridRect = grid.getBoundingClientRect();
      const center = nodeRect.left + nodeRect.width / 2;
      const relative = (
        center - gridRect.left
      ) / Math.max(gridRect.width, 1);

      if (relative >= 0.62) return "outbound";
      if (relative <= 0.48) return "inbound";
    } catch (_) {}

    return "unknown";
  }

  function messageText(node) {
    const clone = node.cloneNode(true);
    clone.querySelectorAll(
      "time,button,svg,script,style,[contenteditable='true']"
    ).forEach(element => element.remove());

    return clean(
      clone.innerText || clone.textContent || "",
      65536
    );
  }

  function mediaOf(node) {
    const result = [];

    node.querySelectorAll("img,video,a[href]").forEach(element => {
      let type = "";
      let url = "";

      if (element.tagName === "IMG") {
        type = "image";
        url = element.currentSrc || element.src || "";
      } else if (element.tagName === "VIDEO") {
        type = "video";
        url = element.currentSrc || element.src || "";
      } else if (element.tagName === "A") {
        type = "link";
        url = element.href || "";
      }

      url = clean(url, 4096);
      if (!url || /^data:/i.test(url)) return;

      result.push({ type, url });
    });

    const unique = new Map();
    result.forEach(item => {
      unique.set(item.type + "|" + item.url, item);
    });

    return [...unique.values()].slice(0, 20);
  }

  function messages(grid, tid) {
    return findMessageNodes(grid).map((node, index) => {
      const time = node.querySelector("time[datetime], time");
      const datetime = clean(
        time?.getAttribute("datetime") ||
        time?.dateTime ||
        time?.textContent ||
        "",
        128
      );

      const timestamp = Date.parse(datetime);
      const occurredAt = Number.isFinite(timestamp)
        ? timestamp
        : null;

      const text = messageText(node);
      const media = mediaOf(node);
      const direction = directionOf(node, grid);

      if (!text && !media.length) return null;

      const contentType = media.length
        ? (text ? "mixed" : media[0].type)
        : "text";

      const signature = [
        tid,
        direction,
        datetime,
        text,
        media.map(item => item.url).join("|"),
        index
      ].join("\n");

      return {
        externalMessageId: "threads-dom:" + hash(signature),
        clientEventId: "threads-dom:" + hash(signature),
        direction,
        senderType:
          direction === "outbound" ? "agent" :
          direction === "inbound" ? "contact" :
          "system",
        contentType,
        text: text || null,
        ...(occurredAt ? { occurredAt } : {}),
        metadata: {
          observedAt: Date.now(),
          timestampResolved: Boolean(occurredAt),
          timestampConfidence:
            occurredAt ? "high" : "low",
          captureMode: "threads-dom",
          media,
          directionConfidence:
            direction === "unknown" ? "low" : "medium",
          messageContract: "juba-channel-message-v1",
          sourcePlatform: "threads"
        }
      };
    }).filter(Boolean);
  }

  function publish(reason) {
    if (!isThreads()) return;

    try {
      const currentRoute = route();
      const tid = threadId();

      if (state.seenRoute && state.seenRoute !== currentRoute) {
        state.generation += 1;
      }

      state.seenRoute = currentRoute;
      state.route = currentRoute;
      state.threadId = tid;
      state.sequence += 1;
      state.scans += 1;

      const grid = findGrid();
      const composer = findComposer();
      const participants = participantCandidates(grid);
      const extractedMessages = messages(grid, tid);

      /*
       * Threads 当前页面探测无法可靠取得当前登录账号身份。
       * ownIdentity 明确保持 null，避免把对方身份误认为账号身份。
       */
      const selectedParticipant =
        participants.length === 1 ? participants[0] : null;

      const writable = Boolean(
        tid &&
        grid &&
        composer &&
        selectedParticipant &&
        extractedMessages.every(
          message => message.direction !== "unknown"
        )
      );

      const snapshot = {
        v: VERSION,
        at: Date.now(),
        platform: "threads",
        route: currentRoute,
        sequence: state.sequence,
        generation: state.generation,
        ownIdentity: null,
        conversation: tid ? {
          threadId: tid,
          externalConversationId: "threads:" + tid,
          writable: false,
          readonly: true,
          confidence:
            selectedParticipant ? "medium" : "low",
          readonlyReason:
            "Threads 当前登录账号身份无法从稳定公开 DOM 可靠核验；"
            + "为避免身份误绑定，本版本保持只读采集诊断",
          identity: selectedParticipant ? {
            ...selectedParticipant,
            role: "IS_PARTICIPANT",
            stable: true
          } : null,
          participants
        } : null,
        messages: extractedMessages,
        diagnostics: {
          reason,
          scans: state.scans,
          gridFound: Boolean(grid),
          composerFound: Boolean(composer),
          participantCount: participants.length,
          messageCount: extractedMessages.length,
          writableCandidate: writable,
          identityError:
            "THREADS_OWNER_IDENTITY_UNVERIFIED",
          lastError: state.lastError
        }
      };

      let node = document.getElementById(NODE_ID);
      if (!node) {
        node = document.createElement("meta");
        node.id = NODE_ID;
        node.setAttribute("name", NODE_ID);
        (
          document.head ||
          document.documentElement
        ).appendChild(node);
      }

      node.setAttribute(
        "content",
        JSON.stringify(snapshot)
      );
    } catch (error) {
      state.lastError = clean(
        error?.message || error || "UNKNOWN_ERROR",
        300
      );
    }
  }

  function schedule(reason) {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => publish(reason), 250);
  }

  function hookHistory() {
    if (window.__jubaThreadsHistoryHook210300) return;
    window.__jubaThreadsHistoryHook210300 = true;

    ["pushState", "replaceState"].forEach(name => {
      const original = history[name];
      if (typeof original !== "function") return;

      history[name] = function (...args) {
        const result = original.apply(this, args);
        setTimeout(() => schedule(name), 0);
        return result;
      };
    });

    addEventListener(
      "popstate",
      () => schedule("popstate")
    );
  }

  function start() {
    hookHistory();

    state.observer = new MutationObserver(
      () => schedule("mutation")
    );

    state.observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true
    });

    publish("start");
    setInterval(() => publish("interval"), 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  } else {
    start();
  }
})();

