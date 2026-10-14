"use strict";

/*
 * JUBAOPEN_THREADS_REGISTRATION_FIX_210_3_21
 *
 * Registration-facing canonical adapter layer.
 *
 * This layer does not invent an identity and does not turn an
 * unconfirmed conversation into an accepted conversation.
 *
 * It only makes an already stable and writable Authority
 * conversation available through a consistent structure.
 */
(() => {
  if (
    window.__jubaThreadsRegistrationFix210321
  ) {
    return;
  }

  window.__jubaThreadsRegistrationFix210321 =
    true;

  const VERSION = "210.3.21";

  const DIAGNOSTIC_ID =
    "jubaopen-threads-registration-diagnostics-v210321";

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

  function publish(value) {
    try {
      ensureMeta().setAttribute(
        "content",
        JSON.stringify({
          v: 1,
          version: VERSION,
          at: Date.now(),
          ...value
        })
      );
    } catch (_) {
      // Diagnostics must never block registration.
    }
  }

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

  function canonicalConversation(raw) {
    if (
      !raw ||
      typeof raw !== "object"
    ) {
      return null;
    }

    const metadata =
      raw.metadata &&
      typeof raw.metadata === "object"
        ? raw.metadata
        : {};

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

    const threadId =
      clean(
        raw.threadId ||
        metadata.threadId ||
        currentThreadId(),
        256
      );

    const externalConversationId =
      clean(
        raw.externalConversationId ||
        metadata.externalConversationId ||
        (
          threadId
            ? `threads:${threadId}`
            : ""
        ),
        512
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
        Boolean(identityValue) &&
        Boolean(externalConversationId)
      );

    if (
      !identityType ||
      !identityValue ||
      !externalConversationId ||
      !stable ||
      !writable ||
      readonly
    ) {
      return null;
    }

    const resolution =
      clean(
        raw.resolution ||
        metadata.identityResolution ||
        metadata.resolution ||
        "manual-confirmed",
        100
      );

    const confirmationId =
      clean(
        raw.confirmationId ||
        metadata.confirmationId,
        200
      );

    const canonicalMetadata = {
      ...metadata,

      platform:
        "threads",

      threadId,

      externalConversationId,

      identityType,

      identityValue,

      identityResolution:
        resolution,

      resolution,

      stable:
        true,

      writable:
        true,

      readonly:
        false,

      confirmedByUser:
        raw.confirmedByUser === true ||
        metadata.confirmedByUser === true ||
        resolution === "manual-confirmed",

      confirmationId,

      identityAuthorityVersion:
        clean(
          metadata.identityAuthorityVersion ||
          "210.3.20",
          64
        ),

      registrationCompatibilityVersion:
        VERSION
    };

    return {
      ...raw,

      platform:
        "threads",

      code:
        "threads",

      threadId,

      externalConversationId,

      identityType,

      identityValue,

      displayName:
        clean(
          raw.displayName ||
          metadata.displayName ||
          (
            identityType ===
            "threads_username"
              ? `@${identityValue}`
              : identityValue
          ),
          200
        ),

      role:
        clean(
          raw.role ||
          metadata.role ||
          "IS_PARTICIPANT",
          64
        ),

      resolution,

      stable:
        true,

      writable:
        true,

      readonly:
        false,

      confirmedByUser:
        canonicalMetadata.confirmedByUser,

      confirmationId,

      reason:
        "",

      reasons:
        [],

      errors:
        [],

      warnings:
        [],

      metadata:
        canonicalMetadata
    };
  }

  function install() {
    const adapter =
      window.JubaAdapters?.threads;

    if (!adapter) {
      publish({
        installed: false,
        accepted: false,
        reason: "THREADS_ADAPTER_MISSING"
      });

      return false;
    }

    if (
      adapter.__jubaRegistrationFix210321
    ) {
      return true;
    }

    const originalConversation =
      typeof adapter.conversation === "function"
        ? adapter.conversation.bind(adapter)
        : null;

    const originalDiagnostics =
      typeof adapter.diagnostics === "function"
        ? adapter.diagnostics.bind(adapter)
        : null;

    if (!originalConversation) {
      publish({
        installed: false,
        accepted: false,
        reason: "CONVERSATION_FUNCTION_MISSING"
      });

      return false;
    }

    adapter.conversation = () => {
      let raw = null;
      let errorText = "";

      try {
        raw =
          originalConversation() ||
          null;
      } catch (error) {
        errorText =
          String(
            error?.stack ||
            error
          );
      }

      const conversation =
        errorText
          ? null
          : canonicalConversation(raw);

      publish({
        installed: true,
        accepted:
          Boolean(conversation),
        reason:
          conversation
            ? "REGISTRATION_CONVERSATION_ACCEPTED"
            : (
                errorText
                  ? "CONVERSATION_THROW"
                  : "CONVERSATION_NOT_WRITABLE"
              ),
        error:
          errorText,
        threadId:
          currentThreadId(),
        finalConversation:
          conversation,
        finalWritable:
          conversation?.writable === true,
        finalReadonly:
          conversation
            ? conversation.readonly === true
            : true
      });

      return conversation;
    };

    adapter.diagnostics = () => {
      let legacy = {};

      if (originalDiagnostics) {
        try {
          const value =
            originalDiagnostics();

          if (
            value &&
            typeof value === "object"
          ) {
            legacy = value;
          }
        } catch (_) {
          legacy = {};
        }
      }

      const conversation =
        adapter.conversation();

      const accepted =
        Boolean(conversation);

      const result = {
        ...legacy,

        platform:
          "threads",

        code:
          accepted
            ? "ACCEPTED"
            : "CONVERSATION_NOT_WRITABLE",

        version:
          VERSION,

        at:
          Date.now(),

        installed:
          true,

        accepted,

        ok:
          accepted,

        reason:
          accepted
            ? "PANEL_READ_ACCEPTED"
            : "CONVERSATION_NOT_WRITABLE",

        conversation,

        finalConversation:
          conversation,

        panelConversation:
          conversation,

        hasConversation:
          accepted,

        externalConversationId:
          conversation
            ?.externalConversationId ||
          "",

        identityType:
          conversation
            ?.identityType ||
          "",

        identityValue:
          conversation
            ?.identityValue ||
          "",

        stable:
          accepted,

        writable:
          accepted,

        readonly:
          !accepted,

        finalStable:
          accepted,

        finalWritable:
          accepted,

        finalReadonly:
          !accepted,

        stableContactIdentity:
          accepted,

        stableContactIdentityMissing:
          !accepted,

        contactIdentityMissing:
          !accepted,

        identityMissing:
          !accepted,

        identityAccepted:
          accepted,

        panelIdentityAccepted:
          accepted,

        panelIdentityCode:
          accepted
            ? "ACCEPTED"
            : "CONVERSATION_NOT_WRITABLE",

        errors:
          accepted
            ? []
            : [
                "CONVERSATION_NOT_WRITABLE"
              ],

        warnings:
          [],

        reasons:
          accepted
            ? []
            : [
                "CONVERSATION_NOT_WRITABLE"
              ],

        conversationReasons:
          accepted
            ? []
            : [
                "CONVERSATION_NOT_WRITABLE"
              ],

        diagnosticsReasons:
          accepted
            ? []
            : [
                "CONVERSATION_NOT_WRITABLE"
              ],

        blocked:
          !accepted,

        canRegister:
          accepted,

        canCreateContact:
          accepted,

        registrationCompatibilityVersion:
          VERSION
      };

      publish({
        installed: true,
        accepted,
        reason:
          result.reason,
        threadId:
          currentThreadId(),
        finalConversation:
          conversation,
        finalWritable:
          accepted,
        finalReadonly:
          !accepted
      });

      return result;
    };

    Object.defineProperty(
      adapter,
      "__jubaRegistrationFix210321",
      {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false
      }
    );

    /*
     * Publish immediately so that the result is available before
     * Chat Panel initializes its registration state.
     */
    adapter.diagnostics();

    return true;
  }

  if (install()) {
    return;
  }

  let attempts = 0;

  const timer = setInterval(
    () => {
      attempts += 1;

      if (
        install() ||
        attempts >= 100
      ) {
        clearInterval(timer);
      }
    },
    50
  );
})();
