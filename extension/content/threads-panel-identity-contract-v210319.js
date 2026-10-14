"use strict";

/*
 * JUBAOPEN_THREADS_PANEL_IDENTITY_CONTRACT_210_3_19
 *
 * 该文件位于 Threads Authority 与 Chat Panel 之间。
 *
 * 目标：
 * 1. 每次调用都实时读取 Authority，不缓存旧 conversation；
 * 2. 统一顶层字段和 metadata 字段；
 * 3. 将不同版本的身份结构规范为 Chat Panel 可消费结构；
 * 4. 记录 Chat Panel 实际能够读取到的身份；
 * 5. 在 Authority 尚未完成安装时不锁定旧函数。
 */
(() => {
  if (
    window
      .__jubaThreadsPanelIdentityContract210319
  ) {
    return;
  }

  window
    .__jubaThreadsPanelIdentityContract210319 =
    true;

  const VERSION = "210.3.19";

  const DIAGNOSTIC_ID =
    "jubaopen-threads-panel-contract-diagnostics-v210319";

  const state = {
    adapter: null,
    authorityConversation: null,
    authorityContext: null,
    authorityDiagnostics: null,
    installed: false,
    calls: 0,
    acceptedCalls: 0,
    rejectedCalls: 0,
    lastCode: "",
    lastAt: 0
  };

  const clean = (
    value,
    max = 4096
  ) =>
    String(value ?? "")
      .replace(/\u0000/g, "")
      .replace(
        /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]/g,
        ""
      )
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);

  function currentThreadId() {
    const match =
      location.pathname.match(
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
      return clean(
        match[1],
        256
      );
    }
  }

  function ensureMeta() {
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

  function isManualResolution(
    resolution
  ) {
    return (
      resolution ===
      "manual-confirmed"
    );
  }

  function normalizeConversation(
    raw
  ) {
    if (
      !raw ||
      typeof raw !== "object"
    ) {
      return {
        ok: false,
        code:
          "CONVERSATION_MISSING",
        raw: raw || null,
        conversation: null
      };
    }

    const metadata =
      raw.metadata &&
      typeof raw.metadata === "object"
        ? raw.metadata
        : {};

    const threadId =
      clean(
        metadata.threadId ||
        raw.threadId ||
        currentThreadId(),
        256
      );

    const identityType =
      clean(
        raw.identityType ||
        metadata.identityType,
        64
      );

    const identityValue =
      clean(
        raw.identityValue ||
        metadata.identityValue,
        200
      );

    const role =
      clean(
        raw.role ||
        metadata.role ||
        (
          identityValue
            ? "IS_PARTICIPANT"
            : ""
        ),
        64
      );

    const stable =
      raw.stable === true ||
      metadata.stable === true;

    const readonly =
      raw.readonly === true;

    const writable =
      raw.writable === true ||
      metadata.writable === true ||
      (
        readonly === false &&
        stable &&
        Boolean(identityType) &&
        Boolean(identityValue)
      );

    const resolution =
      clean(
        raw.resolution ||
        metadata.identityResolution ||
        metadata.resolution,
        100
      );

    const confirmedByUser =
      raw.confirmedByUser === true ||
      metadata.confirmedByUser === true;

    const confirmationId =
      clean(
        raw.confirmationId ||
        metadata.confirmationId,
        200
      );

    const confirmedAt =
      Number(
        raw.confirmedAt ||
        metadata.confirmedAt
      ) || 0;

    const externalConversationId =
      clean(
        raw.externalConversationId ||
        (
          threadId
            ? `threads:${threadId}`
            : ""
        ),
        512
      );

    let code = "ACCEPTED";

    if (!externalConversationId) {
      code =
        "EXTERNAL_CONVERSATION_ID_MISSING";
    } else if (
      !identityType ||
      !identityValue
    ) {
      code =
        "CONTACT_IDENTITY_MISSING";
    } else if (readonly) {
      code =
        "CONVERSATION_READONLY";
    } else if (!stable) {
      code =
        "CONTACT_IDENTITY_NOT_STABLE";
    } else if (!writable) {
      code =
        "CONTACT_IDENTITY_NOT_WRITABLE";
    } else if (
      role &&
      role !== "IS_PARTICIPANT"
    ) {
      code =
        "CONTACT_ROLE_INVALID";
    } else if (
      isManualResolution(
        resolution
      ) &&
      (
        !confirmedByUser ||
        !confirmationId
      )
    ) {
      code =
        "MANUAL_CONFIRMATION_INVALID";
    }

    const accepted =
      code === "ACCEPTED";

    const conversation = {
      ...raw,

      externalConversationId,

      threadId,

      identityType,

      identityValue,

      displayName:
        clean(
          raw.displayName ||
          metadata.displayName,
          200
        ),

      avatarUrl:
        clean(
          raw.avatarUrl ||
          metadata.avatarUrl,
          4096
        ),

      role:
        role ||
        (
          accepted
            ? "IS_PARTICIPANT"
            : ""
        ),

      stable:
        accepted
          ? true
          : stable,

      writable:
        accepted
          ? true
          : writable,

      readonly:
        accepted
          ? false
          : readonly,

      reason:
        accepted
          ? ""
          : (
              clean(raw.reason, 300) ||
              code
            ),

      confidence:
        clean(
          raw.confidence ||
          metadata.confidence ||
          (
            accepted
              ? "high"
              : ""
          ),
          64
        ),

      resolution,

      confirmedByUser,

      confirmationId,

      confirmedAt,

      metadata: {
        ...metadata,

        platform:
          "threads",

        threadId,

        externalConversationId,

        identityType,

        identityValue,

        role:
          role ||
          (
            accepted
              ? "IS_PARTICIPANT"
              : ""
          ),

        stable:
          accepted
            ? true
            : stable,

        writable:
          accepted
            ? true
            : writable,

        readonly:
          accepted
            ? false
            : readonly,

        confidence:
          clean(
            raw.confidence ||
            metadata.confidence ||
            (
              accepted
                ? "high"
                : ""
            ),
            64
          ),

        identityResolution:
          resolution,

        resolution,

        confirmedByUser,

        confirmationId,

        confirmedAt,

        identityAuthorityVersion:
          clean(
            metadata
              .identityAuthorityVersion ||
            VERSION,
            64
          ),

        panelIdentityContractVersion:
          VERSION
      }
    };

    return {
      ok: accepted,
      code,
      raw,
      conversation
    };
  }

  function writeDiagnostics(
    reason,
    result,
    extra = {}
  ) {
    state.lastAt =
      Date.now();

    state.lastCode =
      result?.code || "";

    ensureMeta().setAttribute(
      "content",
      JSON.stringify({
        v: 1,
        version:
          VERSION,
        at:
          state.lastAt,
        reason,
        installed:
          state.installed,
        calls:
          state.calls,
        acceptedCalls:
          state.acceptedCalls,
        rejectedCalls:
          state.rejectedCalls,
        accepted:
          result?.ok === true,
        code:
          result?.code || "",
        threadId:
          currentThreadId(),
        rawConversation:
          result?.raw || null,
        finalConversation:
          result?.conversation || null,
        extra
      })
    );
  }

  function contractConversation() {
    state.calls += 1;

    let raw = null;

    try {
      raw =
        state
          .authorityConversation?.() ||
        null;
    } catch (error) {
      const result = {
        ok: false,
        code:
          "AUTHORITY_CONVERSATION_THROW",
        raw: null,
        conversation: {
          externalConversationId:
            currentThreadId()
              ? (
                  "threads:" +
                  currentThreadId()
                )
              : "",
          identityType: "",
          identityValue: "",
          readonly: true,
          stable: false,
          writable: false,
          reason:
            "AUTHORITY_CONVERSATION_THROW",
          metadata: {
            platform:
              "threads",
            stable:
              false,
            writable:
              false,
            panelIdentityContractVersion:
              VERSION
          }
        }
      };

      state.rejectedCalls += 1;

      writeDiagnostics(
        "CONVERSATION_THROW",
        result,
        {
          error:
            String(
              error?.stack ||
              error
            )
        }
      );

      return result.conversation;
    }

    const result =
      normalizeConversation(raw);

    if (result.ok) {
      state.acceptedCalls += 1;
    } else {
      state.rejectedCalls += 1;
    }

    writeDiagnostics(
      result.ok
        ? "PANEL_READ_ACCEPTED"
        : "PANEL_READ_REJECTED",
      result
    );

    return result.conversation;
  }

  function contractContext() {
    let context = null;

    try {
      context =
        state.authorityContext?.() ||
        null;
    } catch (_) {}

    const conversation =
      contractConversation();

    const threadId =
      clean(
        conversation?.threadId ||
        conversation?.metadata
          ?.threadId ||
        currentThreadId(),
        256
      );

    const route =
      clean(
        context?.route ||
        (
          location.pathname +
          location.search +
          location.hash
        ),
        2048
      );

    const identitySignature = [
      conversation
        ?.externalConversationId || "",
      conversation
        ?.identityType || "",
      conversation
        ?.identityValue || "",
      conversation
        ?.readonly === true
          ? "readonly"
          : "writable",
      conversation
        ?.resolution ||
      conversation
        ?.metadata
        ?.identityResolution ||
      "",
      conversation
        ?.confirmationId ||
      conversation
        ?.metadata
        ?.confirmationId ||
      ""
    ].join("|");

    return {
      ...(context || {}),
      platform:
        "threads",
      route,
      threadId,
      at:
        Number(context?.at) ||
        Date.now(),
      signature: [
        "threads",
        route,
        threadId,
        identitySignature
      ].join("|"),
      contactIdentityRevision:
        identitySignature,
      identityContractVersion:
        VERSION
    };
  }

  function contractDiagnostics() {
    let authority = {};

    try {
      authority =
        state
          .authorityDiagnostics?.() ||
        {};
    } catch (_) {}

    const result =
      normalizeConversation(
        (() => {
          try {
            return state
              .authorityConversation?.() ||
              null;
          } catch (_) {
            return null;
          }
        })()
      );

    return {
      ...authority,
      panelIdentityContractVersion:
        VERSION,
      panelIdentityAccepted:
        result.ok,
      panelIdentityCode:
        result.code,
      panelConversation:
        result.conversation,
      panelContractCalls:
        state.calls
    };
  }

  function findThreadsAdapter() {
    const direct =
      window.JubaAdapters?.threads;

    if (direct) {
      return direct;
    }

    return Object
      .values(
        window.JubaAdapters || {}
      )
      .find(adapter => {
        try {
          return (
            adapter?.code ===
              "threads" ||
            (
              typeof adapter
                ?.matches ===
                "function" &&
              adapter.matches() === true &&
              location.hostname
                .toLowerCase()
                .endsWith(
                  "threads.com"
                )
            )
          );
        } catch (_) {
          return false;
        }
      }) || null;
  }

  function install() {
    const adapter =
      findThreadsAdapter();

    if (
      !adapter ||
      typeof adapter.conversation !==
        "function" ||
      typeof adapter.context !==
        "function"
    ) {
      setTimeout(
        install,
        20
      );
      return;
    }

    if (
      adapter
        .__panelIdentityContract210319 ===
      true
    ) {
      state.adapter = adapter;
      state.installed = true;
      return;
    }

    state.adapter = adapter;

    state.authorityConversation =
      adapter.conversation.bind(
        adapter
      );

    state.authorityContext =
      adapter.context.bind(
        adapter
      );

    state.authorityDiagnostics =
      typeof adapter.diagnostics ===
        "function"
        ? adapter.diagnostics.bind(
            adapter
          )
        : () => ({});

    adapter.conversation =
      contractConversation;

    adapter.context =
      contractContext;

    adapter.diagnostics =
      contractDiagnostics;

    adapter
      .__panelIdentityContract210319 =
      true;

    state.installed = true;

    const initial =
      normalizeConversation(
        state
          .authorityConversation?.() ||
        null
      );

    writeDiagnostics(
      "CONTRACT_INSTALLED",
      initial
    );

    window.dispatchEvent(
      new CustomEvent(
        "jubaopen:threads-panel-identity-contract-ready",
        {
          detail: {
            version:
              VERSION,
            accepted:
              initial.ok,
            code:
              initial.code,
            threadId:
              currentThreadId(),
            identityType:
              initial.conversation
                ?.identityType || "",
            identityValue:
              initial.conversation
                ?.identityValue || "",
            confirmationId:
              initial.conversation
                ?.confirmationId ||
              initial.conversation
                ?.metadata
                ?.confirmationId ||
              ""
          }
        }
      )
    );
  }

  install();
})();
