"use strict";

/*
 * JUBAOPEN_THREADS_IDENTITY_210_3_18
 *
 * Threads ISOLATED world 单一联系人身份模块。
 *
 * 职责：
 * 1. 使用唯一人工身份存储；
 * 2. 提供唯一人工确认 UI；
 * 3. 人工身份优先于自动身份；
 * 4. 直接包装 Threads Adapter；
 * 5. 在 Chat Panel 加载前提供最终 conversation；
 * 6. 保存成功后重新加载页面，清理面板旧状态。
 *
 * 不使用旧 Bridge，不使用旧 Adapter，不使用多层 Authority。
 */
(() => {
  if (window.__jubaThreadsIdentity210318) {
    return;
  }

  window.__jubaThreadsIdentity210318 = true;

  const VERSION = "210.3.18";

  const STORAGE_PREFIX =
    "jubaopen.threads.manualContact.v210318.";

  const HOST_ID =
    "jubaopen-threads-identity-host-v210318";

  const INPUT_ID =
    "jubaopen-threads-contact-input-v210318";

  const CHECKBOX_ID =
    "jubaopen-threads-contact-checkbox-v210318";

  const SNAPSHOT_ID =
    "jubaopen-threads-page-snapshot-v1";

  const DIAGNOSTIC_ID =
    "jubaopen-threads-identity-diagnostics-v210318";

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
    adapter: null,
    originalConversation: null,
    originalContext: null,
    originalDiagnostics: null,
    installed: false,
    host: null,
    shadow: null,
    editorOpen: false,
    saving: false,
    lastThreadId: "",
    lastStatusSignature: "",
    timer: 0,
    routeTimer: 0
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
    let username = clean(value, 512);

    if (/^https?:\/\//i.test(username)) {
      try {
        const url = new URL(username);

        if (
          !/^(?:www\.)?threads\.com$/i.test(
            url.hostname
          )
        ) {
          return "";
        }

        username =
          url.pathname
            .split("/")
            .filter(Boolean)[0] || "";
      } catch (_) {
        return "";
      }
    }

    username = username
      .replace(/^@/, "")
      .replace(/^\/+|\/+$/g, "")
      .toLowerCase();

    if (
      !/^[a-z0-9._]{1,64}$/.test(username) ||
      blockedNames.has(username)
    ) {
      return "";
    }

    return username;
  }

  function currentThreadId() {
    const match = location.pathname.match(
      /^\/messages\/(?:e2ee\/)?t\/([^/?#]+)/
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

  function readStorage(threadId) {
    if (!threadId) {
      return null;
    }

    try {
      const raw = localStorage.getItem(
        storageKey(threadId)
      );

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

  function writeStorage(threadId, value) {
    try {
      localStorage.setItem(
        storageKey(threadId),
        JSON.stringify(value)
      );

      return true;
    } catch (_) {
      return false;
    }
  }

  function removeStorage(threadId) {
    try {
      localStorage.removeItem(
        storageKey(threadId)
      );
    } catch (_) {}
  }

  function randomId() {
    try {
      return crypto.randomUUID();
    } catch (_) {
      return (
        Date.now().toString(36) +
        "-" +
        Math.random().toString(36).slice(2)
      );
    }
  }

  function readSnapshot() {
    const node =
      document.getElementById(SNAPSHOT_ID);

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

  function ownerIdentityValue() {
    try {
      const owner =
        state.adapter?.account?.();

      if (
        owner?.identityType ===
          "threads_username"
      ) {
        return normalizeUsername(
          owner.identityValue
        );
      }

      return clean(
        owner?.identityValue,
        100
      );
    } catch (_) {
      return "";
    }
  }

  function validManualIdentity(threadId) {
    const record =
      readStorage(threadId);

    if (!record) {
      return null;
    }

    const identityValue =
      normalizeUsername(
        record.identityValue
      );

    const valid = Boolean(
      record.schemaVersion === 3 &&
      record.sourceVersion === VERSION &&
      record.platform === "threads" &&
      record.threadId === threadId &&
      record.identityType ===
        "threads_username" &&
      identityValue &&
      record.role ===
        "IS_PARTICIPANT" &&
      record.confirmedByUser === true &&
      clean(record.confirmationId, 200) &&
      Number(record.confirmedAt) > 0
    );

    if (!valid) {
      removeStorage(threadId);
      return null;
    }

    const currentOwner =
      ownerIdentityValue();

    const savedOwner =
      clean(
        record.ownerIdentityValue,
        100
      ).toLowerCase();

    if (
      currentOwner &&
      savedOwner &&
      currentOwner !== savedOwner
    ) {
      return null;
    }

    if (
      currentOwner &&
      identityValue === currentOwner
    ) {
      return null;
    }

    return {
      identityType:
        "threads_username",
      identityValue,
      displayName:
        clean(
          record.displayName ||
          `@${identityValue}`,
          200
        ) || `@${identityValue}`,
      avatarUrl:
        clean(record.avatarUrl, 4096),
      threadId,
      role:
        "IS_PARTICIPANT",
      stable:
        true,
      confidence:
        "high",
      writable:
        true,
      resolution:
        "manual-confirmed",
      confirmedByUser:
        true,
      confirmationId:
        clean(record.confirmationId, 200),
      confirmedAt:
        Number(record.confirmedAt),
      source:
        "threads-user-confirmed-v210318"
    };
  }

  function validAutomaticIdentity(threadId) {
    const snapshot =
      readSnapshot();

    const conversation =
      snapshot?.conversation;

    const identity =
      conversation?.identity;

    if (
      !conversation ||
      !identity ||
      identity.role !== "IS_PARTICIPANT" ||
      identity.stable !== true ||
      identity.confidence !== "high"
    ) {
      return null;
    }

    const snapshotThreadId =
      clean(
        conversation.threadId ||
        snapshot.threadId,
        256
      );

    if (
      snapshotThreadId &&
      snapshotThreadId !== threadId
    ) {
      return null;
    }

    const identityType =
      clean(identity.identityType, 64);

    const rawValue =
      clean(identity.identityValue, 100);

    let identityValue = "";

    if (
      identityType ===
        "threads_username"
    ) {
      identityValue =
        normalizeUsername(rawValue);
    } else if (
      identityType ===
        "threads_user_id" &&
      /^[0-9]{5,30}$/.test(rawValue)
    ) {
      identityValue = rawValue;
    }

    if (!identityValue) {
      return null;
    }

    const owner =
      ownerIdentityValue();

    if (
      owner &&
      identityValue.toLowerCase() ===
        owner.toLowerCase()
    ) {
      return null;
    }

    return {
      identityType,
      identityValue,
      displayName:
        clean(identity.displayName, 200),
      avatarUrl:
        clean(identity.avatarUrl, 4096),
      threadId,
      role:
        "IS_PARTICIPANT",
      stable:
        true,
      confidence:
        "high",
      writable:
        true,
      resolution:
        "auto-verified",
      confirmedByUser:
        false,
      confirmationId: "",
      confirmedAt: 0,
      source:
        "threads-page-probe-v210318"
    };
  }

  function selectedIdentity(threadId) {
    return (
      validManualIdentity(threadId) ||
      validAutomaticIdentity(threadId)
    );
  }

  function originalConversation() {
    try {
      return (
        state.originalConversation?.() ||
        null
      );
    } catch (_) {
      return null;
    }
  }

  function authoritativeConversation() {
    const threadId =
      currentThreadId();

    const original =
      originalConversation();

    if (!threadId) {
      return original;
    }

    const identity =
      selectedIdentity(threadId);

    if (!identity) {
      return {
        ...(original || {}),
        externalConversationId:
          `threads:${threadId}`,
        identityType: "",
        identityValue: "",
        readonly: true,
        reason:
          "联系人稳定平台身份缺失",
        metadata: {
          ...(
            original?.metadata ||
            {}
          ),
          platform:
            "threads",
          threadId,
          stable:
            false,
          writable:
            false,
          role:
            "",
          identityResolution:
            "missing",
          identityAuthorityVersion:
            VERSION
        }
      };
    }

    return {
      ...(original || {}),
      externalConversationId:
        `threads:${threadId}`,
      identityType:
        identity.identityType,
      identityValue:
        identity.identityValue,
      displayName:
        identity.displayName,
      avatarUrl:
        identity.avatarUrl,
      readonly:
        false,
      reason: "",
      metadata: {
        ...(
          original?.metadata ||
          {}
        ),
        platform:
          "threads",
        threadId,
        role:
          "IS_PARTICIPANT",
        stable:
          true,
        writable:
          true,
        confidence:
          "high",
        source:
          identity.source,
        identityResolution:
          identity.resolution,
        confirmedByUser:
          identity.confirmedByUser,
        confirmationId:
          identity.confirmationId,
        confirmedAt:
          identity.confirmedAt,
        identityAuthorityVersion:
          VERSION
      }
    };
  }

  function identitySignature(conversation) {
    return [
      clean(
        conversation?.externalConversationId,
        300
      ),
      clean(
        conversation?.identityType,
        64
      ),
      clean(
        conversation?.identityValue,
        100
      ),
      conversation?.readonly === true
        ? "readonly"
        : "writable",
      clean(
        conversation?.metadata
          ?.identityResolution,
        100
      ),
      clean(
        conversation?.metadata
          ?.confirmationId,
        200
      )
    ].join("|");
  }

  function authoritativeContext() {
    let original = null;

    try {
      original =
        state.originalContext?.() ||
        null;
    } catch (_) {}

    const threadId =
      currentThreadId();

    if (
      !threadId &&
      !original
    ) {
      return null;
    }

    const route =
      clean(
        original?.route ||
        (
          location.pathname +
          location.search +
          location.hash
        ),
        2048
      );

    const conversation =
      authoritativeConversation();

    const identityPart =
      identitySignature(
        conversation
      );

    return {
      ...(original || {}),
      platform:
        "threads",
      route,
      threadId:
        threadId ||
        clean(original?.threadId, 256),
      at:
        Number(original?.at) ||
        Date.now(),
      signature: [
        "threads",
        route,
        threadId,
        identityPart
      ].join("|"),
      contactIdentityRevision:
        identityPart
    };
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

  function publishDiagnostics(reason) {
    const conversation =
      authoritativeConversation();

    ensureMeta(
      DIAGNOSTIC_ID
    ).setAttribute(
      "content",
      JSON.stringify({
        v: 1,
        version: VERSION,
        at: Date.now(),
        installed:
          state.installed,
        reason,
        threadId:
          currentThreadId(),
        manualRecordPresent:
          Boolean(
            readStorage(
              currentThreadId()
            )
          ),
        finalConversation:
          conversation,
        finalWritable:
          Boolean(
            conversation &&
            conversation.readonly === false &&
            conversation.identityType &&
            conversation.identityValue
          )
      })
    );
  }

  function installAdapter() {
    const adapter =
      window.JubaAdapters?.threads;

    if (
      !adapter ||
      typeof adapter.conversation !==
        "function" ||
      typeof adapter.context !==
        "function"
    ) {
      setTimeout(
        installAdapter,
        40
      );
      return;
    }

    if (
      adapter.__identity210318 === true
    ) {
      state.adapter = adapter;
      state.installed = true;
      return;
    }

    state.adapter = adapter;

    state.originalConversation =
      adapter.conversation.bind(adapter);

    state.originalContext =
      adapter.context.bind(adapter);

    state.originalDiagnostics =
      typeof adapter.diagnostics ===
        "function"
        ? adapter.diagnostics.bind(adapter)
        : () => ({});

    adapter.conversation =
      authoritativeConversation;

    adapter.context =
      authoritativeContext;

    adapter.diagnostics = () => {
      let original = {};

      try {
        original =
          state.originalDiagnostics?.() ||
          {};
      } catch (_) {}

      const conversation =
        authoritativeConversation();

      return {
        ...original,
        identityAuthorityVersion:
          VERSION,
        finalIdentityType:
          conversation?.identityType || "",
        finalIdentityValue:
          conversation?.identityValue || "",
        finalReadonly:
          conversation?.readonly === true,
        finalIdentityResolution:
          conversation?.metadata
            ?.identityResolution || "",
        finalStable:
          conversation?.metadata
            ?.stable === true,
        finalWritable:
          conversation?.metadata
            ?.writable === true
      };
    };

    adapter.__identity210318 =
      true;

    state.installed = true;

    publishDiagnostics(
      "ADAPTER_INSTALLED"
    );

    ensureUi();
    updateUi(true);
  }

  function ensureUi() {
    if (
      state.host?.isConnected &&
      state.shadow
    ) {
      return;
    }

    let host =
      document.getElementById(HOST_ID);

    if (!host) {
      host =
        document.createElement("div");

      host.id = HOST_ID;

      host.setAttribute(
        "data-juba-owned",
        "1"
      );

      (
        document.body ||
        document.documentElement
      ).appendChild(host);
    }

    const shadow =
      host.shadowRoot ||
      host.attachShadow({
        mode: "open"
      });

    state.host = host;
    state.shadow = shadow;

    /*
     * DOM 只创建一次。
     * 轮询时只更新 textContent/class/hidden，
     * 绝不再使用 innerHTML 重建输入框。
     */
    shadow.innerHTML = `
      <style>
        :host {
          all: initial;
        }

        *,
        *::before,
        *::after {
          box-sizing: border-box;
        }

        .wrap {
          position: fixed;
          z-index: 2147483646;
          top: 57px;
          right: 8px;
          width: 310px;
          color: #4b2736;
          font: 12px/1.45 system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
        }

        .status {
          width: 100%;
          border: 1px solid #ef9fbd;
          border-radius: 9px;
          background: #fff0f6;
          color: #a21d53;
          padding: 8px 10px;
          text-align: left;
          font-weight: 750;
          cursor: pointer;
          box-shadow: 0 3px 12px #0002;
        }

        .status.ready {
          border-color: #86d6a7;
          background: #effff5;
          color: #166534;
        }

        .editor {
          margin-top: 7px;
          border: 1px solid #e8a1bd;
          border-radius: 10px;
          background: #fffafd;
          padding: 10px;
          box-shadow: 0 8px 30px #0003;
        }

        .editor[hidden] {
          display: none;
        }

        .title {
          color: #8d2857;
          font-weight: 800;
          margin-bottom: 7px;
        }

        .username {
          width: 100%;
          height: 34px;
          border: 1px solid #dda8bd;
          border-radius: 6px;
          padding: 6px 8px;
          background: #fff;
          color: #302028;
          outline: none;
        }

        .username:focus {
          border-color: #d84f88;
          box-shadow: 0 0 0 2px #f7c6da77;
        }

        .check {
          display: flex;
          align-items: flex-start;
          gap: 7px;
          margin: 9px 0;
          color: #684657;
        }

        .actions {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 6px;
        }

        .action {
          border: 1px solid #cf4a80;
          border-radius: 6px;
          background: #df4d89;
          color: #fff;
          padding: 6px 9px;
          font-weight: 700;
          cursor: pointer;
        }

        .secondary {
          border-color: #dbb0c2;
          background: #fff;
          color: #8b3d60;
        }

        .danger {
          border-color: #ef9a9a;
          background: #fff5f5;
          color: #b42318;
        }

        .action:disabled {
          opacity: .55;
          cursor: wait;
        }

        .message {
          margin-top: 8px;
          min-height: 18px;
          color: #067647;
          font-weight: 650;
          overflow-wrap: anywhere;
        }

        .message.error {
          color: #b42318;
        }

        .hint {
          margin-top: 5px;
          color: #866675;
          font-size: 11px;
        }
      </style>

      <div class="wrap">
        <button
          id="status"
          type="button"
          class="status"
        >联系人身份未确认 · 点击确认</button>

        <div
          id="editor"
          class="editor"
          hidden
        >
          <div class="title">
            确认当前聊天联系人
          </div>

          <input
            id="${INPUT_ID}"
            class="username"
            type="text"
            autocomplete="off"
            spellcheck="false"
            placeholder="Threads 用户名，如 linda_fanee"
          >

          <label class="check">
            <input
              id="${CHECKBOX_ID}"
              type="checkbox"
            >
            <span>
              我确认该用户名属于当前聊天对方
            </span>
          </label>

          <div class="actions">
            <button
              id="clear"
              type="button"
              class="action danger"
              hidden
            >清除人工确认</button>

            <button
              id="cancel"
              type="button"
              class="action secondary"
            >取消</button>

            <button
              id="save"
              type="button"
              class="action"
            >确认并重新载入</button>
          </div>

          <div
            id="message"
            class="message"
          ></div>

          <div class="hint">
            输入框不会被轮询重建。保存并回读成功后，页面将重新载入。
          </div>
        </div>
      </div>
    `;

    shadow
      .getElementById("status")
      .addEventListener(
        "click",
        openEditor
      );

    shadow
      .getElementById("cancel")
      .addEventListener(
        "click",
        closeEditor
      );

    shadow
      .getElementById("save")
      .addEventListener(
        "click",
        saveManual
      );

    shadow
      .getElementById("clear")
      .addEventListener(
        "click",
        clearManual
      );
  }

  function message(text, error = false) {
    const element =
      state.shadow?.getElementById(
        "message"
      );

    if (!element) {
      return;
    }

    element.textContent = text;

    element.className =
      error
        ? "message error"
        : "message";
  }

  function openEditor() {
    ensureUi();

    state.editorOpen = true;

    const editor =
      state.shadow.getElementById(
        "editor"
      );

    const input =
      state.shadow.getElementById(
        INPUT_ID
      );

    const checkbox =
      state.shadow.getElementById(
        CHECKBOX_ID
      );

    const manual =
      validManualIdentity(
        currentThreadId()
      );

    editor.hidden = false;

    input.value =
      manual?.identityValue || "";

    checkbox.checked = false;

    message("");

    setTimeout(() => {
      input.focus();
      input.select();
    }, 0);
  }

  function closeEditor() {
    state.editorOpen = false;

    const editor =
      state.shadow?.getElementById(
        "editor"
      );

    if (editor) {
      editor.hidden = true;
    }
  }

  function saveManual() {
    if (state.saving) {
      return;
    }

    const threadId =
      currentThreadId();

    const input =
      state.shadow?.getElementById(
        INPUT_ID
      );

    const checkbox =
      state.shadow?.getElementById(
        CHECKBOX_ID
      );

    const saveButton =
      state.shadow?.getElementById(
        "save"
      );

    const identityValue =
      normalizeUsername(
        input?.value
      );

    if (!threadId) {
      message(
        "当前不是有效的 Threads 私信会话。",
        true
      );
      return;
    }

    if (!identityValue) {
      message(
        "请输入有效的 Threads 用户名。",
        true
      );
      return;
    }

    if (checkbox?.checked !== true) {
      message(
        "请先勾选并确认这是当前聊天对方。",
        true
      );
      return;
    }

    const owner =
      ownerIdentityValue();

    if (
      owner &&
      owner.toLowerCase() ===
        identityValue.toLowerCase()
    ) {
      message(
        "联系人用户名不能与本人身份相同。",
        true
      );
      return;
    }

    state.saving = true;

    saveButton.disabled = true;
    saveButton.textContent =
      "正在保存…";

    const confirmationId =
      randomId();

    const record = {
      schemaVersion: 3,
      sourceVersion:
        VERSION,
      platform:
        "threads",
      threadId,
      identityType:
        "threads_username",
      identityValue,
      displayName:
        `@${identityValue}`,
      avatarUrl: "",
      role:
        "IS_PARTICIPANT",
      stable:
        true,
      confidence:
        "high",
      writable:
        true,
      confirmedByUser:
        true,
      confirmationId,
      confirmedAt:
        Date.now(),
      ownerIdentityValue:
        owner,
      source:
        "threads-user-confirmed-v210318"
    };

    const saved =
      writeStorage(
        threadId,
        record
      );

    const reread =
      readStorage(threadId);

    const verified = Boolean(
      saved &&
      reread?.schemaVersion === 3 &&
      reread?.sourceVersion === VERSION &&
      reread?.threadId === threadId &&
      normalizeUsername(
        reread?.identityValue
      ) === identityValue &&
      reread?.confirmedByUser === true &&
      reread?.confirmationId ===
        confirmationId
    );

    if (!verified) {
      state.saving = false;

      saveButton.disabled = false;
      saveButton.textContent =
        "确认并重新载入";

      message(
        "保存后回读验证失败，身份没有应用。",
        true
      );

      return;
    }

    const conversation =
      authoritativeConversation();

    const adapterVerified = Boolean(
      conversation &&
      conversation.readonly === false &&
      conversation.identityType ===
        "threads_username" &&
      conversation.identityValue ===
        identityValue &&
      conversation.metadata
        ?.identityResolution ===
        "manual-confirmed" &&
      conversation.metadata
        ?.confirmationId ===
        confirmationId
    );

    if (!adapterVerified) {
      removeStorage(threadId);

      state.saving = false;

      saveButton.disabled = false;
      saveButton.textContent =
        "确认并重新载入";

      message(
        "身份已保存，但 Adapter 回读验证失败；记录已撤销。",
        true
      );

      publishDiagnostics(
        "ADAPTER_READBACK_FAILED"
      );

      return;
    }

    publishDiagnostics(
      "MANUAL_IDENTITY_COMMITTED"
    );

    message(
      `已确认 @${identityValue}，正在重新载入建档面板……`
    );

    saveButton.textContent =
      "正在重新载入…";

    /*
     * 刷新后加载顺序为：
     * threads.js
     * -> threads-identity-v210318.js
     * -> chat-panel.js
     * -> bootstrap.js
     *
     * 所以 Chat Panel 首次 mount 前就能读到最终人工身份。
     */
    setTimeout(() => {
      location.reload();
    }, 350);
  }

  function clearManual() {
    const threadId =
      currentThreadId();

    if (!threadId) {
      return;
    }

    removeStorage(threadId);

    publishDiagnostics(
      "MANUAL_IDENTITY_CLEARED"
    );

    message(
      "人工身份已清除，正在重新载入……"
    );

    setTimeout(() => {
      location.reload();
    }, 250);
  }

  function updateUi(force = false) {
    ensureUi();

    const threadId =
      currentThreadId();

    const conversation =
      authoritativeConversation();

    const signature = [
      threadId,
      conversation?.identityType || "",
      conversation?.identityValue || "",
      conversation?.readonly === true
        ? "readonly"
        : "writable",
      conversation?.metadata
        ?.identityResolution || ""
    ].join("|");

    if (
      !force &&
      signature === state.lastStatusSignature
    ) {
      return;
    }

    state.lastStatusSignature =
      signature;

    const status =
      state.shadow?.getElementById(
        "status"
      );

    const clearButton =
      state.shadow?.getElementById(
        "clear"
      );

    if (!status) {
      return;
    }

    const writable = Boolean(
      conversation &&
      conversation.readonly === false &&
      conversation.identityType &&
      conversation.identityValue
    );

    if (writable) {
      const resolution =
        conversation.metadata
          ?.identityResolution;

      const label =
        resolution ===
          "manual-confirmed"
          ? "手动已确认"
          : "自动已验证";

      status.textContent =
        `联系人：@${conversation.identityValue}（${label}）`;

      status.classList.add(
        "ready"
      );
    } else {
      status.textContent =
        "联系人身份未确认 · 点击确认";

      status.classList.remove(
        "ready"
      );
    }

    if (clearButton) {
      clearButton.hidden =
        !validManualIdentity(threadId);
    }

    /*
     * 注意：
     * 此处绝不修改输入框 value 和 checkbox.checked。
     * 用户编辑期间不会被定时器清空。
     */
  }

  function watchRoute() {
    const threadId =
      currentThreadId();

    if (
      threadId !== state.lastThreadId
    ) {
      state.lastThreadId = threadId;
      state.lastStatusSignature = "";

      if (state.editorOpen) {
        closeEditor();
      }

      updateUi(true);
      publishDiagnostics(
        "THREAD_CHANGED"
      );
    } else {
      updateUi(false);
    }
  }

  function start() {
    installAdapter();

    state.routeTimer =
      setInterval(
        watchRoute,
        500
      );
  }

  start();

  window.addEventListener(
    "pagehide",
    () => {
      clearInterval(
        state.routeTimer
      );
      clearTimeout(
        state.timer
      );
    },
    {
      once: true
    }
  );
})();
