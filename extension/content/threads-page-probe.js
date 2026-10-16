"use strict";
/*
 * JubaOpen Threads page probe 210.3.4
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

  if (window.__jubaThreadsProbe210303) return;
  window.__jubaThreadsProbe210303 = true;

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

  /*
   * JUBAOPEN_THREADS_MESSAGE_GRIDCELL_VISIBILITY_FIX_210_3_5_4
   *
   * Threads 当前消息 DOM 中，role=gridcell 可能是一个没有自身
   * 布局矩形的语义包装层，例如 display:contents 或零尺寸包装节点。
   *
   * 原实现只检查 gridcell 自身的 getBoundingClientRect()，导致：
   *
   *   gridFound = true
   *   gridCellCount > 0
   *   visibleGridCellCount = 0
   *   messageCount = 0
   *
   * 实际消息文本后代仍然可见。因此：
   *
   *   1. 普通节点继续使用原有严格判定。
   *   2. 只有 role=gridcell 可以通过可见后代获得可见状态。
   *   3. 不对整个页面宽泛扫描，避免将导航、联系人名称、
   *      输入框草稿和菜单内容误采集为聊天消息。
   */

  const ownVisualState = element => {
    try {
      if (!element || !element.isConnected) {
        return false;
      }

      if (
        element.getAttribute?.("aria-hidden") === "true"
      ) {
        return false;
      }

      const style = getComputedStyle(element);

      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        Number(style.opacity || 1) <= 0
      ) {
        return false;
      }

      const rect = element.getBoundingClientRect();

      return (
        rect.width > 1 &&
        rect.height > 1 &&
        rect.bottom > 0 &&
        rect.right > 0 &&
        rect.top < innerHeight &&
        rect.left < innerWidth
      );
    } catch (_) {
      return false;
    }
  };

  const visibleGridCellDescendant = gridCell => {
    try {
      if (
        !gridCell ||
        !gridCell.isConnected ||
        gridCell.getAttribute?.("aria-hidden") === "true"
      ) {
        return null;
      }

      /*
       * 优先使用 Threads 消息正文常见的 dir=auto 节点。
       * 媒体节点作为非文本消息的补充候选。
       *
       * textbox/contenteditable 明确排除，防止采集输入框草稿。
       */
      const candidates = gridCell.querySelectorAll(
        [
          "span[dir='auto']",
          "div[dir='auto']",
          "img",
          "video",
          "audio"
        ].join(",")
      );

      for (const candidate of candidates) {
        if (
          candidate.matches?.(
            "[contenteditable='true'],[role='textbox']"
          ) ||
          candidate.closest?.(
            "[contenteditable='true'],[role='textbox']"
          )
        ) {
          continue;
        }

        if (
          candidate.closest?.(
            "[role='menu'],[role='dialog'],nav,header"
          )
        ) {
          continue;
        }

        if (ownVisualState(candidate)) {
          return candidate;
        }
      }

      return null;
    } catch (_) {
      return null;
    }
  };

  const visible = element => {
    try {
      if (ownVisualState(element)) {
        return true;
      }

      /*
       * 仅为零尺寸 gridcell 启用后代可见性兼容。
       * 普通元素仍然必须具有自己的有效矩形。
       */
      if (
        element?.getAttribute?.("role") === "gridcell"
      ) {
        return Boolean(
          visibleGridCellDescendant(element)
        );
      }

      return false;
    } catch (_) {
      return false;
    }
  };

  const isThreads = () =>
    /^(?:www\.)?threads\.com$/i.test(
      location.hostname
    );

  const isMessageRoute = () =>
    isThreads() &&
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


  /*
   * JUBAOPEN_THREADS_OWNER_IDENTITY_FIX_210_3_1
   *
   * 本人身份只能来自消息区域之外的显式账号菜单或个人资料入口。
   * 消息参与者、动态作者、搜索结果不能单独作为本人身份。
   */
  const OWNER_STORAGE_KEY =
    "jubaopen.threads.ownerIdentity.v210301";
  const OWNER_PENDING_KEY =
    "jubaopen.threads.pendingOwner.v210301";

  const OWNER_MAX_AGE = 30 * 60 * 1000;
  const OWNER_PENDING_MAX_AGE = 60 * 1000;
  const OWNER_STABLE_MS = 500;
  const OWNER_REQUIRED_HITS = 2;

  const ownerState = {
    value: "",
    displayName: "",
    profileUrl: "",
    avatarUrl: "",
    source: "",
    score: 0,
    hits: 0,
    firstSeenAt: 0,
    lastSeenAt: 0,
    accepted: null,
    conflict: false,
    clickHooked: false
  };

  function safeSessionGet(key) {
    try {
      const raw = sessionStorage.getItem(key);
      if (!raw) return null;

      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object"
        ? parsed
        : null;
    } catch (_) {
      return null;
    }
  }

  function safeSessionSet(key, value) {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch (_) {}
  }

  function safeSessionRemove(key) {
    try {
      sessionStorage.removeItem(key);
    } catch (_) {}
  }

  function profileData(anchor) {
    if (!anchor || anchor.tagName !== "A") return null;

    let url;

    try {
      url = new URL(anchor.href, location.href);
    } catch (_) {
      return null;
    }

    if (!/^(?:www\.)?threads\.com$/i.test(url.hostname)) {
      return null;
    }

    const firstPart =
      url.pathname.split("/").filter(Boolean)[0] || "";

    const identityValue = username(firstPart);
    if (!identityValue) return null;

    const image = anchor.querySelector("img");

    return {
      identityType: "threads_username",
      identityValue,
      displayName: clean(
        image?.alt || anchor.textContent || "",
        200
      ),
      profileUrl: clean(url.href, 2048),
      avatarUrl: clean(
        image?.currentSrc || image?.src || "",
        4096
      )
    };
  }

  function semanticText(element) {
    const parts = [];
    let current = element;

    for (
      let depth = 0;
      current && depth < 5;
      depth += 1
    ) {
      parts.push(
        current.getAttribute?.("aria-label") || "",
        current.getAttribute?.("title") || "",
        current.getAttribute?.("data-testid") || "",
        current.getAttribute?.("role") || "",
        current.textContent || ""
      );

      current = current.parentElement;
    }

    return clean(parts.join(" "), 1600).toLowerCase();
  }

  function ownerSemanticScore(anchor) {
    if (!anchor || !visible(anchor)) return -10000;

    /*
     * 消息区中的资料链接属于会话参与者，不能作为本人证据。
     */
    if (
      anchor.closest('[role="grid"]') ||
      anchor.closest('[role="gridcell"]')
    ) {
      return -10000;
    }

    /*
     * 动态、帖子、搜索结果中的作者也不能作为本人证据。
     */
    if (
      anchor.closest(
        "article,[role='article']," +
        "[role='feed'],[role='listbox']"
      )
    ) {
      return -10000;
    }

    const semantic = semanticText(anchor);
    let score = 0;

    const strongPatterns = [
      /\bmy profile\b/i,
      /\bview profile\b/i,
      /\baccount menu\b/i,
      /\bprofile menu\b/i,
      /\baccount center\b/i,
      /我的主页/,
      /我的个人主页/,
      /个人资料/,
      /個人資料/,
      /账号菜单/,
      /帳號選單/,
      /プロフィール/,
      /アカウント/,
      /내 프로필/,
      /계정/
    ];

    const weakPatterns = [
      /\bprofile\b/i,
      /\baccount\b/i,
      /\bsettings\b/i,
      /主页/,
      /帳號/,
      /账号/,
      /设置/,
      /設定/
    ];

    if (
      strongPatterns.some(pattern => pattern.test(semantic))
    ) {
      score += 80;
    } else if (
      weakPatterns.some(pattern => pattern.test(semantic))
    ) {
      score += 30;
    }

    if (anchor.closest("[role='menu']")) score += 35;
    if (anchor.closest("[role='menuitem']")) score += 30;
    if (anchor.closest("nav,[role='navigation']")) score += 25;
    if (anchor.closest("header")) score += 15;
    if (anchor.querySelector("img")) score += 8;

    return score;
  }

  function explicitOwnerCandidates() {
    const candidates = [];

    document.querySelectorAll("a[href]").forEach(anchor => {
      const identity = profileData(anchor);
      if (!identity) return;

      const score = ownerSemanticScore(anchor);
      if (score < 55) return;

      candidates.push({
        ...identity,
        score,
        source: anchor.closest("[role='menu']")
          ? "threads-account-menu"
          : "threads-profile-navigation"
      });
    });

    candidates.sort(
      (left, right) => right.score - left.score
    );

    return candidates;
  }

  function clearAcceptedOwner(reason) {
    ownerState.accepted = null;
    ownerState.value = "";
    ownerState.displayName = "";
    ownerState.profileUrl = "";
    ownerState.avatarUrl = "";
    ownerState.source = "";
    ownerState.score = 0;
    ownerState.hits = 0;
    ownerState.firstSeenAt = 0;
    ownerState.lastSeenAt = 0;
    ownerState.conflict = true;

    safeSessionRemove(OWNER_STORAGE_KEY);

    state.lastError = clean(
      reason || "THREADS_OWNER_IDENTITY_CONFLICT",
      300
    );
  }

  function acceptOwner(candidate, sourceOverride = "") {
    const value = username(candidate?.identityValue);
    if (!value) return null;

    const accepted = {
      identityType: "threads_username",
      identityValue: value,
      displayName: clean(candidate.displayName, 200),
      profileUrl: clean(candidate.profileUrl, 2048),
      avatarUrl: clean(candidate.avatarUrl, 4096),
      role: "IS_OWNER",
      stable: true,
      confidence: "high",
      source: clean(
        sourceOverride ||
        candidate.source ||
        "threads-owner-detector",
        80
      ),
      verifiedAt: Date.now()
    };

    ownerState.accepted = accepted;
    ownerState.value = value;
    ownerState.conflict = false;

    safeSessionSet(OWNER_STORAGE_KEY, accepted);

    return { ...accepted };
  }

  function observeOwnerCandidate(candidate) {
    const value = username(candidate?.identityValue);
    if (!value) return null;

    const now = Date.now();

    if (
      ownerState.accepted &&
      ownerState.accepted.identityValue !== value
    ) {
      clearAcceptedOwner(
        "THREADS_OWNER_IDENTITY_CHANGED"
      );
    }

    if (ownerState.value !== value) {
      ownerState.value = value;
      ownerState.displayName =
        clean(candidate.displayName, 200);
      ownerState.profileUrl =
        clean(candidate.profileUrl, 2048);
      ownerState.avatarUrl =
        clean(candidate.avatarUrl, 4096);
      ownerState.source =
        clean(candidate.source, 80);
      ownerState.score = Number(candidate.score) || 0;
      ownerState.hits = 1;
      ownerState.firstSeenAt = now;
      ownerState.lastSeenAt = now;
      ownerState.conflict = false;
      return null;
    }

    ownerState.hits += 1;
    ownerState.lastSeenAt = now;
    ownerState.score = Math.max(
      ownerState.score,
      Number(candidate.score) || 0
    );

    if (
      ownerState.hits >= OWNER_REQUIRED_HITS &&
      now - ownerState.firstSeenAt >= OWNER_STABLE_MS
    ) {
      return acceptOwner({
        ...candidate,
        identityValue: value,
        displayName:
          candidate.displayName ||
          ownerState.displayName,
        profileUrl:
          candidate.profileUrl ||
          ownerState.profileUrl,
        avatarUrl:
          candidate.avatarUrl ||
          ownerState.avatarUrl,
        source:
          candidate.source ||
          ownerState.source
      });
    }

    return null;
  }

  function loadStoredOwner() {
    const stored = safeSessionGet(OWNER_STORAGE_KEY);
    if (!stored) return null;

    const verifiedAt = Number(stored.verifiedAt);

    if (
      !Number.isFinite(verifiedAt) ||
      Date.now() - verifiedAt > OWNER_MAX_AGE ||
      verifiedAt - Date.now() > 5000
    ) {
      safeSessionRemove(OWNER_STORAGE_KEY);
      return null;
    }

    const value = username(stored.identityValue);

    if (!value) {
      safeSessionRemove(OWNER_STORAGE_KEY);
      return null;
    }

    return {
      identityType: "threads_username",
      identityValue: value,
      displayName: clean(stored.displayName, 200),
      profileUrl: clean(stored.profileUrl, 2048),
      avatarUrl: clean(stored.avatarUrl, 4096),
      role: "IS_OWNER",
      stable: true,
      confidence: "high",
      source: clean(
        stored.source || "threads-session-owner",
        80
      ),
      verifiedAt
    };
  }

  function pendingProfileCandidate() {
    const pending = safeSessionGet(OWNER_PENDING_KEY);
    if (!pending) return null;

    const recordedAt = Number(pending.at);

    if (
      !Number.isFinite(recordedAt) ||
      Date.now() - recordedAt > OWNER_PENDING_MAX_AGE ||
      recordedAt - Date.now() > 5000
    ) {
      safeSessionRemove(OWNER_PENDING_KEY);
      return null;
    }

    const current = username(
      location.pathname.split("/").filter(Boolean)[0] || ""
    );

    if (!current || current !== pending.identityValue) {
      return null;
    }

    safeSessionRemove(OWNER_PENDING_KEY);

    return {
      identityType: "threads_username",
      identityValue: current,
      displayName: clean(pending.displayName, 200),
      profileUrl: clean(location.href, 2048),
      avatarUrl: clean(pending.avatarUrl, 4096),
      score: 100,
      source: "threads-explicit-profile-click"
    };
  }

  function hookOwnerClicks() {
    if (ownerState.clickHooked) return;

    ownerState.clickHooked = true;

    document.addEventListener(
      "click",
      event => {
        const anchor = event.target?.closest?.("a[href]");
        if (!anchor) return;

        const identity = profileData(anchor);
        if (!identity) return;

        const score = ownerSemanticScore(anchor);
        if (score < 55) return;

        const pending = {
          ...identity,
          score: Math.max(score, 100),
          source: "threads-explicit-profile-click",
          at: Date.now()
        };

        safeSessionSet(OWNER_PENDING_KEY, pending);

        ownerState.value = identity.identityValue;
        ownerState.hits = OWNER_REQUIRED_HITS;
        ownerState.firstSeenAt =
          Date.now() - OWNER_STABLE_MS;
        ownerState.lastSeenAt = Date.now();

        acceptOwner(
          pending,
          "threads-explicit-profile-click"
        );
      },
      true
    );
  }

  function detectOwnIdentity() {
    hookOwnerClicks();

    /*
     * JUBAOPEN_MANUAL_OWNER_PRIORITY_210_3_3
     *
     * 用户明确确认的手动身份优先于不稳定 DOM 自动候选。
     */
    const manualOwner = loadStoredOwner();

    if (
      manualOwner &&
      manualOwner.source ===
        "threads-user-confirmed-manual"
    ) {
      ownerState.accepted = manualOwner;
      ownerState.value =
        manualOwner.identityValue;
      ownerState.conflict = false;

      return { ...manualOwner };
    }


    const pending = pendingProfileCandidate();

    if (pending) {
      return acceptOwner(
        pending,
        "threads-explicit-profile-click"
      );
    }

    const candidates = explicitOwnerCandidates();

    if (candidates.length) {
      const top = candidates[0];

      const conflict = candidates.some(candidate =>
        candidate.identityValue !== top.identityValue &&
        candidate.score >= top.score - 5
      );

      if (conflict) {
        clearAcceptedOwner(
          "THREADS_OWNER_MULTIPLE_HIGH_CONFIDENCE_CANDIDATES"
        );
        return null;
      }

      const observed = observeOwnerCandidate(top);
      if (observed) return observed;
    }

    if (ownerState.accepted) {
      return { ...ownerState.accepted };
    }

    const stored = loadStoredOwner();

    if (stored) {
      ownerState.accepted = stored;
      ownerState.value = stored.identityValue;
      ownerState.conflict = false;
      return { ...stored };
    }

    return null;
  }

  function ownerDiagnostics(owner) {
    return {
      ownerFound: Boolean(owner),
      ownerIdentityType:
        clean(owner?.identityType, 64),
      ownerIdentityValue:
        clean(owner?.identityValue, 100),
      ownerConfidence:
        clean(owner?.confidence, 20),
      ownerSource:
        clean(owner?.source, 80),
      ownerCandidateHits: ownerState.hits,
      ownerCandidateScore: ownerState.score,
      ownerConflict: ownerState.conflict
    };
  }

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
      const owner = detectOwnIdentity();
      const ownerValue = clean(
        owner?.identityValue,
        100
      ).toLowerCase();
      const counterpartParticipants =
        participants.filter(participant =>
          clean(
            participant.identityValue,
            100
          ).toLowerCase() !== ownerValue
        );
      const extractedMessages = messages(grid, tid);

      /*
       * Threads 当前页面探测无法可靠取得当前登录账号身份。
       * ownIdentity 明确保持 null，避免把对方身份误认为账号身份。
       */
      const selectedParticipant =
        counterpartParticipants.length === 1
          ? counterpartParticipants[0]
          : null;

      const writable = Boolean(
        tid &&
        grid &&
        composer &&
        owner &&
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
        ownIdentity: owner ? { ...owner } : null,
        conversation: tid ? {
          threadId: tid,
          externalConversationId: "threads:" + tid,
          writable,
          readonly: !writable,
          confidence:
            selectedParticipant ? "medium" : "low",
          readonlyReason: writable
            ? ""
            : (!owner
              ? "尚未取得 Threads 本人稳定身份，请点击页面右上角“手动设置本人身份”"
              : (!selectedParticipant
                ? "尚未取得唯一的 Threads 会话参与者身份"
                : "Threads 消息方向仍在稳定核验")),
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
          counterpartParticipantCount: counterpartParticipants.length,
          ...ownerDiagnostics(owner),
          messageCount: extractedMessages.length,
          writableCandidate: writable,
          identityError: !owner
            ? "THREADS_OWNER_IDENTITY_UNVERIFIED"
            : (!selectedParticipant
              ? "THREADS_PARTICIPANT_UNVERIFIED"
              : (writable
                ? ""
                : "THREADS_DIRECTION_UNVERIFIED")),
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

/*
 * JUBAOPEN_THREADS_GRID_FALLBACK_SCANNER_210_3_5_5
 *
 * Threads 2026 DOM compatibility:
 *
 *   role=grid is visible
 *   role=gridcell nodes do not contain message text
 *   visible dir=auto message nodes are direct/indirect Grid descendants
 *
 * This scanner does not replace the primary scanner. It augments the
 * snapshot only when the primary scanner has produced zero messages.
 */
(() => {
  "use strict";

  const PATCH_VERSION = "210.3.5.5";
  const NODE_ID = "jubaopen-threads-page-snapshot-v1";
  const PATCH_FLAG = "threadsGridFallbackV21030505";
  const MAX_MESSAGES = 500;

  if (window.__jubaThreadsGridFallback21030505) {
    return;
  }

  window.__jubaThreadsGridFallback21030505 = true;

  let applying = false;
  let scheduled = 0;
  let lastAppliedKey = "";

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

  const visual = element => {
    try {
      if (!element || !element.isConnected) {
        return false;
      }

      if (
        element.getAttribute?.("aria-hidden") === "true"
      ) {
        return false;
      }

      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();

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

  const intersects = (left, right) =>
    left.left < right.right &&
    left.right > right.left &&
    left.top < right.bottom &&
    left.bottom > right.top;

  const area = rect =>
    Math.max(0, rect.width) *
    Math.max(0, rect.height);

  const hash = value => {
    const input = String(value ?? "");
    let result = 2166136261;

    for (let index = 0; index < input.length; index += 1) {
      result ^= input.charCodeAt(index);
      result = Math.imul(result, 16777619);
    }

    return (result >>> 0)
      .toString(16)
      .padStart(8, "0");
  };

  const currentThreadId = snapshot => {
    const fromSnapshot = clean(
      snapshot?.threadId ||
      snapshot?.conversationId ||
      snapshot?.conversation?.threadId ||
      snapshot?.conversation?.id ||
      "",
      256
    );

    if (fromSnapshot) {
      return fromSnapshot;
    }

    const match = location.pathname.match(
      /^\/messages\/t\/([^/?#]+)/
    );

    if (!match) {
      return "";
    }

    try {
      return clean(decodeURIComponent(match[1]), 256);
    } catch (_) {
      return clean(match[1], 256);
    }
  };

  const excluded = (node, grid) => {
    try {
      if (!node || !grid || !grid.contains(node)) {
        return true;
      }

      if (
        node.matches?.(
          [
            "[contenteditable='true']",
            "[role='textbox']",
            "textarea",
            "input",
            "button",
            "[role='button']",
            "time",
            "abbr"
          ].join(",")
        )
      ) {
        return true;
      }

      const blockedAncestor = node.closest?.(
        [
          "[contenteditable='true']",
          "[role='textbox']",
          "[role='menu']",
          "[role='menuitem']",
          "[role='dialog']",
          "[role='listbox']",
          "textarea",
          "form",
          "nav",
          "header"
        ].join(",")
      );

      if (
        blockedAncestor &&
        blockedAncestor !== grid &&
        grid.contains(blockedAncestor)
      ) {
        return true;
      }

      return false;
    } catch (_) {
      return true;
    }
  };

  const likelyStatusText = text => {
    const value = clean(text, 500).toLowerCase();

    if (!value) {
      return true;
    }

    const exact = new Set([
      "seen",
      "sent",
      "delivered",
      "sending",
      "已读",
      "已发送",
      "已送达",
      "发送中",
      "message",
      "消息"
    ]);

    if (exact.has(value)) {
      return true;
    }

    if (
      /^(?:today|yesterday|今天|昨天)$/i.test(value)
    ) {
      return true;
    }

    if (
      /^(?:\d{1,2}:\d{2})(?:\s?[ap]m)?$/i.test(value)
    ) {
      return true;
    }

    if (
      /^(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?$/i
        .test(value)
    ) {
      return true;
    }

    return false;
  };

  const chooseGrid = () => {
    const grids = Array.from(
      document.querySelectorAll('[role="grid"]')
    ).filter(visual);

    if (!grids.length) {
      return null;
    }

    const composer = Array.from(
      document.querySelectorAll(
        [
          "[contenteditable='true']",
          "[role='textbox']",
          "textarea"
        ].join(",")
      )
    ).find(visual);

    grids.sort((left, right) => {
      const leftRect = left.getBoundingClientRect();
      const rightRect = right.getBoundingClientRect();

      let leftScore = area(leftRect);
      let rightScore = area(rightRect);

      if (composer) {
        const composerRect =
          composer.getBoundingClientRect();

        const leftDistance = Math.abs(
          composerRect.left +
          composerRect.width / 2 -
          (
            leftRect.left +
            leftRect.width / 2
          )
        );

        const rightDistance = Math.abs(
          composerRect.left +
          composerRect.width / 2 -
          (
            rightRect.left +
            rightRect.width / 2
          )
        );

        leftScore -= leftDistance * 100;
        rightScore -= rightDistance * 100;
      }

      return rightScore - leftScore;
    });

    return grids[0] || null;
  };

  const leafSeeds = grid => {
    const all = Array.from(
      grid.querySelectorAll(
        "span[dir='auto'],div[dir='auto']"
      )
    ).filter(node => {
      if (!visual(node) || excluded(node, grid)) {
        return false;
      }

      const text = clean(node.textContent, 65536);

      if (!text || likelyStatusText(text)) {
        return false;
      }

      return true;
    });

    return all.filter(node => {
      const visibleTextChild = Array.from(
        node.querySelectorAll(
          "span[dir='auto'],div[dir='auto']"
        )
      ).some(child => {
        if (child === node) {
          return false;
        }

        if (!visual(child) || excluded(child, grid)) {
          return false;
        }

        return Boolean(clean(child.textContent, 65536));
      });

      return !visibleTextChild;
    });
  };

  const directionFor = (element, grid) => {
    try {
      const gridRect = grid.getBoundingClientRect();
      const rect = element.getBoundingClientRect();

      if (
        gridRect.width <= 1 ||
        rect.width <= 1 ||
        !intersects(rect, gridRect)
      ) {
        return {
          direction: "",
          relativeCenter: null
        };
      }

      const relativeCenter =
        (
          rect.left +
          rect.width / 2 -
          gridRect.left
        ) / gridRect.width;

      if (relativeCenter <= 0.44) {
        return {
          direction: "inbound",
          relativeCenter
        };
      }

      if (relativeCenter >= 0.56) {
        return {
          direction: "outbound",
          relativeCenter
        };
      }

      return {
        direction: "",
        relativeCenter
      };
    } catch (_) {
      return {
        direction: "",
        relativeCenter: null
      };
    }
  };

  const bubbleForSeed = (seed, grid, direction) => {
    const gridRect = grid.getBoundingClientRect();

    let current = seed;
    let selected = seed;

    for (let depth = 0; depth < 7; depth += 1) {
      const parent = current?.parentElement;

      if (!parent || parent === grid) {
        break;
      }

      if (!grid.contains(parent)) {
        break;
      }

      if (
        parent.matches?.(
          [
            "[role='grid']",
            "[role='dialog']",
            "[role='menu']",
            "form",
            "nav",
            "header"
          ].join(",")
        )
      ) {
        break;
      }

      const rect = parent.getBoundingClientRect();

      if (
        rect.width <= 1 ||
        rect.height <= 1 ||
        rect.width > gridRect.width * 0.78 ||
        rect.height > Math.max(500, gridRect.height * 0.65)
      ) {
        break;
      }

      const parentDirection =
        directionFor(parent, grid).direction;

      if (
        parentDirection &&
        parentDirection !== direction
      ) {
        break;
      }

      selected = parent;
      current = parent;
    }

    return selected;
  };

  const extractBubbleText = (bubble, seed, grid) => {
    const nodes = Array.from(
      bubble.querySelectorAll(
        "span[dir='auto'],div[dir='auto']"
      )
    ).filter(node => {
      if (!visual(node) || excluded(node, grid)) {
        return false;
      }

      return !Array.from(
        node.querySelectorAll(
          "span[dir='auto'],div[dir='auto']"
        )
      ).some(child => {
        if (child === node) {
          return false;
        }

        return (
          visual(child) &&
          !excluded(child, grid) &&
          Boolean(clean(child.textContent, 65536))
        );
      });
    });

    const sourceNodes = nodes.length ? nodes : [seed];
    const parts = [];
    const seen = new Set();

    for (const node of sourceNodes) {
      const text = clean(node.textContent, 65536);

      if (
        !text ||
        likelyStatusText(text) ||
        seen.has(text)
      ) {
        continue;
      }

      seen.add(text);
      parts.push(text);
    }

    return clean(parts.join("\n"), 65536);
  };

  const scanFallbackMessages = snapshot => {
    const grid = chooseGrid();

    const diagnostics = {
      gridFound: Boolean(grid),
      gridCellCount: 0,
      visibleGridCellCount: 0,
      gridTextSeedCount: 0,
      seedsInsideGridCell: 0,
      seedsOutsideGridCell: 0,
      fallbackBubbleCount: 0,
      fallbackDirectionResolvedCount: 0,
      fallbackDirectionRejectedCount: 0,
      fallbackMessageCount: 0,
      messageScannerMode: "grid-fallback"
    };

    if (!grid) {
      return {
        messages: [],
        diagnostics
      };
    }

    const cells = Array.from(
      grid.querySelectorAll('[role="gridcell"]')
    );

    diagnostics.gridCellCount = cells.length;
    diagnostics.visibleGridCellCount =
      cells.filter(visual).length;

    const seeds = leafSeeds(grid);

    diagnostics.gridTextSeedCount = seeds.length;
    diagnostics.seedsInsideGridCell =
      seeds.filter(
        seed => Boolean(seed.closest('[role="gridcell"]'))
      ).length;

    diagnostics.seedsOutsideGridCell =
      seeds.length -
      diagnostics.seedsInsideGridCell;

    const bubbleMap = new Map();

    for (const seed of seeds) {
      const resolution = directionFor(seed, grid);

      if (!resolution.direction) {
        diagnostics.fallbackDirectionRejectedCount += 1;
        continue;
      }

      diagnostics.fallbackDirectionResolvedCount += 1;

      const bubble = bubbleForSeed(
        seed,
        grid,
        resolution.direction
      );

      const existing = bubbleMap.get(bubble);

      if (existing) {
        existing.seeds.push(seed);
        continue;
      }

      bubbleMap.set(bubble, {
        bubble,
        seeds: [seed],
        direction: resolution.direction,
        relativeCenter: resolution.relativeCenter
      });
    }

    const groups = Array.from(
      bubbleMap.values()
    ).sort((left, right) => {
      const leftRect =
        left.bubble.getBoundingClientRect();

      const rightRect =
        right.bubble.getBoundingClientRect();

      if (Math.abs(leftRect.top - rightRect.top) > 2) {
        return leftRect.top - rightRect.top;
      }

      return leftRect.left - rightRect.left;
    });

    diagnostics.fallbackBubbleCount = groups.length;

    const thread = currentThreadId(snapshot);
    const capturedAt = clean(
      snapshot?.capturedAt ||
      snapshot?.generatedAt ||
      snapshot?.timestamp ||
      new Date().toISOString(),
      100
    );

    const messages = [];
    const duplicateGuard = new Set();

    groups.forEach((group, order) => {
      const seed = group.seeds[0];

      const text = extractBubbleText(
        group.bubble,
        seed,
        grid
      );

      if (!text || likelyStatusText(text)) {
        return;
      }

      const rect =
        group.bubble.getBoundingClientRect();

      const geometryKey = [
        Math.round(rect.top),
        Math.round(rect.left),
        Math.round(rect.width),
        Math.round(rect.height)
      ].join(":");

      const identityKey = [
        thread,
        group.direction,
        order,
        geometryKey,
        text
      ].join("|");

      const stableHash = hash(identityKey);

      const messageId =
        "threads-grid-fallback:" +
        clean(thread || "unknown", 256) +
        ":" +
        group.direction +
        ":" +
        stableHash;

      if (duplicateGuard.has(messageId)) {
        return;
      }

      duplicateGuard.add(messageId);

      const message = {
        id: messageId,
        messageId,
        externalId: messageId,
        externalMessageId: messageId,
        platformMessageId: messageId,

        threadId: thread,
        conversationId: thread,

        direction: group.direction,

        text,
        body: text,
        content: text,
        textContent: text,

        type: "text",
        messageType: "text",

        timestamp: capturedAt,
        occurredAt: capturedAt,
        sentAt: capturedAt,
        createdAt: capturedAt,

        order,
        source: "threads-grid-fallback-210.3.5.5",

        fallback: true,
        fallbackVersion: PATCH_VERSION,
        relativeCenter: group.relativeCenter
      };

      messages.push(message);
    });

    diagnostics.fallbackMessageCount =
      messages.length;

    return {
      messages: messages.slice(-MAX_MESSAGES),
      diagnostics
    };
  };

  const parseSnapshot = node => {
    try {
      const raw =
        node.getAttribute("content") ||
        node.textContent ||
        "";

      if (!raw) {
        return null;
      }

      const parsed = JSON.parse(raw);

      return (
        parsed &&
        typeof parsed === "object"
      ) ? parsed : null;
    } catch (_) {
      return null;
    }
  };

  const writeSnapshot = (node, snapshot) => {
    const encoded = JSON.stringify(snapshot);

    node.setAttribute("content", encoded);

    if (
      node.tagName !== "META" &&
      node.textContent !== encoded
    ) {
      node.textContent = encoded;
    }
  };

  const applyFallback = () => {
    if (applying) {
      return;
    }

    const node = document.getElementById(NODE_ID);

    if (!node) {
      return;
    }

    const snapshot = parseSnapshot(node);

    if (!snapshot) {
      return;
    }

    const existingMessages = Array.isArray(
      snapshot.messages
    ) ? snapshot.messages : [];

    if (existingMessages.length > 0) {
      return;
    }

    const sequence =
      snapshot.sequence ??
      snapshot.seq ??
      "";

    if (
      snapshot?.diagnostics?.[PATCH_FLAG] === true &&
      snapshot?.diagnostics?.fallbackMessageCount > 0
    ) {
      return;
    }

    const result = scanFallbackMessages(snapshot);

    const resultKey = [
      sequence,
      result.messages.length,
      result.messages
        .map(message => message.messageId)
        .join(",")
    ].join("|");

    if (
      resultKey === lastAppliedKey &&
      snapshot?.diagnostics?.[PATCH_FLAG] === true
    ) {
      return;
    }

    lastAppliedKey = resultKey;

    const diagnostics = {
      ...(snapshot.diagnostics || {}),
      ...result.diagnostics,
      [PATCH_FLAG]: true,
      fallbackPatchVersion: PATCH_VERSION,
      primaryMessageCount: existingMessages.length
    };

    snapshot.messages = result.messages;
    snapshot.messageCount = result.messages.length;
    snapshot.diagnostics = diagnostics;

    diagnostics.messageCount = result.messages.length;

    applying = true;

    try {
      writeSnapshot(node, snapshot);
    } finally {
      applying = false;
    }
  };

  const schedule = () => {
    if (scheduled) {
      return;
    }

    scheduled = window.setTimeout(() => {
      scheduled = 0;

      try {
        applyFallback();
      } catch (_) {}
    }, 60);
  };

  const observer = new MutationObserver(mutations => {
    if (applying) {
      return;
    }

    for (const mutation of mutations) {
      if (
        mutation.type === "attributes" &&
        mutation.target?.id === NODE_ID
      ) {
        schedule();
        return;
      }

      if (mutation.type === "childList") {
        schedule();
        return;
      }
    }
  });

  const start = () => {
    observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["content"]
      }
    );

    schedule();

    window.setInterval(schedule, 1000);
  };

  if (document.documentElement) {
    start();
  } else {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  }
})();

/*
 * JUBAOPEN_THREADS_TIMESTAMP_RESOLVER_210_3_5_6
 *
 * 独立的 Threads 时间快照后处理器。
 *
 * 不修改 3.5.5 fallback scanner 内部结构，避免依赖缩进和
 * 混淆 class。它观察快照节点，在 fallback 消息生成后：
 *
 * 1. 查找消息 Grid 中居中的时间锚点；
 * 2. 解析日期和时间；
 * 3. 根据消息正文、方向及 DOM 顺序匹配可见消息；
 * 4. 将 occurredAt 写成 Unix 毫秒整数；
 * 5. 将扫描时间保存在 metadata.observedAt；
 * 6. 保留 3.5.5 消息 ID。
 */
(() => {
  "use strict";

  const NODE_ID =
    "jubaopen-threads-page-snapshot-v1";

  const PATCH_VERSION = "210.3.5.6";

  const DIAGNOSTIC_FLAG =
    "threadsTimestampResolver21030506";

  if (
    window.__jubaThreadsTimestampResolver21030506
  ) {
    return;
  }

  window.__jubaThreadsTimestampResolver21030506 =
    true;

  let applying = false;
  let timer = 0;

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
      if (!element || !element.isConnected) {
        return false;
      }

      if (
        element.getAttribute?.("aria-hidden") ===
        "true"
      ) {
        return false;
      }

      const rect =
        element.getBoundingClientRect();

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

  const excluded = (node, grid) => {
    try {
      if (
        !node ||
        !grid ||
        !grid.contains(node)
      ) {
        return true;
      }

      if (
        node.matches?.(
          [
            "[contenteditable='true']",
            "[role='textbox']",
            "textarea",
            "input",
            "button",
            "[role='button']"
          ].join(",")
        )
      ) {
        return true;
      }

      const blocked = node.closest?.(
        [
          "[contenteditable='true']",
          "[role='textbox']",
          "[role='menu']",
          "[role='menuitem']",
          "[role='dialog']",
          "[role='listbox']",
          "textarea",
          "form",
          "nav",
          "header"
        ].join(",")
      );

      return Boolean(
        blocked &&
        blocked !== grid &&
        grid.contains(blocked)
      );
    } catch (_) {
      return true;
    }
  };

  const chooseGrid = () => {
    const grids = Array.from(
      document.querySelectorAll(
        '[role="grid"]'
      )
    ).filter(visible);

    if (!grids.length) {
      return null;
    }

    grids.sort((left, right) => {
      const a =
        left.getBoundingClientRect();

      const b =
        right.getBoundingClientRect();

      return (
        b.width * b.height -
        a.width * a.height
      );
    });

    return grids[0] || null;
  };

  const localEpoch = (
    year,
    month,
    day,
    hour,
    minute,
    second = 0
  ) => {
    const values = [
      year,
      month,
      day,
      hour,
      minute,
      second
    ].map(Number);

    if (
      values.some(
        value => !Number.isInteger(value)
      )
    ) {
      return null;
    }

    const [y, m, d, h, min, sec] =
      values;

    if (
      y < 2000 ||
      y > 2100 ||
      m < 1 ||
      m > 12 ||
      d < 1 ||
      d > 31 ||
      h < 0 ||
      h > 23 ||
      min < 0 ||
      min > 59 ||
      sec < 0 ||
      sec > 59
    ) {
      return null;
    }

    const date = new Date(
      y,
      m - 1,
      d,
      h,
      min,
      sec,
      0
    );

    if (
      date.getFullYear() !== y ||
      date.getMonth() !== m - 1 ||
      date.getDate() !== d ||
      date.getHours() !== h ||
      date.getMinutes() !== min ||
      date.getSeconds() !== sec
    ) {
      return null;
    }

    const result = date.getTime();

    return (
      Number.isFinite(result) &&
      result > 0
    ) ? Math.trunc(result) : null;
  };

  const dateParts = date => ({
    year: date.getFullYear(),
    month: date.getMonth() + 1,
    day: date.getDate()
  });

  const offsetDateParts = (
    date,
    offset
  ) => {
    const shifted = new Date(
      date.getFullYear(),
      date.getMonth(),
      date.getDate() + offset,
      12,
      0,
      0,
      0
    );

    return dateParts(shifted);
  };

  const parseClock = (
    hourText,
    minuteText,
    secondText,
    meridiemText
  ) => {
    let hour = Number(hourText);
    const minute = Number(minuteText);
    const second = Number(
      secondText || 0
    );

    const meridiem = clean(
      meridiemText,
      20
    ).toLowerCase();

    if (
      !Number.isInteger(hour) ||
      !Number.isInteger(minute) ||
      !Number.isInteger(second) ||
      minute < 0 ||
      minute > 59 ||
      second < 0 ||
      second > 59
    ) {
      return null;
    }

    if (meridiem) {
      if (hour < 1 || hour > 12) {
        return null;
      }

      const pm =
        meridiem === "pm" ||
        meridiem.includes("下午") ||
        meridiem.includes("晚上");

      const am =
        meridiem === "am" ||
        meridiem.includes("上午") ||
        meridiem.includes("凌晨");

      if (!pm && !am) {
        return null;
      }

      if (pm && hour !== 12) {
        hour += 12;
      }

      if (am && hour === 12) {
        hour = 0;
      }
    } else if (hour < 0 || hour > 23) {
      return null;
    }

    return {
      hour,
      minute,
      second
    };
  };

  const parseTimeAnchor = (
    input,
    nowMs
  ) => {
    const raw = clean(input, 200);

    if (!raw) {
      return null;
    }

    const text = raw
      .replace(/：/g, ":")
      .replace(/[，,]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    let match = null;
    let clock = null;
    let occurredAt = null;
    let source = "";
    let precision = "minute";

    match = text.match(
      /^(\d{4})年(\d{1,2})月(\d{1,2})日\s*(上午|下午|晚上|凌晨)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?$/
    );

    if (match) {
      clock = parseClock(
        match[5],
        match[6],
        match[7],
        match[4]
      );

      if (!clock) {
        return null;
      }

      occurredAt = localEpoch(
        match[1],
        match[2],
        match[3],
        clock.hour,
        clock.minute,
        clock.second
      );

      source =
        "threads-center-full-date-zh";

      precision =
        match[7] ? "second" : "minute";
    }

    if (!occurredAt) {
      match = text.match(
        /^(\d{4})[\/.-](\d{1,2})[\/.-](\d{1,2})\s+(?:(AM|PM)\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(AM|PM))?$/i
      );

      if (match) {
        clock = parseClock(
          match[5],
          match[6],
          match[7],
          match[4] || match[8]
        );

        if (!clock) {
          return null;
        }

        occurredAt = localEpoch(
          match[1],
          match[2],
          match[3],
          clock.hour,
          clock.minute,
          clock.second
        );

        source =
          "threads-center-full-date-numeric";

        precision =
          match[7] ? "second" : "minute";
      }
    }

    const now = new Date(nowMs);

    if (!occurredAt) {
      match = text.match(
        /^(今天|昨天|today|yesterday)\s+(?:(上午|下午|晚上|凌晨|AM|PM)\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(AM|PM))?$/i
      );

      if (match) {
        clock = parseClock(
          match[3],
          match[4],
          match[5],
          match[2] || match[6]
        );

        if (!clock) {
          return null;
        }

        const label =
          match[1].toLowerCase();

        const offset = (
          label === "昨天" ||
          label === "yesterday"
        ) ? -1 : 0;

        const parts =
          offsetDateParts(now, offset);

        occurredAt = localEpoch(
          parts.year,
          parts.month,
          parts.day,
          clock.hour,
          clock.minute,
          clock.second
        );

        source = offset === -1
          ? "threads-center-yesterday"
          : "threads-center-today";

        precision =
          match[5] ? "second" : "minute";
      }
    }

    if (!occurredAt) {
      match = text.match(
        /^(?:(上午|下午|晚上|凌晨|AM|PM)\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(AM|PM))?$/i
      );

      if (match) {
        clock = parseClock(
          match[2],
          match[3],
          match[4],
          match[1] || match[5]
        );

        if (!clock) {
          return null;
        }

        let parts = dateParts(now);

        occurredAt = localEpoch(
          parts.year,
          parts.month,
          parts.day,
          clock.hour,
          clock.minute,
          clock.second
        );

        if (
          occurredAt &&
          occurredAt >
            nowMs + 5 * 60 * 1000
        ) {
          parts =
            offsetDateParts(now, -1);

          occurredAt = localEpoch(
            parts.year,
            parts.month,
            parts.day,
            clock.hour,
            clock.minute,
            clock.second
          );
        }

        source =
          "threads-center-time-only";

        precision =
          match[4] ? "second" : "minute";
      }
    }

    if (
      !Number.isFinite(occurredAt) ||
      occurredAt <= 0 ||
      occurredAt >
        nowMs + 5 * 60 * 1000
    ) {
      return null;
    }

    return {
      occurredAt:
        Math.trunc(occurredAt),
      raw,
      source,
      precision
    };
  };

  const leafTextNodes = grid =>
    Array.from(
      grid.querySelectorAll(
        "span[dir='auto'],div[dir='auto']"
      )
    ).filter(node => {
      if (
        !visible(node) ||
        excluded(node, grid)
      ) {
        return false;
      }

      const text = clean(
        node.textContent,
        65536
      );

      if (!text) {
        return false;
      }

      return !Array.from(
        node.querySelectorAll(
          "span[dir='auto'],div[dir='auto']"
        )
      ).some(child => (
        child !== node &&
        visible(child) &&
        !excluded(child, grid) &&
        Boolean(
          clean(child.textContent, 65536)
        )
      ));
    });

  const collectAnchors = (
    grid,
    nodes,
    nowMs
  ) => {
    const gridRect =
      grid.getBoundingClientRect();

    const anchors = [];
    const seen = new Set();

    for (const node of nodes) {
      const rect =
        node.getBoundingClientRect();

      if (
        gridRect.width <= 1 ||
        rect.width <= 1
      ) {
        continue;
      }

      const center =
        (
          rect.left +
          rect.width / 2 -
          gridRect.left
        ) / gridRect.width;

      if (
        center <= 0.44 ||
        center >= 0.56
      ) {
        continue;
      }

      const parsed = parseTimeAnchor(
        node.textContent,
        nowMs
      );

      if (!parsed) {
        continue;
      }

      const key = [
        parsed.occurredAt,
        Math.round(rect.top),
        parsed.raw
      ].join("|");

      if (seen.has(key)) {
        continue;
      }

      seen.add(key);

      anchors.push({
        ...parsed,
        top: rect.top,
        left: rect.left
      });
    }

    anchors.sort((left, right) => (
      Math.abs(left.top - right.top) > 2
        ? left.top - right.top
        : left.left - right.left
    ));

    return anchors;
  };

  const directionForNode = (
    node,
    grid
  ) => {
    const gridRect =
      grid.getBoundingClientRect();

    const rect =
      node.getBoundingClientRect();

    if (
      gridRect.width <= 1 ||
      rect.width <= 1
    ) {
      return "";
    }

    const center =
      (
        rect.left +
        rect.width / 2 -
        gridRect.left
      ) / gridRect.width;

    if (center <= 0.44) {
      return "inbound";
    }

    if (center >= 0.56) {
      return "outbound";
    }

    return "";
  };

  const collectMessageNodes = (
    grid,
    nodes,
    nowMs
  ) => {
    const output = [];

    for (const node of nodes) {
      if (
        parseTimeAnchor(
          node.textContent,
          nowMs
        )
      ) {
        continue;
      }

      const direction =
        directionForNode(node, grid);

      if (!direction) {
        continue;
      }

      const text = clean(
        node.textContent,
        65536
      );

      if (!text) {
        continue;
      }

      const rect =
        node.getBoundingClientRect();

      output.push({
        node,
        text,
        direction,
        top: rect.top,
        left: rect.left
      });
    }

    output.sort((left, right) => (
      Math.abs(left.top - right.top) > 2
        ? left.top - right.top
        : left.left - right.left
    ));

    return output;
  };

  const findDomMessage = (
    message,
    candidates,
    used
  ) => {
    const text = clean(
      message?.text ||
      message?.body ||
      message?.content ||
      message?.textContent ||
      "",
      65536
    );

    const direction =
      message?.direction === "outbound"
        ? "outbound"
        : "inbound";

    for (
      let index = 0;
      index < candidates.length;
      index += 1
    ) {
      if (used.has(index)) {
        continue;
      }

      const candidate =
        candidates[index];

      if (
        candidate.direction === direction &&
        candidate.text === text
      ) {
        used.add(index);
        return candidate;
      }
    }

    for (
      let index = 0;
      index < candidates.length;
      index += 1
    ) {
      if (used.has(index)) {
        continue;
      }

      const candidate =
        candidates[index];

      if (
        candidate.direction !== direction
      ) {
        continue;
      }

      if (
        text &&
        (
          candidate.text.includes(text) ||
          text.includes(candidate.text)
        )
      ) {
        used.add(index);
        return candidate;
      }
    }

    return null;
  };

  const precedingAnchor = (
    top,
    anchors
  ) => {
    let selected = null;
    let selectedIndex = -1;

    for (
      let index = 0;
      index < anchors.length;
      index += 1
    ) {
      if (
        anchors[index].top <= top + 2
      ) {
        selected = anchors[index];
        selectedIndex = index;
        continue;
      }

      break;
    }

    return selected
      ? {
          anchor: selected,
          index: selectedIndex
        }
      : null;
  };

  const readSnapshot = node => {
    try {
      const raw =
        node.getAttribute("content") ||
        node.textContent ||
        "";

      if (!raw) {
        return null;
      }

      const value = JSON.parse(raw);

      return (
        value &&
        typeof value === "object"
      ) ? value : null;
    } catch (_) {
      return null;
    }
  };

  const writeSnapshot = (
    node,
    snapshot
  ) => {
    const encoded =
      JSON.stringify(snapshot);

    node.setAttribute(
      "content",
      encoded
    );

    if (
      node.tagName !== "META" &&
      node.textContent !== encoded
    ) {
      node.textContent = encoded;
    }
  };

  const invalidLegacyTimestamp = value => (
    typeof value === "string" &&
    !Number.isFinite(Number(value))
  );

  const apply = () => {
    if (applying) {
      return;
    }

    const node =
      document.getElementById(NODE_ID);

    if (!node) {
      return;
    }

    const snapshot =
      readSnapshot(node);

    if (!snapshot) {
      return;
    }

    const messages =
      Array.isArray(snapshot.messages)
        ? snapshot.messages
        : [];

    if (!messages.length) {
      return;
    }

    const diagnostics =
      snapshot.diagnostics || {};

    if (
      diagnostics[DIAGNOSTIC_FLAG] === true &&
      diagnostics.timestampResolverSequence ===
        snapshot.sequence &&
      messages.every(message => (
        Number.isFinite(
          Number(message?.occurredAt)
        ) ||
        message?.metadata
          ?.timestampResolved === false
      ))
    ) {
      return;
    }

    const grid = chooseGrid();

    if (!grid) {
      return;
    }

    const observedAt = Date.now();
    const leaves = leafTextNodes(grid);

    const anchors = collectAnchors(
      grid,
      leaves,
      observedAt
    );

    const domMessages =
      collectMessageNodes(
        grid,
        leaves,
        observedAt
      );

    const usedDomNodes = new Set();
    const ordinalByAnchor = new Map();

    let resolvedCount = 0;
    let unresolvedCount = 0;
    let approximateCount = 0;
    let matchedDomCount = 0;

    const orderedMessages =
      messages
        .map((message, index) => ({
          message,
          originalIndex: index,
          order: Number.isFinite(
            Number(message?.order)
          )
            ? Number(message.order)
            : index
        }))
        .sort((left, right) => (
          left.order - right.order
        ));

    for (const item of orderedMessages) {
      const message = item.message;

      const domMessage = findDomMessage(
        message,
        domMessages,
        usedDomNodes
      );

      const metadata = {
        ...(
          message.metadata &&
          typeof message.metadata === "object"
            ? message.metadata
            : {}
        ),
        observedAt,
        captureMode:
          "threads-grid-fallback",
        timestampResolverVersion:
          PATCH_VERSION
      };

      if (domMessage) {
        matchedDomCount += 1;
      }

      const resolution = domMessage
        ? precedingAnchor(
            domMessage.top,
            anchors
          )
        : null;

      if (resolution) {
        const previous =
          ordinalByAnchor.get(
            resolution.index
          ) || 0;

        ordinalByAnchor.set(
          resolution.index,
          previous + 1
        );

        const occurredAt =
          resolution.anchor.occurredAt +
          previous;

        message.timestamp = occurredAt;
        message.occurredAt = occurredAt;
        message.sentAt = occurredAt;
        message.createdAt = occurredAt;

        metadata.timestampResolved = true;
        metadata.timestampConfidence =
          previous === 0
            ? "high"
            : "medium";

        metadata.timestampSource =
          previous === 0
            ? resolution.anchor.source
            : "threads-center-time-group";

        metadata.timestampRaw =
          resolution.anchor.raw;

        metadata.timestampPrecision =
          resolution.anchor.precision;

        metadata.timestampAnchorAt =
          resolution.anchor.occurredAt;

        metadata.timestampAnchorIndex =
          resolution.index;

        metadata.timestampOrderOffsetMs =
          previous;

        metadata.timestampApproximate =
          previous > 0;

        metadata.timezone =
          Intl.DateTimeFormat()
            .resolvedOptions()
            .timeZone || "";

        resolvedCount += 1;

        if (previous > 0) {
          approximateCount += 1;
        }
      } else {
        /*
         * 删除 3.5.5 写入的 ISO 扫描时间，避免继续把
         * 观察时间伪装成发送时间。
         */
        if (
          invalidLegacyTimestamp(
            message.timestamp
          )
        ) {
          delete message.timestamp;
        }

        if (
          invalidLegacyTimestamp(
            message.occurredAt
          )
        ) {
          delete message.occurredAt;
        }

        if (
          invalidLegacyTimestamp(
            message.sentAt
          )
        ) {
          delete message.sentAt;
        }

        if (
          invalidLegacyTimestamp(
            message.createdAt
          )
        ) {
          delete message.createdAt;
        }

        metadata.timestampResolved = false;
        metadata.timestampConfidence = "low";

        metadata.timestampSource =
          domMessage
            ? "threads-center-anchor-not-preceding"
            : "threads-message-dom-not-matched";

        metadata.timestampApproximate = false;

        unresolvedCount += 1;
      }

      message.metadata = metadata;
    }

    snapshot.messages = messages;

    snapshot.diagnostics = {
      ...diagnostics,
      [DIAGNOSTIC_FLAG]: true,

      timestampResolverVersion:
        PATCH_VERSION,

      timestampResolverSequence:
        snapshot.sequence,

      timestampScannerMode:
        "threads-center-time-anchor",

      timestampAnchorCount:
        anchors.length,

      timestampDomMessageCount:
        domMessages.length,

      timestampMatchedDomMessageCount:
        matchedDomCount,

      timestampResolvedMessageCount:
        resolvedCount,

      timestampUnresolvedMessageCount:
        unresolvedCount,

      timestampApproximateMessageCount:
        approximateCount,

      timestampAnchorSamples:
        anchors
          .slice(0, 20)
          .map(anchor => ({
            raw: anchor.raw,
            occurredAt:
              anchor.occurredAt,
            source: anchor.source,
            precision:
              anchor.precision,
            top: Math.round(anchor.top)
          }))
    };

    applying = true;

    try {
      writeSnapshot(node, snapshot);
    } finally {
      applying = false;
    }
  };

  const schedule = () => {
    if (timer) {
      return;
    }

    timer = window.setTimeout(() => {
      timer = 0;

      try {
        apply();
      } catch (_) {}
    }, 100);
  };

  const observer =
    new MutationObserver(mutations => {
      if (applying) {
        return;
      }

      for (const mutation of mutations) {
        if (
          mutation.type === "attributes" &&
          mutation.target?.id === NODE_ID
        ) {
          schedule();
          return;
        }

        if (mutation.type === "childList") {
          schedule();
          return;
        }
      }
    });

  const start = () => {
    observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["content"]
      }
    );

    schedule();

    window.setInterval(
      schedule,
      1000
    );
  };

  if (document.documentElement) {
    start();
  } else {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  }
})();

