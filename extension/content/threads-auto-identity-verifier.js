"use strict";

/*
 * JUBAOPEN_THREADS_AUTO_IDENTITY_VERIFIER_210_3_15
 *
 * 运行环境：MAIN world。
 *
 * 本文件只发布经过严格验证的当前会话联系人用户名：
 *
 * 1. 必须位于 /messages/t/{threadId}；
 * 2. 必须来自当前聊天区域中的 Threads 个人资料链接；
 * 3. 必须排除当前登录账号本人；
 * 4. 必须只有一个高可信候选；
 * 5. 必须连续命中至少 3 次；
 * 6. 必须稳定至少 900ms；
 * 7. 冲突或切换会话时立即撤销。
 *
 * 不访问 Cookie、Token、密码或 Chrome 扩展 API。
 */
(() => {
  if (window.__jubaThreadsAutoIdentityVerifier210315) {
    return;
  }

  window.__jubaThreadsAutoIdentityVerifier210315 = true;

  const VERSION = "210.3.15";

  const SNAPSHOT_ID = "jubaopen-threads-page-snapshot-v1";

  const BRIDGE_ID = "jubaopen-threads-auto-contact-v210315";

  const MANUAL_HOST_ID = "jubaopen-threads-manual-contact-host";

  const PANEL_HOST_ID = "jubaopen-interaction-host";

  const REQUIRED_HITS = 3;
  const REQUIRED_STABLE_MS = 900;
  const SCAN_INTERVAL_MS = 350;
  const MIN_SCORE = 58;
  const CONFLICT_MARGIN = 12;

  const blockedNames = new Set([
    "messages",
    "activity",
    "search",
    "settings",
    "privacy",
    "accounts",
    "login",
    "signup",
    "explore",
    "following",
    "followers",
    "notifications",
    "about",
    "help"
  ]);

  const state = {
    threadId: "",
    candidate: "",
    hits: 0,
    firstSeenAt: 0,
    lastSeenAt: 0,
    publishedSignature: "",
    scans: 0,
    lastReason: "",
    timer: 0
  };

  const clean = (value, max = 4096) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .replace(
        /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g,
        ""
      )
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);

  function normalizeUsername(value) {
    const result = clean(value, 100)
      .replace(/^@/, "")
      .replace(/^\/+|\/+$/g, "")
      .toLowerCase();

    if (
      !/^[a-z0-9._]{1,64}$/.test(result) ||
      blockedNames.has(result)
    ) {
      return "";
    }

    return result;
  }

  function profileUsername(href) {
    try {
      const url = new URL(href, location.href);

      if (
        !/^(?:www\.)?threads\.com$/i.test(
          url.hostname
        )
      ) {
        return "";
      }

      const parts = url.pathname.split("/").filter(Boolean);

      if (parts.length !== 1) {
        return "";
      }

      return normalizeUsername(parts[0]);
    } catch (_) {
      return "";
    }
  }

  function currentThreadId() {
    const match = location.pathname.match(
      /^\/messages\/t\/([^/?#]+)/
    );

    if (!match) {
      return "";
    }

    try {
      return clean(
        decodeURIComponent(match[1]),
        256
      );
    } catch (_) {
      return clean(match[1], 256);
    }
  }

  function isVisible(element) {
    try {
      if (
        !element ||
        !element.isConnected ||
        element.getAttribute?.("aria-hidden") === "true"
      ) {
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
  }

  function readSnapshot() {
    const node = document.getElementById(SNAPSHOT_ID);

    if (!node) {
      return null;
    }

    try {
      const value = JSON.parse(
        node.getAttribute("content") || "{}"
      );

      if (
        value?.v !== 1 ||
        value?.platform !== "threads"
      ) {
        return null;
      }

      return value;
    } catch (_) {
      return null;
    }
  }

  function ownerUsername() {
    const snapshot = readSnapshot();
    const identity = snapshot?.ownIdentity;

    if (
      !identity ||
      identity.role !== "IS_OWNER" ||
      identity.stable !== true ||
      identity.confidence !== "high" ||
      identity.identityType !== "threads_username"
    ) {
      return "";
    }

    return normalizeUsername(
      identity.identityValue
    );
  }

  function findComposer() {
    const selectors = [
      '[role="textbox"][contenteditable="true"][data-lexical-editor]',
      '[role="textbox"][contenteditable="true"]'
    ];

    const candidates = selectors.flatMap(selector =>
        Array.from(
          document.querySelectorAll(selector)
        )
      ).filter(isVisible);

    candidates.sort((left, right) => {
      const a = left.getBoundingClientRect();
      const b = right.getBoundingClientRect();

      return b.top - a.top;
    });

    return candidates[0] || null;
  }

  function conversationRoot() {
    const composer = findComposer();

    if (!composer) {
      return null;
    }

    let best = null;
    let bestScore = -Infinity;

    for (
      let node = composer.parentElement, depth = 0;
      node && depth < 12;
      node = node.parentElement, depth += 1
    ) {
      if (
        node === document.body ||
        node === document.documentElement
      ) {
        break;
      }

      let rect;

      try {
        rect = node.getBoundingClientRect();
      } catch (_) {
        continue;
      }

      if (
        rect.width < innerWidth * 0.30 ||
        rect.height < innerHeight * 0.35
      ) {
        continue;
      }

      const anchorCount = node.querySelectorAll('a[href]').length;

      const score = Math.min(rect.height, innerHeight) +
        Math.min(rect.width, innerWidth) * 0.25 -
        depth * 15 +
        Math.min(anchorCount, 20) * 2;

      if (score > bestScore) {
        best = node;
        bestScore = score;
      }
    }

    return best;
  }

  function excludedAnchor(anchor) {
    if (!anchor || !anchor.isConnected) {
      return true;
    }

    if (
      anchor.closest(
        `#${MANUAL_HOST_ID},#${PANEL_HOST_ID}`
      )
    ) {
      return true;
    }

    if (
      anchor.closest(
        'nav,[role="navigation"],[role="menu"],' +
        '[role="dialog"]'
      )
    ) {
      return true;
    }

    const href = anchor.getAttribute("href") || "";

    return (
      href.includes("/messages/") ||
      href.includes("/activity") ||
      href.includes("/search") ||
      href.includes("/settings")
    );
  }

  function collectCandidates() {
    const threadId = currentThreadId();

    if (!threadId) {
      return {
        ok: false,
        reason: "NOT_CONVERSATION_ROUTE",
        candidates: []
      };
    }

    const root = conversationRoot();

    if (!root) {
      return {
        ok: false,
        reason: "CONVERSATION_ROOT_MISSING",
        candidates: []
      };
    }

    const owner = ownerUsername();
    const byUsername = new Map();

    for (
      const anchor of
      root.querySelectorAll('a[href]')
    ) {
      if (
        !isVisible(anchor) ||
        excludedAnchor(anchor)
      ) {
        continue;
      }

      const username = profileUsername(
          anchor.getAttribute("href")
        );

      if (
        !username ||
        username === owner
      ) {
        continue;
      }

      const rect = anchor.getBoundingClientRect();

      const rootRect = root.getBoundingClientRect();

      let score = 20;

      /*
       * 当前聊天区域证据。
       */
      score += 24;

      /*
       * 对话顶部资料入口通常比消息正文中的链接更可靠。
       */
      if (
        rect.top <=
        Math.max(260, rootRect.top + 220)
      ) {
        score += 25;
      }

      /*
       * 排除页面左侧会话列表区域。
       */
      if (rect.left >= innerWidth * 0.22) {
        score += 12;
      } else {
        score -= 30;
      }

      if (
        anchor.querySelector("img")
      ) {
        score += 8;
      }

      const text = clean(anchor.textContent, 200)
          .toLowerCase();

      if (
        text.includes(username) ||
        text.includes(`@${username}`)
      ) {
        score += 8;
      }

      const old = byUsername.get(username);

      if (
        !old ||
        score > old.score
      ) {
        byUsername.set(username, {
          username,
          score,
          displayName:
            clean(
              anchor.textContent ||
              anchor.querySelector("img")?.alt ||
              `@${username}`,
              200
            ) || `@${username}`,
          profileUrl:
            clean(anchor.href, 2048),
          avatarUrl:
            clean(
              anchor.querySelector("img")?.src,
              4096
            ),
          evidence: {
            inConversationRoot: true,
            ownerExcluded:
              Boolean(owner),
            left:
              Math.round(rect.left),
            top:
              Math.round(rect.top),
            hasImage:
              Boolean(
                anchor.querySelector("img")
              )
          }
        });
      }
    }

    const candidates = Array.from(byUsername.values())
        .filter(item =>
          item.score >= MIN_SCORE
        )
        .sort((a, b) =>
          b.score - a.score
        );

    if (!candidates.length) {
      return {
        ok: false,
        reason: "NO_HIGH_CONFIDENCE_CANDIDATE",
        owner,
        candidates
      };
    }

    if (
      candidates.length > 1 &&
      candidates[0].score -
        candidates[1].score <
        CONFLICT_MARGIN
    ) {
      return {
        ok: false,
        reason: "PARTICIPANT_CANDIDATE_CONFLICT",
        owner,
        candidates
      };
    }

    return {
      ok: true,
      reason: "UNIQUE_CANDIDATE",
      owner,
      candidate: candidates[0],
      candidates
    };
  }

  function ensureBridge() {
    let node = document.getElementById(BRIDGE_ID);

    if (!node) {
      node = document.createElement("meta");
      node.id = BRIDGE_ID;
      node.hidden = true;

      (
        document.head ||
        document.documentElement
      ).appendChild(node);
    }

    return node;
  }

  function clearBridge(reason) {
    const node = document.getElementById(BRIDGE_ID);

    const payload = {
      v: 1,
      version: VERSION,
      platform: "threads",
      at: Date.now(),
      threadId: currentThreadId(),
      verified: false,
      reason: clean(reason, 200),
      identity: null
    };

    const signature = JSON.stringify(payload);

    if (
      signature === state.publishedSignature
    ) {
      return;
    }

    state.publishedSignature = signature;

    ensureBridge().setAttribute(
      "content",
      signature
    );
  }

  function publish(candidate) {
    const now = Date.now();

    const payload = {
      v: 1,
      version: VERSION,
      platform: "threads",
      at: now,
      threadId: state.threadId,
      verified: true,
      verification: "automatic",
      identity: {
        identityType: "threads_username",
        identityValue: candidate.username,
        displayName:
          candidate.displayName ||
          `@${candidate.username}`,
        avatarUrl:
          candidate.avatarUrl || "",
        profileUrl:
          candidate.profileUrl || "",
        role: "IS_PARTICIPANT",
        stable: true,
        confidence: "high",
        confirmedByUser: false,
        automaticallyVerified: true,
        writable: true,
        threadId: state.threadId,
        source:
          "threads-conversation-participant-profile",
        evidence: {
          ...candidate.evidence,
          uniqueCandidate: true,
          consecutiveHits:
            state.hits,
          stableForMs:
            now - state.firstSeenAt,
          score:
            candidate.score
        }
      }
    };

    const signature = JSON.stringify(payload);

    /*
     * at 会变化，但只在身份或关键证据变化时更新 Bridge。
     */
    const stableSignature = [
      payload.threadId,
      payload.identity.identityType,
      payload.identity.identityValue,
      payload.identity.source,
      payload.identity.evidence.score
    ].join("|");

    if (
      stableSignature ===
      state.publishedSignature
    ) {
      return;
    }

    state.publishedSignature = stableSignature;

    ensureBridge().setAttribute(
      "content",
      JSON.stringify(payload)
    );
  }

  function resetCandidate(
    threadId,
    reason
  ) {
    state.threadId = threadId;
    state.candidate = "";
    state.hits = 0;
    state.firstSeenAt = 0;
    state.lastSeenAt = 0;
    state.lastReason = reason;
  }

  function scan() {
    state.scans += 1;

    const now = Date.now();
    const threadId = currentThreadId();

    if (!threadId) {
      resetCandidate(
        "",
        "NOT_CONVERSATION_ROUTE"
      );

      clearBridge(
        "NOT_CONVERSATION_ROUTE"
      );

      return;
    }

    if (state.threadId !== threadId) {
      resetCandidate(
        threadId,
        "THREAD_CHANGED"
      );

      clearBridge("THREAD_CHANGED");
    }

    const result = collectCandidates();

    if (!result.ok) {
      resetCandidate(
        threadId,
        result.reason
      );

      clearBridge(result.reason);
      return;
    }

    const candidate = result.candidate;

    if (
      state.candidate !==
      candidate.username
    ) {
      state.candidate = candidate.username;
      state.hits = 1;
      state.firstSeenAt = now;
      state.lastSeenAt = now;
      state.lastReason = "CANDIDATE_STARTED";

      clearBridge(
        "CANDIDATE_STABILIZING"
      );

      return;
    }

    state.hits += 1;
    state.lastSeenAt = now;

    if (
      state.hits < REQUIRED_HITS ||
      now - state.firstSeenAt <
        REQUIRED_STABLE_MS
    ) {
      clearBridge(
        "CANDIDATE_STABILIZING"
      );

      return;
    }

    state.lastReason = "AUTO_VERIFIED";

    publish(candidate);
  }

  function schedule() {
    clearTimeout(state.timer);

    state.timer = setTimeout(
      scan,
      80
    );
  }

  const observer = new MutationObserver(schedule);

  function start() {
    if (!document.documentElement) {
      setTimeout(start, 50);
      return;
    }

    observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: [
          "href",
          "aria-label",
          "content"
        ]
      }
    );

    scan();

    setInterval(
      scan,
      SCAN_INTERVAL_MS
    );
  }

  start();

  window.addEventListener(
    "pagehide",
    () => observer.disconnect(),
    {
      once: true
    }
  );
})();
