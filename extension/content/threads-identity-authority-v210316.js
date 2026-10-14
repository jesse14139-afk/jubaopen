"use strict";

/*
 * JUBAOPEN_THREADS_IDENTITY_AUTHORITY_210_3_16
 *
 * 运行于 Chrome 扩展 ISOLATED world。
 *
 * 本层是 Threads 建档身份的最终权威入口：
 *
 * 1. 直接读取 210.3.16 单一身份 Bridge；
 * 2. 人工确认身份拥有最高优先级；
 * 3. 返回 readonly:false 的标准 conversation；
 * 4. 将身份修订加入 context.signature；
 * 5. 写入 MAIN world 可读取的应用回执；
 * 6. 身份变化时通知 Bootstrap 重新 resolve(true)；
 * 7. Bridge 无有效身份时安全回退 210.3.15 原结果。
 */
(() => {
  if (window.__jubaThreadsIdentityAuthority210316) {
    return;
  }

  window.__jubaThreadsIdentityAuthority210316 = true;

  const VERSION = "210.3.16";

  const BRIDGE_ID =
    "jubaopen-threads-contact-identity-v210316";

  const ACK_ID =
    "jubaopen-threads-contact-identity-ack-v210316";

  const DIAGNOSTIC_ID =
    "jubaopen-threads-identity-diagnostics-v210316";

  const EVENT_NAME =
    "jubaopen:threads-authoritative-identity-changed";

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

  let installTimer = 0;
  let pollTimer = 0;
  let observer = null;
  let installed = false;
  let previousSignature = "";
  let eventCount = 0;

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

  function readAuthority() {
    const threadId =
      currentThreadId();

    const payload =
      readMeta(BRIDGE_ID);

    if (
      !threadId ||
      payload?.v !== 2 ||
      payload?.platform !== "threads" ||
      clean(payload.threadId, 256) !== threadId
    ) {
      return {
        payload,
        identity: null,
        reason: "BRIDGE_NOT_APPLICABLE"
      };
    }

    if (payload.status === "conflict") {
      return {
        payload,
        identity: null,
        reason: "IDENTITY_CONFLICT"
      };
    }

    const selected =
      payload.selected;

    if (
      !selected ||
      selected.identityType !==
        "threads_username" ||
      selected.role !==
        "IS_PARTICIPANT" ||
      selected.stable !== true ||
      selected.confidence !== "high" ||
      selected.writable !== true ||
      clean(selected.threadId, 256) !==
        threadId
    ) {
      return {
        payload,
        identity: null,
        reason: "SELECTED_IDENTITY_INVALID"
      };
    }

    const identityValue =
      normalizeUsername(
        selected.identityValue
      );

    if (!identityValue) {
      return {
        payload,
        identity: null,
        reason: "SELECTED_USERNAME_INVALID"
      };
    }

    const resolution =
      clean(selected.resolution, 100);

    if (
      resolution !== "manual-confirmed" &&
      resolution !== "auto-verified" &&
      resolution !== "probe-auto-verified"
    ) {
      return {
        payload,
        identity: null,
        reason: "RESOLUTION_INVALID"
      };
    }

    if (
      resolution === "manual-confirmed" &&
      selected.confirmedByUser !== true
    ) {
      return {
        payload,
        identity: null,
        reason: "MANUAL_CONFIRMATION_MISSING"
      };
    }

    return {
      payload,
      reason: "ACCEPTED",
      identity: {
        identityType:
          "threads_username",
        identityValue,
        displayName:
          clean(
            selected.displayName ||
            `@${identityValue}`,
            200
          ) || `@${identityValue}`,
        avatarUrl:
          clean(selected.avatarUrl, 4096),
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
          clean(selected.source, 200),
        confirmedByUser:
          selected.confirmedByUser === true,
        automaticallyVerified:
          selected.automaticallyVerified === true,
        savedAt:
          Number(selected.savedAt) || 0,
        revision:
          Number(payload.revision) || 0,
        evidence:
          selected.evidence &&
          typeof selected.evidence === "object"
            ? selected.evidence
            : {}
      }
    };
  }

  function authorityConversation() {
    const result =
      readAuthority();

    const identity =
      result.identity;

    if (!identity) {
      return null;
    }

    return {
      externalConversationId:
        "threads:" +
        identity.threadId,
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
      reason:
        "",
      metadata: {
        source:
          identity.source,
        confidence:
          "high",
        stable:
          true,
        writable:
          true,
        role:
          "IS_PARTICIPANT",
        threadId:
          identity.threadId,
        identityResolution:
          identity.resolution,
        confirmedByUser:
          identity.confirmedByUser,
        manuallyConfirmed:
          identity.resolution ===
            "manual-confirmed",
        automaticallyVerified:
          identity.automaticallyVerified,
        savedAt:
          identity.savedAt,
        identityRevision:
          identity.revision,
        evidence:
          identity.evidence,
        authorityVersion:
          VERSION
      }
    };
  }

  function conversationSignature(
    conversation
  ) {
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
      ).toLowerCase(),
      conversation?.readonly === true
        ? "readonly"
        : "writable",
      clean(
        conversation?.metadata
          ?.identityResolution,
        100
      ),
      Number(
        conversation?.metadata
          ?.identityRevision
      ) || 0,
      clean(conversation?.reason, 300)
    ].join("|");
  }

  function writeAck(conversation) {
    if (
      !conversation ||
      conversation.readonly === true ||
      !conversation.identityValue
    ) {
      return;
    }

    const payload = {
      v: 1,
      version: VERSION,
      platform: "threads",
      accepted: true,
      at: Date.now(),
      threadId:
        currentThreadId(),
      identityType:
        conversation.identityType,
      identityValue:
        conversation.identityValue,
      resolution:
        conversation.metadata
          ?.identityResolution || "",
      revision:
        Number(
          conversation.metadata
            ?.identityRevision
        ) || 0
    };

    ensureMeta(ACK_ID).setAttribute(
      "content",
      JSON.stringify(payload)
    );
  }

  function ensureDiagnostic() {
    return ensureMeta(DIAGNOSTIC_ID);
  }

  function publishDiagnostic(reason = "") {
    const adapter =
      window.JubaAdapters?.threads;

    let conversation = null;
    let context = null;

    try {
      conversation =
        adapter?.conversation?.() || null;
    } catch (error) {
      conversation = {
        error: String(error)
      };
    }

    try {
      context =
        adapter?.context?.() || null;
    } catch (error) {
      context = {
        error: String(error)
      };
    }

    const authority =
      readAuthority();

    ensureDiagnostic().setAttribute(
      "content",
      JSON.stringify({
        v: 1,
        version: VERSION,
        at: Date.now(),
        installed,
        reason,
        eventCount,
        threadId:
          currentThreadId(),
        authorityReason:
          authority.reason,
        bridgeStatus:
          authority.payload?.status || "",
        bridgeRevision:
          Number(
            authority.payload?.revision
          ) || 0,
        acceptedIdentity:
          authority.identity,
        finalConversation:
          conversation,
        finalContext:
          context,
        finalWritable:
          Boolean(
            conversation &&
            conversation.readonly !== true &&
            conversation.identityType &&
            conversation.identityValue
          )
      })
    );
  }

  function install() {
    const adapter =
      window.JubaAdapters?.threads;

    if (
      !adapter ||
      typeof adapter.conversation !==
        "function" ||
      typeof adapter.context !==
        "function"
    ) {
      clearTimeout(installTimer);

      installTimer = setTimeout(
        install,
        50
      );

      return;
    }

    if (
      adapter.__identityAuthority210316 ===
        true
    ) {
      installed = true;
      return;
    }

    const previousConversation =
      adapter.conversation.bind(adapter);

    const previousContext =
      adapter.context.bind(adapter);

    const previousDiagnostics =
      typeof adapter.diagnostics ===
        "function"
        ? adapter.diagnostics.bind(adapter)
        : () => ({
            platform: "threads"
          });

    adapter.conversation = () => {
      const authoritative =
        authorityConversation();

      if (authoritative) {
        writeAck(authoritative);
        return authoritative;
      }

      try {
        return previousConversation();
      } catch (_) {
        return null;
      }
    };

    adapter.context = () => {
      let original = null;

      try {
        original =
          previousContext();
      } catch (_) {}

      const conversation =
        adapter.conversation();

      if (
        !original &&
        !conversation
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

      const threadId =
        currentThreadId() ||
        clean(original?.threadId, 256);

      const identityRevision =
        conversationSignature(
          conversation
        );

      return {
        ...(original || {}),
        platform:
          "threads",
        route,
        threadId,
        sequence:
          Number.isSafeInteger(
            Number(original?.sequence)
          )
            ? Number(original.sequence)
            : 0,
        generation:
          Number(original?.generation) ||
          0,
        at:
          Number(original?.at) ||
          Date.now(),
        signature: [
          "threads",
          route,
          threadId,
          identityRevision
        ].join("|"),
        contactIdentityRevision:
          identityRevision
      };
    };

    adapter.diagnostics = () => {
      let old = {};

      try {
        old =
          previousDiagnostics() || {};
      } catch (_) {}

      const authority =
        readAuthority();

      const conversation =
        adapter.conversation();

      return {
        ...old,
        identityAuthorityVersion:
          VERSION,
        authorityReason:
          authority.reason,
        bridgeStatus:
          authority.payload?.status || "",
        bridgeRevision:
          Number(
            authority.payload?.revision
          ) || 0,
        finalIdentityType:
          conversation?.identityType || "",
        finalIdentityValue:
          conversation?.identityValue || "",
        finalReadonly:
          conversation?.readonly === true,
        finalIdentityResolution:
          conversation?.metadata
            ?.identityResolution || ""
      };
    };

    adapter.__identityAuthority210316 =
      true;
    installed = true;

    previousSignature =
      conversationSignature(
        adapter.conversation()
      );

    publishDiagnostic("INSTALLED");
  }

  function currentSignature() {
    const adapter =
      window.JubaAdapters?.threads;

    if (!adapter) {
      return "";
    }

    let conversation = null;
    let context = null;

    try {
      conversation =
        adapter.conversation?.() || null;
    } catch (_) {}

    try {
      context =
        adapter.context?.() || null;
    } catch (_) {}

    return [
      clean(context?.signature, 4096),
      conversationSignature(
        conversation
      )
    ].join("||");
  }

  function emitIfChanged(reason) {
    if (!installed) {
      return;
    }

    const signature =
      currentSignature();

    if (
      signature === previousSignature
    ) {
      return;
    }

    const oldSignature =
      previousSignature;

    previousSignature =
      signature;
    eventCount += 1;

    window.dispatchEvent(
      new CustomEvent(
        EVENT_NAME,
        {
          detail: {
            platform: "threads",
            threadId:
              currentThreadId(),
            signature,
            oldSignature,
            reason,
            eventCount
          }
        }
      )
    );

    publishDiagnostic(reason);
  }

  function installObserver() {
    if (
      observer ||
      !document.documentElement
    ) {
      return;
    }

    observer =
      new MutationObserver(
        mutations => {
          for (
            const mutation of mutations
          ) {
            const target =
              mutation.target;

            if (target?.id === BRIDGE_ID) {
              emitIfChanged(
                "UNIFIED_BRIDGE_CHANGED"
              );
              return;
            }

            if (
              mutation.type === "childList" &&
              Array.from(
                mutation.addedNodes || []
              ).some(node =>
                node?.id === BRIDGE_ID
              )
            ) {
              emitIfChanged(
                "UNIFIED_BRIDGE_ADDED"
              );
              return;
            }
          }
        }
      );

    observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: [
          "content"
        ]
      }
    );
  }

  install();
  installObserver();

  pollTimer = setInterval(() => {
    install();
    installObserver();
    emitIfChanged(
      "AUTHORITY_SIGNATURE_POLL"
    );

    const conversation =
      authorityConversation();

    if (conversation) {
      writeAck(conversation);
    }

    publishDiagnostic("POLL");
  }, 300);

  window.addEventListener(
    "pagehide",
    () => {
      clearTimeout(installTimer);
      clearInterval(pollTimer);
      observer?.disconnect();
    },
    {
      once: true
    }
  );
})();
