"use strict";

/*
 * JUBAOPEN_THREADS_CONTACT_IDENTITY_210_3_16
 *
 * 运行于 MAIN world。
 *
 * 职责：
 * 1. 读取当前 threadId 对应的人工确认记录；
 * 2. 读取 Page Probe 与 210.3.15 自动验证结果；
 * 3. 自动候选必须连续稳定，且不得等于本人身份；
 * 4. 人工确认拥有最高优先级；
 * 5. 发布单一权威身份 Bridge；
 * 6. 为“确认并立即应用”提供保存、回读及回执反馈；
 */
(() => {
  if (window.__jubaThreadsContactIdentity210316) {
    return;
  }

  window.__jubaThreadsContactIdentity210316 = true;

  const VERSION = "210.3.16";

  const SNAPSHOT_ID =
    "jubaopen-threads-page-snapshot-v1";

  const OLD_MANUAL_BRIDGE_ID =
    "jubaopen-threads-manual-contact-v210305";

  const OLD_AUTO_BRIDGE_ID =
    "jubaopen-threads-auto-contact-v210315";

  const UNIFIED_BRIDGE_ID =
    "jubaopen-threads-contact-identity-v210316";

  const ACK_ID =
    "jubaopen-threads-contact-identity-ack-v210316";

  const HOST_ID =
    "jubaopen-threads-manual-contact-host";

  const STORAGE_PREFIX =
    "jubaopen.threads.manualContact.v210305.";

  const OWNER_SESSION_KEY =
    "jubaopen.threads.ownerIdentity.v210301";

  const REQUIRED_HITS = 3;
  const REQUIRED_STABLE_MS = 900;

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
    route: "",
    threadId: "",
    autoValue: "",
    autoHits: 0,
    autoFirstSeenAt: 0,
    revision: 0,
    lastSignature: "",
    lastSelected: null,
    timer: 0,
    observer: null,
    submitBusy: false,
    lastAckRevision: 0
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
    let result = clean(value, 512);

    if (/^https?:\/\//i.test(result)) {
      try {
        const url = new URL(result);

        if (
          !/^(?:www\.)?threads\.com$/i.test(
            url.hostname
          )
        ) {
          return "";
        }

        result =
          url.pathname
            .split("/")
            .filter(Boolean)[0] || "";
      } catch (_) {
        return "";
      }
    }

    result = result
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

  function storageKey(threadId) {
    return (
      STORAGE_PREFIX +
      encodeURIComponent(threadId)
    );
  }

  function readJsonStorage(storage, key) {
    try {
      const raw = storage.getItem(key);

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
  }

  function writeJsonStorage(
    storage,
    key,
    value
  ) {
    try {
      storage.setItem(
        key,
        JSON.stringify(value)
      );

      return true;
    } catch (_) {
      return false;
    }
  }

  function readMeta(id) {
    const node =
      document.getElementById(id);

    if (!node) {
      return null;
    }

    try {
      const value = JSON.parse(
        node.getAttribute("content") || "{}"
      );

      return (
        value &&
        typeof value === "object"
      ) ? value : null;
    } catch (_) {
      return null;
    }
  }

  function ensureMeta(id) {
    let node =
      document.getElementById(id);

    if (!node) {
      node = document.createElement("meta");
      node.id = id;
      node.hidden = true;

      (
        document.head ||
        document.documentElement
      ).appendChild(node);
    }

    return node;
  }

  function ownerUsername() {
    const stored = readJsonStorage(
      sessionStorage,
      OWNER_SESSION_KEY
    );

    if (
      stored?.role === "IS_OWNER" &&
      stored?.stable === true &&
      stored?.confidence === "high"
    ) {
      return normalizeUsername(
        stored.identityValue
      );
    }

    const snapshot =
      readMeta(SNAPSHOT_ID);

    const owner =
      snapshot?.ownIdentity;

    if (
      owner?.role !== "IS_OWNER" ||
      owner?.stable !== true ||
      owner?.confidence !== "high"
    ) {
      return "";
    }

    return normalizeUsername(
      owner.identityValue
    );
  }

  function normalizeParticipant(
    source,
    threadId,
    resolution
  ) {
    if (
      !source ||
      !threadId ||
      clean(source.threadId, 256) !== threadId
    ) {
      return null;
    }

    const identityValue =
      normalizeUsername(
        source.identityValue
      );

    if (!identityValue) {
      return null;
    }

    const owner = ownerUsername();

    if (
      owner &&
      owner === identityValue
    ) {
      return null;
    }

    return {
      identityType:
        "threads_username",
      identityValue,
      displayName:
        clean(
          source.displayName ||
          `@${identityValue}`,
          200
        ) || `@${identityValue}`,
      avatarUrl:
        clean(source.avatarUrl, 4096),
      profileUrl:
        clean(
          source.profileUrl ||
          `https://www.threads.com/@${identityValue}`,
          4096
        ),
      role:
        "IS_PARTICIPANT",
      stable:
        true,
      confidence:
        "high",
      writable:
        true,
      threadId,
      resolution,
      source:
        clean(
          source.source ||
          resolution,
          200
        ),
      confirmedByUser:
        resolution === "manual-confirmed",
      automaticallyVerified:
        resolution !== "manual-confirmed",
      savedAt:
        Number(source.savedAt) || 0,
      evidence:
        source.evidence &&
        typeof source.evidence === "object"
          ? source.evidence
          : {}
    };
  }

  function readManual(threadId) {
    if (!threadId) {
      return null;
    }

    const record = readJsonStorage(
      localStorage,
      storageKey(threadId)
    );

    if (!record) {
      return null;
    }

    if (
      record.confirmedByUser !== true ||
      clean(record.threadId, 256) !== threadId
    ) {
      return null;
    }

    return normalizeParticipant(
      {
        ...record,
        threadId,
        source:
          "threads-user-confirmed-manual-contact"
      },
      threadId,
      "manual-confirmed"
    );
  }

  function snapshotCandidate(threadId) {
    const snapshot =
      readMeta(SNAPSHOT_ID);

    const conversation =
      snapshot?.conversation;

    const identity =
      conversation?.identity;

    if (
      !conversation ||
      clean(conversation.threadId, 256) !==
        threadId ||
      !identity ||
      identity.role !== "IS_PARTICIPANT"
    ) {
      return null;
    }

    return normalizeParticipant(
      {
        ...identity,
        threadId,
        source:
          "threads-page-probe-candidate"
      },
      threadId,
      "auto-verified"
    );
  }

  function oldAutoCandidate(threadId) {
    const payload =
      readMeta(OLD_AUTO_BRIDGE_ID);

    if (
      payload?.verified !== true ||
      clean(payload.threadId, 256) !== threadId
    ) {
      return null;
    }

    return normalizeParticipant(
      payload.identity,
      threadId,
      "auto-verified"
    );
  }

  function stableAutomatic(threadId) {
    const candidate =
      oldAutoCandidate(threadId) ||
      snapshotCandidate(threadId);

    const value =
      candidate?.identityValue || "";

    const now = Date.now();

    if (!value) {
      state.autoValue = "";
      state.autoHits = 0;
      state.autoFirstSeenAt = 0;
      return null;
    }

    if (state.autoValue !== value) {
      state.autoValue = value;
      state.autoHits = 1;
      state.autoFirstSeenAt = now;
      return null;
    }

    state.autoHits += 1;

    if (
      state.autoHits < REQUIRED_HITS ||
      now - state.autoFirstSeenAt <
        REQUIRED_STABLE_MS
    ) {
      return null;
    }

    return {
      ...candidate,
      evidence: {
        ...candidate.evidence,
        uniqueCandidate: true,
        ownerExcluded: true,
        consecutiveHits:
          state.autoHits,
        stableForMs:
          now - state.autoFirstSeenAt
      }
    };
  }

  function selectIdentity(threadId) {
    const manual =
      readManual(threadId);

    const automatic =
      stableAutomatic(threadId);

    if (
      manual &&
      automatic &&
      manual.identityValue !==
        automatic.identityValue
    ) {
      return {
        selected: manual,
        conflict: {
          code: "IDENTITY_CONFLICT",
          manualIdentityValue:
            manual.identityValue,
          automaticIdentityValue:
            automatic.identityValue
        },
        manual,
        automatic
      };
    }

    if (manual) {
      return {
        selected: manual,
        conflict: null,
        manual,
        automatic
      };
    }

    if (automatic) {
      return {
        selected: automatic,
        conflict: null,
        manual: null,
        automatic
      };
    }

    return {
      selected: null,
      conflict: null,
      manual: null,
      automatic: null
    };
  }

  function publishOldManualBridge(
    threadId,
    identity
  ) {
    const payload = {
      v: 1,
      version: VERSION,
      platform: "threads",
      at: Date.now(),
      threadId,
      identity
    };

    ensureMeta(
      OLD_MANUAL_BRIDGE_ID
    ).setAttribute(
      "content",
      JSON.stringify(payload)
    );
  }

  function authoritySignature(
    threadId,
    result
  ) {
    const selected =
      result.selected;

    return [
      threadId,
      selected?.identityType || "",
      selected?.identityValue || "",
      selected?.resolution || "",
      selected?.savedAt || 0,
      result.conflict?.code || "",
      result.conflict
        ?.automaticIdentityValue || ""
    ].join("|");
  }

  function publishUnified(reason = "POLL") {
    const threadId =
      currentThreadId();

    if (
      state.threadId !== threadId
    ) {
      state.threadId = threadId;
      state.autoValue = "";
      state.autoHits = 0;
      state.autoFirstSeenAt = 0;
      state.lastSignature = "";
    }

    const result =
      selectIdentity(threadId);

    const signature =
      authoritySignature(
        threadId,
        result
      );

    if (
      signature === state.lastSignature
    ) {
      state.lastSelected =
        result.selected;
      updateStatusUi(result);
      return;
    }

    state.lastSignature = signature;
    state.lastSelected =
      result.selected;
    state.revision += 1;

    const payload = {
      v: 2,
      version: VERSION,
      platform: "threads",
      at: Date.now(),
      revision: state.revision,
      threadId,
      route:
        clean(
          location.pathname +
          location.search +
          location.hash,
          2048
        ),
      status:
        result.conflict
          ? "conflict"
          : result.selected
            ? result.selected.resolution
            : "missing",
      selected:
        result.selected,
      conflict:
        result.conflict,
      candidates: {
        manual:
          result.manual,
        automatic:
          result.automatic
      },
      reason
    };

    ensureMeta(
      UNIFIED_BRIDGE_ID
    ).setAttribute(
      "content",
      JSON.stringify(payload)
    );

    updateStatusUi(result);
  }

  function shadowRoot() {
    return (
      document.getElementById(HOST_ID)
        ?.shadowRoot || null
    );
  }

  function allShadowButtons() {
    const root = shadowRoot();

    return root
      ? Array.from(
          root.querySelectorAll("button")
        )
      : [];
  }

  function findConfirmButton() {
    return (
      allShadowButtons().find(button => {
        const text =
          clean(button.textContent, 100);

        return (
          text.includes("确认") &&
          text.includes("应用")
        );
      }) || null
    );
  }

  function findTextInput() {
    const root = shadowRoot();

    if (!root) {
      return null;
    }

    const inputs =
      Array.from(
        root.querySelectorAll(
          'input:not([type]),' +
          'input[type="text"],' +
          'input[type="url"]'
        )
      );

    return (
      inputs.find(input => {
        const value =
          normalizeUsername(input.value);

        return Boolean(value);
      }) ||
      inputs[0] ||
      null
    );
  }

  function findConfirmationCheckbox() {
    return (
      shadowRoot()
        ?.querySelector(
          'input[type="checkbox"]'
        ) || null
    );
  }

  function statusElement() {
    const root = shadowRoot();

    if (!root) {
      return null;
    }

    const candidates = Array.from(
      root.querySelectorAll(
        '[role="status"],.status,.message,' +
        '[data-status],p,div'
      )
    );

    return (
      candidates.find(element => {
        const text =
          clean(element.textContent, 300);

        return (
          text.includes("保存失败") ||
          text.includes("应用失败") ||
          text.includes("已应用") ||
          text.includes("自动识别失败")
        );
      }) || null
    );
  }

  function showMessage(
    message,
    isError = false
  ) {
    const root = shadowRoot();

    if (!root) {
      return;
    }

    let element =
      root.getElementById(
        "jubaopen-threads-manual-result-v210316"
      );

    if (!element) {
      element =
        document.createElement("div");

      element.id =
        "jubaopen-threads-manual-result-v210316";

      element.setAttribute(
        "role",
        "status"
      );

      element.style.cssText = [
        "margin:8px 0",
        "padding:8px 10px",
        "border-radius:8px",
        "font:600 12px/1.45 system-ui,sans-serif",
        "word-break:break-word"
      ].join(";");

      const button =
        findConfirmButton();

      if (button?.parentElement) {
        button.parentElement.insertBefore(
          element,
          button.parentElement.firstChild
        );
      } else {
        root.appendChild(element);
      }
    }

    element.style.background =
      isError ? "#fff0f3" : "#ecfdf3";

    element.style.color =
      isError ? "#b42318" : "#067647";

    element.style.border =
      isError
        ? "1px solid #fda4af"
        : "1px solid #86efac";

    element.textContent = message;
  }

  function readAck(
    threadId,
    identityValue,
    minimumRevision
  ) {
    const ack =
      readMeta(ACK_ID);

    if (
      ack?.v !== 1 ||
      ack?.accepted !== true ||
      clean(ack.threadId, 256) !==
        threadId ||
      normalizeUsername(
        ack.identityValue
      ) !== identityValue ||
      Number(ack.revision) <
        Number(minimumRevision)
    ) {
      return null;
    }

    return ack;
  }

  function waitForAck(
    threadId,
    identityValue,
    minimumRevision,
    timeoutMs = 3500
  ) {
    return new Promise(resolve => {
      const startedAt = Date.now();

      const check = () => {
        const ack = readAck(
          threadId,
          identityValue,
          minimumRevision
        );

        if (ack) {
          resolve(ack);
          return;
        }

        if (
          Date.now() - startedAt >=
            timeoutMs
        ) {
          resolve(null);
          return;
        }

        setTimeout(check, 80);
      };

      check();
    });
  }

  function buildManualRecord(
    threadId,
    identityValue
  ) {
    const savedAt = Date.now();

    return {
      identityType:
        "threads_username",
      identityValue,
      displayName:
        `@${identityValue}`,
      avatarUrl: "",
      profileUrl:
        `https://www.threads.com/@${identityValue}`,
      role:
        "IS_PARTICIPANT",
      stable:
        true,
      confidence:
        "high",
      writable:
        true,
      source:
        "threads-user-confirmed-manual-contact",
      threadId,
      confirmedByUser:
        true,
      manuallyConfirmed:
        true,
      savedAt,
      version:
        VERSION
    };
  }

  async function applyManualIdentity(event) {
    if (state.submitBusy) {
      event?.preventDefault?.();
      event?.stopImmediatePropagation?.();
      return;
    }

    const button =
      findConfirmButton();

    const input =
      findTextInput();

    const checkbox =
      findConfirmationCheckbox();

    const threadId =
      currentThreadId();

    const identityValue =
      normalizeUsername(input?.value);

    if (!threadId) {
      event?.preventDefault?.();
      event?.stopImmediatePropagation?.();
      showMessage(
        "应用失败：当前不是有效的 Threads 会话。",
        true
      );
      return;
    }

    if (!identityValue) {
      event?.preventDefault?.();
      event?.stopImmediatePropagation?.();
      showMessage(
        "应用失败：Threads 用户名格式无效。",
        true
      );
      return;
    }

    if (
      checkbox &&
      checkbox.checked !== true
    ) {
      event?.preventDefault?.();
      event?.stopImmediatePropagation?.();
      showMessage(
        "请先勾选并确认这是当前聊天对方。",
        true
      );
      return;
    }

    const owner =
      ownerUsername();

    if (
      owner &&
      owner === identityValue
    ) {
      event?.preventDefault?.();
      event?.stopImmediatePropagation?.();
      showMessage(
        "应用失败：联系人用户名不能与本人账号相同。",
        true
      );
      return;
    }

    state.submitBusy = true;

    if (button) {
      button.disabled = true;
      button.dataset.jubaOriginalText =
        clean(button.textContent, 100);

      button.textContent =
        "正在保存并应用…";
    }

    showMessage(
      `正在应用：@${identityValue}`
    );

    try {
      const record =
        buildManualRecord(
          threadId,
          identityValue
        );

      const saved =
        writeJsonStorage(
          localStorage,
          storageKey(threadId),
          record
        );

      if (!saved) {
        throw new Error(
          "LOCAL_STORAGE_WRITE_FAILED"
        );
      }

      const reread =
        readJsonStorage(
          localStorage,
          storageKey(threadId)
        );

      if (
        normalizeUsername(
          reread?.identityValue
        ) !== identityValue ||
        reread?.confirmedByUser !== true ||
        clean(reread?.threadId, 256) !==
          threadId
      ) {
        throw new Error(
          "LOCAL_STORAGE_READBACK_FAILED"
        );
      }

      publishOldManualBridge(
        threadId,
        record
      );

      state.lastSignature = "";
      publishUnified(
        "MANUAL_CONFIRMATION_COMMITTED"
      );

      const unified =
        readMeta(UNIFIED_BRIDGE_ID);

      const revision =
        Number(unified?.revision) || 0;

      window.dispatchEvent(
        new CustomEvent(
          "jubaopen:threads-manual-identity-committed",
          {
            detail: {
              platform: "threads",
              threadId,
              identityValue,
              revision
            }
          }
        )
      );

      const ack =
        await waitForAck(
          threadId,
          identityValue,
          revision
        );

      if (!ack) {
        throw new Error(
          "IDENTITY_APPLY_ACK_TIMEOUT"
        );
      }

      state.lastAckRevision =
        Number(ack.revision) || revision;

      showMessage(
        `已确认并应用：@${identityValue}`
      );

      updateStatusUi({
        selected: {
          ...record,
          resolution:
            "manual-confirmed"
        },
        conflict: null
      });

      if (button) {
        button.textContent =
          "已应用";
      }
    } catch (error) {
      const code =
        clean(
          error?.message || error,
          200
        );

      const messages = {
        LOCAL_STORAGE_WRITE_FAILED:
          "浏览器拒绝保存人工身份。",
        LOCAL_STORAGE_READBACK_FAILED:
          "人工身份保存后回读校验失败。",
        IDENTITY_APPLY_ACK_TIMEOUT:
          "身份已保存，但建档 Adapter 未在规定时间内接受。"
      };

      showMessage(
        `应用失败：${messages[code] || code}`,
        true
      );

      if (button) {
        button.textContent =
          "重试确认并应用";
      }
    } finally {
      state.submitBusy = false;

      if (button) {
        button.disabled = false;
      }
    }
  }

  function hookConfirmButton() {
    const button =
      findConfirmButton();

    if (
      !button ||
      button.dataset
        .jubaIdentityHook210316 === "1"
    ) {
      return;
    }

    button.dataset
      .jubaIdentityHook210316 = "1";

    /*
     * 不阻断 210.3.15 原处理器。
     * 210.3.16 在同一次点击中独立完成保存、回读及应用确认。
     */
    button.addEventListener(
      "click",
      applyManualIdentity,
      true
    );
  }

  function updateStatusUi(result) {
    const selected =
      result?.selected;

    const conflict =
      result?.conflict;

    for (
      const button of allShadowButtons()
    ) {
      const text =
        clean(button.textContent, 200);

      if (
        !text.startsWith("联系人：") &&
        !text.includes("点击核对")
      ) {
        continue;
      }

      if (conflict) {
        button.textContent =
          "联系人身份冲突 · 点击处理";
        continue;
      }

      if (!selected) {
        continue;
      }

      const label =
        selected.resolution ===
          "manual-confirmed"
          ? "手动已确认"
          : "自动已验证";

      button.textContent =
        `联系人：@${selected.identityValue}（${label}）`;
    }
  }

  function tick(reason = "POLL") {
    hookConfirmButton();
    publishUnified(reason);
  }

  function schedule() {
    clearTimeout(state.timer);

    state.timer = setTimeout(
      () => tick("DOM_MUTATION"),
      60
    );
  }

  function start() {
    if (!document.documentElement) {
      setTimeout(start, 50);
      return;
    }

    state.observer =
      new MutationObserver(schedule);

    state.observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: [
          "content",
          "href",
          "aria-label"
        ]
      }
    );

    tick("START");

    setInterval(
      () => tick("POLL"),
      350
    );
  }

  start();

  window.addEventListener(
    "pagehide",
    () => {
      clearTimeout(state.timer);
      state.observer?.disconnect();
    },
    {
      once: true
    }
  );
})();
