"use strict";

/*
 * JUBAOPEN_THREADS_MANUAL_CONTACT_210_3_5
 *
 * 当 Threads 无法从稳定 DOM 自动识别聊天对方时，允许用户按当前
 * threadId 明确输入并确认联系人 Threads 用户名。
 *
 * 记录按会话保存，不会自动应用到其他会话。
 * 不读取密码、Cookie、Token 或其他登录凭据。
 */
(() => {
  if (window.__jubaThreadsManualContact210305) {
    return;
  }

  window.__jubaThreadsManualContact210305 = true;

  const VERSION = "210.3.5";

  const SNAPSHOT_ID =
    "jubaopen-threads-page-snapshot-v1";

  const BRIDGE_ID =
    "jubaopen-threads-manual-contact-v210305";

  const HOST_ID =
    "jubaopen-threads-manual-contact-host";

  const OWNER_SESSION_KEY =
    "jubaopen.threads.ownerIdentity.v210301";

  const STORAGE_PREFIX =
    "jubaopen.threads.manualContact.v210305.";

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

  let host = null;
  let shadow = null;
  let statusButton = null;
  let missingSince = 0;
  let lastStatus = "";
  let lastRoute = "";

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

    if (!match) return "";

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

  function readJson(storage, key) {
    try {
      const raw = storage.getItem(key);

      if (!raw) return null;

      const parsed = JSON.parse(raw);

      return (
        parsed &&
        typeof parsed === "object"
      ) ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function writeJson(storage, key, value) {
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

  function removeKey(storage, key) {
    try {
      storage.removeItem(key);
    } catch (_) {}
  }

  function ownerUsername() {
    const owner = readJson(
      sessionStorage,
      OWNER_SESSION_KEY
    );

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

  function readSnapshot() {
    const node =
      document.getElementById(SNAPSHOT_ID);

    if (!node) return null;

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

  function automaticContact() {
    const identity =
      readSnapshot()?.conversation?.identity;

    if (
      !identity ||
      identity.role !== "IS_PARTICIPANT"
    ) {
      return null;
    }

    const identityValue =
      normalizeUsername(
        identity.identityValue
      );

    if (!identityValue) return null;

    const owner = ownerUsername();

    if (
      owner &&
      identityValue === owner
    ) {
      return null;
    }

    return {
      ...identity,
      identityValue
    };
  }

  function readManualContact(threadId) {
    if (!threadId) return null;

    const record = readJson(
      localStorage,
      storageKey(threadId)
    );

    if (!record) return null;

    const identityValue =
      normalizeUsername(
        record.identityValue
      );

    if (
      !identityValue ||
      record.confirmedByUser !== true ||
      record.threadId !== threadId
    ) {
      removeKey(
        localStorage,
        storageKey(threadId)
      );

      return null;
    }

    return {
      identityType: "threads_username",
      identityValue,
      displayName: clean(
        record.displayName ||
        `@${identityValue}`,
        200
      ),
      avatarUrl: "",
      profileUrl:
        `https://www.threads.com/@${identityValue}`,
      role: "IS_PARTICIPANT",
      stable: true,
      confidence: "high",
      source:
        "threads-user-confirmed-manual-contact",
      threadId,
      confirmedByUser: true,
      savedAt: Number(record.savedAt) || 0,
      version: VERSION
    };
  }

  function saveManualContact(
    threadId,
    value
  ) {
    const identityValue =
      normalizeUsername(value);

    if (!threadId || !identityValue) {
      return null;
    }

    const owner = ownerUsername();

    if (
      owner &&
      identityValue === owner
    ) {
      return {
        error: "CONTACT_EQUALS_OWNER"
      };
    }

    const record = {
      identityType: "threads_username",
      identityValue,
      displayName: `@${identityValue}`,
      profileUrl:
        `https://www.threads.com/@${identityValue}`,
      role: "IS_PARTICIPANT",
      stable: true,
      confidence: "high",
      source:
        "threads-user-confirmed-manual-contact",
      threadId,
      confirmedByUser: true,
      savedAt: Date.now(),
      version: VERSION
    };

    if (
      !writeJson(
        localStorage,
        storageKey(threadId),
        record
      )
    ) {
      return null;
    }

    publishBridge();
    return record;
  }

  function clearManualContact(threadId) {
    if (!threadId) return;

    removeKey(
      localStorage,
      storageKey(threadId)
    );

    publishBridge();
  }

  function ensureBridgeNode() {
    let node =
      document.getElementById(BRIDGE_ID);

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

  function publishBridge() {
    const node = ensureBridgeNode();
    const threadId = currentThreadId();
    const manual = readManualContact(threadId);

    const payload = {
      v: 1,
      platform: "threads",
      version: VERSION,
      at: Date.now(),
      threadId,
      identity: manual
    };

    node.setAttribute(
      "content",
      JSON.stringify(payload)
    );

    node.setAttribute(
      "data-updated-at",
      String(payload.at)
    );

    try {
      window.dispatchEvent(
        new CustomEvent(
          "jubaopen:threads-manual-contact",
          {
            detail: {
              threadId,
              available: Boolean(manual)
            }
          }
        )
      );
    } catch (_) {}
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[character]
    );
  }

  function createInterface() {
    if (
      host ||
      !document.body
    ) {
      return;
    }

    host = document.createElement("div");
    host.id = HOST_ID;

    Object.assign(host.style, {
      position: "fixed",
      right: "16px",
      top: "90px",
      zIndex: "2147483647",
      width: "auto",
      height: "auto",
      margin: "0",
      padding: "0"
    });

    shadow = host.attachShadow({
      mode: "open"
    });

    shadow.innerHTML = `
      <style>
        :host {
          all: initial;
        }

        * {
          box-sizing: border-box;
        }

        .status {
          min-height: 34px;
          max-width: 350px;
          padding: 7px 12px;
          border: 1px solid #d94d89;
          border-radius: 18px;
          background: #fff5fa;
          color: #8c2754;
          box-shadow:
            0 7px 24px rgba(76,17,44,.26);
          font: 700 12px/1.35
            system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
          cursor: pointer;
        }

        .status:hover {
          background: #ffe5f1;
        }

        .status.ok {
          border-color: #329565;
          background: #effff6;
          color: #17613d;
        }

        .overlay {
          position: fixed;
          inset: 0;
          z-index: 2147483647;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 18px;
          background: rgba(22,8,15,.55);
        }

        .dialog {
          width: 420px;
          max-width: calc(100vw - 30px);
          padding: 20px;
          border: 1px solid #e094b6;
          border-radius: 16px;
          background: #fffafd;
          color: #39232e;
          box-shadow:
            0 24px 80px rgba(35,8,22,.42);
          font: 13px/1.55
            system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
        }

        h2 {
          margin: 0 0 10px;
          color: #8d2d58;
          font-size: 18px;
        }

        p {
          margin: 8px 0;
        }

        .warning {
          padding: 9px 10px;
          border-radius: 8px;
          background: #fff0f6;
          color: #77334f;
        }

        .thread {
          padding: 7px 9px;
          border-radius: 7px;
          background: #f7f1f4;
          color: #735766;
          overflow-wrap: anywhere;
          font-size: 11px;
        }

        label.title {
          display: block;
          margin-top: 14px;
          font-weight: 700;
        }

        input[type="text"] {
          width: 100%;
          height: 39px;
          margin-top: 6px;
          padding: 0 11px;
          border: 1px solid #d486aa;
          border-radius: 8px;
          outline: none;
          background: #fff;
          color: #2e1a24;
          font: 14px
            system-ui,
            -apple-system,
            "Segoe UI",
            sans-serif;
        }

        input[type="text"]:focus {
          border-color: #bd3b76;
          box-shadow:
            0 0 0 3px rgba(189,59,118,.13);
        }

        .confirm {
          display: flex;
          gap: 8px;
          align-items: flex-start;
          margin-top: 12px;
        }

        .confirm input {
          flex: none;
          width: 16px;
          height: 16px;
          margin: 2px 0 0;
        }

        .error {
          min-height: 20px;
          margin-top: 5px;
          color: #bf234e;
          font-size: 12px;
        }

        .buttons {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 16px;
        }

        button {
          min-height: 34px;
          padding: 0 13px;
          border: 1px solid #d387a9;
          border-radius: 8px;
          background: #fff;
          color: #823052;
          font: 700 12px
            system-ui,
            -apple-system,
            "Segoe UI",
            "Microsoft YaHei",
            sans-serif;
          cursor: pointer;
        }

        button:hover {
          background: #fff0f7;
        }

        button.primary {
          border-color: #bd3b76;
          background: #bd3b76;
          color: #fff;
        }

        button.danger {
          margin-right: auto;
          border-color: #d25868;
          color: #a32134;
        }

        button:disabled {
          opacity: .48;
          cursor: not-allowed;
        }
      </style>

      <button
        id="statusButton"
        type="button"
        class="status"
      >
        设置 Threads 联系人身份
      </button>

      <div id="dialogContainer"></div>
    `;

    statusButton =
      shadow.getElementById(
        "statusButton"
      );

    statusButton.addEventListener(
      "click",
      openDialog
    );

    document.body.appendChild(host);
    renderStatus();
  }

  function closeDialog() {
    const container =
      shadow?.getElementById(
        "dialogContainer"
      );

    if (container) {
      container.textContent = "";
    }
  }

  function openDialog() {
    if (!shadow) return;

    const threadId = currentThreadId();

    if (!threadId) {
      window.alert(
        "请先打开一个具体的 Threads 聊天会话。"
      );
      return;
    }

    const manual =
      readManualContact(threadId);

    const automatic =
      automaticContact();

    const defaultValue =
      manual?.identityValue ||
      automatic?.identityValue ||
      "";

    const container =
      shadow.getElementById(
        "dialogContainer"
      );

    container.innerHTML = `
      <div
        id="manualContactOverlay"
        class="overlay"
      >
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="manualContactTitle"
        >
          <h2 id="manualContactTitle">
            设置当前会话联系人身份
          </h2>

          <p>
            自动识别失败时，请输入当前聊天对方的
            Threads 用户名。
          </p>

          <p class="warning">
            这里填写的是聊天对方，不是你自己的用户名。
            该身份只绑定到当前会话。错误输入可能导致客户
            关联到错误身份。
          </p>

          <p class="thread">
            当前 threadId：
            ${escapeHtml(threadId)}
          </p>

          <label
            class="title"
            for="manualContactUsername"
          >
            联系人 Threads 用户名
          </label>

          <input
            id="manualContactUsername"
            type="text"
            autocomplete="off"
            spellcheck="false"
            placeholder="@contact_name 或个人资料网址"
            value="${escapeHtml(defaultValue)}"
          >

          <div
            id="manualContactError"
            class="error"
          ></div>

          <label class="confirm">
            <input
              id="manualContactConfirm"
              type="checkbox"
            >
            <span>
              我确认这是当前聊天对方的 Threads 用户名，
              不是本人账号。
            </span>
          </label>

          <div class="buttons">
            <button
              id="manualContactClear"
              type="button"
              class="danger"
            >
              清除本会话身份
            </button>

            <button
              id="manualContactCancel"
              type="button"
            >
              取消
            </button>

            <button
              id="manualContactSave"
              type="button"
              class="primary"
            >
              保存并重新识别
            </button>
          </div>
        </div>
      </div>
    `;

    const input =
      shadow.getElementById(
        "manualContactUsername"
      );

    const confirmation =
      shadow.getElementById(
        "manualContactConfirm"
      );

    const error =
      shadow.getElementById(
        "manualContactError"
      );

    const save =
      shadow.getElementById(
        "manualContactSave"
      );

    const clear =
      shadow.getElementById(
        "manualContactClear"
      );

    clear.disabled = !manual;

    shadow
      .getElementById(
        "manualContactCancel"
      )
      .addEventListener(
        "click",
        closeDialog
      );

    shadow
      .getElementById(
        "manualContactOverlay"
      )
      .addEventListener(
        "click",
        event => {
          if (
            event.target?.id ===
            "manualContactOverlay"
          ) {
            closeDialog();
          }
        }
      );

    clear.addEventListener(
      "click",
      () => {
        if (
          !window.confirm(
            "确定清除当前会话手动设置的联系人身份吗？"
          )
        ) {
          return;
        }

        clearManualContact(threadId);
        closeDialog();

        setTimeout(
          () => location.reload(),
          120
        );
      }
    );

    save.addEventListener(
      "click",
      () => {
        error.textContent = "";

        const identityValue =
          normalizeUsername(input.value);

        if (!identityValue) {
          error.textContent =
            "联系人用户名格式无效。请输入 @用户名，" +
            "或完整的 Threads 个人资料网址。";

          input.focus();
          return;
        }

        const owner = ownerUsername();

        if (
          owner &&
          identityValue === owner
        ) {
          error.textContent =
            "联系人用户名不能与本人用户名相同。";
          input.focus();
          return;
        }

        if (!confirmation.checked) {
          error.textContent =
            "请先确认这是当前聊天对方的用户名。";

          confirmation.focus();
          return;
        }

        const result = saveManualContact(
          threadId,
          identityValue
        );

        if (
          result?.error ===
          "CONTACT_EQUALS_OWNER"
        ) {
          error.textContent =
            "联系人用户名不能与本人用户名相同。";
          return;
        }

        if (!result) {
          error.textContent =
            "保存失败，浏览器可能禁止了本地存储。";
          return;
        }

        save.disabled = true;
        save.textContent =
          "已保存，正在刷新……";

        setTimeout(
          () => location.reload(),
          160
        );
      }
    );

    setTimeout(
      () => {
        input.focus();
        input.select();
      },
      0
    );
  }

  function renderStatus() {
    if (!statusButton) return;

    const threadId = currentThreadId();

    if (!threadId) {
      statusButton.hidden = true;
      missingSince = 0;
      return;
    }

    const automatic =
      automaticContact();

    const manual =
      readManualContact(threadId);

    if (automatic) {
      missingSince = 0;

      const text =
        `联系人：@${automatic.identityValue}` +
        "（自动）";

      if (lastStatus !== text) {
        statusButton.textContent =
          text + " · 点击核对";

        statusButton.className =
          "status ok";

        lastStatus = text;
      }

      statusButton.hidden = false;
      return;
    }

    if (manual) {
      missingSince = 0;

      const text =
        `联系人：@${manual.identityValue}` +
        "（手动）";

      if (lastStatus !== text) {
        statusButton.textContent =
          text + " · 点击修改";

        statusButton.className =
          "status ok";

        lastStatus = text;
      }

      statusButton.hidden = false;
      return;
    }

    if (!missingSince) {
      missingSince = Date.now();
    }

    if (
      Date.now() - missingSince < 2500
    ) {
      statusButton.hidden = true;
      return;
    }

    const text =
      "联系人身份缺失 · 点击手动设置";

    if (lastStatus !== text) {
      statusButton.textContent = text;
      statusButton.className = "status";
      lastStatus = text;
    }

    statusButton.hidden = false;
  }

  function routeTick() {
    const route =
      location.pathname +
      location.search +
      location.hash;

    if (route !== lastRoute) {
      lastRoute = route;
      missingSince = 0;
      lastStatus = "";
    }

    publishBridge();
    renderStatus();
  }

  function start() {
    if (
      !/^(?:www\.)?threads\.com$/i.test(
        location.hostname
      )
    ) {
      return;
    }

    publishBridge();

    if (document.body) {
      createInterface();
    } else {
      document.addEventListener(
        "DOMContentLoaded",
        createInterface,
        { once: true }
      );
    }

    setInterval(
      () => {
        publishBridge();

        if (!host || !host.isConnected) {
          host = null;
          shadow = null;
          statusButton = null;
          createInterface();
        }

        routeTick();
      },
      1000
    );
  }

  start();
})();
