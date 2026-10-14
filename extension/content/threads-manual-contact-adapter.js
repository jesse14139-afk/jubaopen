"use strict";

/*
 * JUBAOPEN_THREADS_MANUAL_CONTACT_ADAPTER_210_3_10
 *
 * 运行于 Chrome 扩展 ISOLATED world。
 *
 * MAIN world 的 threads-manual-contact.js 将用户确认的联系人
 * 写入共享 DOM Bridge；本文件在 Adapter 和 Chat Panel 之间
 * 加载，负责把该身份加入权威 Adapter 链路。
 *
 * 本版本不会触发页面重新载入。
 */
(() => {
  if (
    window.__jubaThreadsManualContactAdapter210310
  ) {
    return;
  }

  window.__jubaThreadsManualContactAdapter210310 =
    true;

  const VERSION = "210.3.10";

  const BRIDGE_ID =
    "jubaopen-threads-manual-contact-v210305";

  const DIAGNOSTIC_ID =
    "jubaopen-threads-adapter-diagnostics-v210310";

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

  const clean = (value, max = 4096) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .replace(
        /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g,
        ""
      )
      .trim()
      .slice(0, max);

  function normalizeUsername(value) {
    const username = clean(value, 100)
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

  function readBridge() {
    const node =
      document.getElementById(BRIDGE_ID);

    if (!node) {
      return {
        ok: false,
        reason: "BRIDGE_NODE_MISSING",
        payload: null
      };
    }

    let payload = null;

    try {
      payload = JSON.parse(
        node.getAttribute("content") || "{}"
      );
    } catch (error) {
      return {
        ok: false,
        reason: "BRIDGE_JSON_INVALID",
        error: String(error),
        payload: null
      };
    }

    if (
      !payload ||
      payload.v !== 1 ||
      payload.platform !== "threads"
    ) {
      return {
        ok: false,
        reason: "BRIDGE_PAYLOAD_INVALID",
        payload
      };
    }

    /*
     * 不再使用五秒 MAX_AGE。
     *
     * Bridge 是否适用于当前页面，只由当前 threadId 与记录中的
     * threadId 是否完全相同决定。
     */
    return {
      ok: true,
      reason: "",
      payload
    };
  }

  function readManualIdentity() {
    const threadId =
      currentThreadId();

    if (!threadId) {
      return {
        identity: null,
        reason: "CURRENT_THREAD_ID_MISSING"
      };
    }

    const bridge = readBridge();

    if (!bridge.ok) {
      return {
        identity: null,
        reason: bridge.reason
      };
    }

    const payload =
      bridge.payload;

    const bridgedThreadId = clean(
      payload.threadId,
      256
    );

    if (
      !bridgedThreadId ||
      bridgedThreadId !== threadId
    ) {
      return {
        identity: null,
        reason: "THREAD_ID_MISMATCH",
        currentThreadId: threadId,
        bridgedThreadId
      };
    }

    const source =
      payload.identity;

    if (!source) {
      return {
        identity: null,
        reason: "MANUAL_IDENTITY_EMPTY"
      };
    }

    const username =
      normalizeUsername(
        source.identityValue
      );

    if (!username) {
      return {
        identity: null,
        reason: "MANUAL_USERNAME_INVALID"
      };
    }

    if (
      source.identityType !==
        "threads_username" ||
      source.role !==
        "IS_PARTICIPANT" ||
      source.stable !== true ||
      source.confidence !== "high" ||
      source.confirmedByUser !== true ||
      clean(source.threadId, 256) !== threadId
    ) {
      return {
        identity: null,
        reason: "MANUAL_IDENTITY_NOT_CONFIRMED",
        flags: {
          identityType:
            source.identityType,
          role:
            source.role,
          stable:
            source.stable,
          confidence:
            source.confidence,
          confirmedByUser:
            source.confirmedByUser,
          identityThreadId:
            source.threadId
        }
      };
    }

    return {
      reason: "MANUAL_CONFIRMED",
      identity: {
        identityType:
          "threads_username",
        identityValue:
          username,
        displayName: clean(
          source.displayName ||
          `@${username}`,
          200
        ),
        avatarUrl: clean(
          source.avatarUrl,
          4096
        ),
        role:
          "IS_PARTICIPANT",
        stable:
          true,
        confidence:
          "high",
        confirmedByUser:
          true,
        manuallyConfirmed:
          true,
        source:
          "threads-user-confirmed-manual-contact",
        threadId,
        savedAt:
          Number(source.savedAt) || 0
      }
    };
  }

  function ensureDiagnosticNode() {
    let node =
      document.getElementById(
        DIAGNOSTIC_ID
      );

    if (!node) {
      node =
        document.createElement("meta");

      node.id =
        DIAGNOSTIC_ID;

      node.hidden = true;

      (
        document.head ||
        document.documentElement
      ).appendChild(node);
    }

    return node;
  }

  function publishDiagnostic(extra = {}) {
    const adapter =
      window.JubaAdapters?.threads;

    const manual =
      readManualIdentity();

    let context = null;
    let conversation = null;
    let diagnostics = null;

    try {
      context =
        adapter?.context?.() || null;
    } catch (error) {
      context = {
        error: String(error)
      };
    }

    try {
      conversation =
        adapter?.conversation?.() || null;
    } catch (error) {
      conversation = {
        error: String(error)
      };
    }

    try {
      diagnostics =
        adapter?.diagnostics?.() || null;
    } catch (error) {
      diagnostics = {
        error: String(error)
      };
    }

    const payload = {
      v: 1,
      version: VERSION,
      at: Date.now(),
      patchInstalled:
        Boolean(
          adapter?.__manualContact210310
        ),
      pageReloadMechanism:
        "disabled",
      currentThreadId:
        currentThreadId(),
      bridgeFound:
        Boolean(
          document.getElementById(
            BRIDGE_ID
          )
        ),
      manualContactFound:
        Boolean(manual.identity),
      manualContactReason:
        manual.reason,
      manualIdentityValue:
        manual.identity
          ?.identityValue || "",
      context,
      conversation,
      diagnostics,
      ...extra
    };

    const node =
      ensureDiagnosticNode();

    node.setAttribute(
      "content",
      JSON.stringify(payload)
    );

    node.setAttribute(
      "data-updated-at",
      String(payload.at)
    );
  }

  function install() {
    const adapter =
      window.JubaAdapters?.threads;

    if (
      !adapter ||
      typeof adapter.context !==
        "function" ||
      typeof adapter.conversation !==
        "function"
    ) {
      setTimeout(install, 50);
      return;
    }

    if (
      adapter.__manualContact210310 === true
    ) {
      publishDiagnostic({
        installState: "ALREADY_INSTALLED"
      });
      return;
    }

    const originalContext =
      adapter.context.bind(adapter);

    const originalConversation =
      adapter.conversation.bind(adapter);

    const originalDiagnostics =
      typeof adapter.diagnostics ===
        "function"
        ? adapter.diagnostics.bind(adapter)
        : () => ({
            platform: "threads"
          });

    adapter.context = () => {
      let original = null;

      try {
        original =
          originalContext();
      } catch (_) {}

      const manualResult =
        readManualIdentity();

      const manual =
        manualResult.identity;

      if (!manual) {
        return original;
      }

      const route = clean(
        original?.route ||
        (
          location.pathname +
          location.search +
          location.hash
        ),
        2048
      );

      const revision = [
        "manual-confirmed",
        manual.identityType,
        manual.identityValue,
        String(manual.savedAt || 0)
      ].join(":");

      return {
        ...(original || {}),
        platform:
          "threads",
        route,
        threadId:
          manual.threadId,
        sequence:
          Number.isSafeInteger(
            Number(original?.sequence)
          )
            ? Number(original.sequence)
            : 0,
        generation:
          Number(original?.generation) || 0,
        at:
          Number(original?.at) ||
          Date.now(),
        signature: [
          "threads",
          route,
          manual.threadId,
          revision
        ].join("|"),
        contactIdentityRevision:
          revision
      };
    };

    adapter.conversation = () => {
      const manualResult =
        readManualIdentity();

      const manual =
        manualResult.identity;

      /*
       * 当前 threadId 的用户确认身份优先于自动 DOM 推断。
       */
      if (manual) {
        return {
          externalConversationId:
            "threads:" +
            manual.threadId,
          identityType:
            manual.identityType,
          identityValue:
            manual.identityValue,
          displayName:
            manual.displayName,
          avatarUrl:
            manual.avatarUrl,
          readonly:
            false,
          reason:
            "",
          metadata: {
            source:
              manual.source,
            confidence:
              "high",
            stable:
              true,
            confirmedByUser:
              true,
            manuallyConfirmed:
              true,
            identityResolution:
              "manual-confirmed",
            threadId:
              manual.threadId,
            savedAt:
              manual.savedAt,
            adapterPatchVersion:
              VERSION
          }
        };
      }

      try {
        return originalConversation();
      } catch (_) {
        return null;
      }
    };

    adapter.diagnostics = () => {
      let original = {};

      try {
        original =
          originalDiagnostics() || {};
      } catch (_) {}

      const manualResult =
        readManualIdentity();

      let finalConversation = null;
      let finalContext = null;

      try {
        finalConversation =
          adapter.conversation();
      } catch (_) {}

      try {
        finalContext =
          adapter.context();
      } catch (_) {}

      return {
        ...original,
        adapterPatchVersion:
          VERSION,
        fixMarker:
          "JUBAOPEN_THREADS_MANUAL_CONTACT_ADAPTER_210_3_10",
        pageReloadMechanism:
          "disabled",
        manualContactFound:
          Boolean(
            manualResult.identity
          ),
        manualContactReason:
          manualResult.reason,
        manualIdentityValue:
          manualResult.identity
            ?.identityValue || "",
        finalConversationWritable:
          Boolean(
            finalConversation &&
            finalConversation.readonly !== true &&
            finalConversation.identityType &&
            finalConversation.identityValue
          ),
        finalIdentityValue:
          finalConversation
            ?.identityValue || "",
        finalIdentityResolution:
          finalConversation
            ?.metadata
            ?.identityResolution || "",
        contextSignature:
          finalContext
            ?.signature || ""
      };
    };

    adapter.__manualContact210310 =
      true;

    publishDiagnostic({
      installState: "INSTALLED"
    });
  }

  /*
   * 身份变化时只更新诊断。
   * 禁止刷新页面，Adapter 会在下一次调用时动态读取 Bridge。
   */
  function manualIdentityChanged() {
    publishDiagnostic({
      installState:
        "MANUAL_IDENTITY_CHANGED",
      reloadRequested:
        false
    });
  }

  window.addEventListener(
    "jubaopen:threads-manual-contact",
    manualIdentityChanged
  );

  window.addEventListener(
    "jubaopen:threads-contact-identity-changed",
    manualIdentityChanged
  );

  install();

  setInterval(() => {
    publishDiagnostic({
      installState:
        window.JubaAdapters
          ?.threads
          ?.__manualContact210310
          ? "INSTALLED"
          : "WAITING"
    });
  }, 1000);
})();
