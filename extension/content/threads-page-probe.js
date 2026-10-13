"use strict";
/*
 * JubaOpen Threads page probe 210.3.5
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

