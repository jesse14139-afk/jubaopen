"use strict";
window.JubaAdapters=window.JubaAdapters||{};
window.JubaAdapters.messenger={
 code:"messenger",
 capabilities:window.JubaMessageProtocol.capabilities.messenger,
 matches:()=>location.hostname.endsWith("messenger.com"),
 account:()=>window.JubaMeta.account("messenger"),
 context:()=>window.JubaMeta.context("messenger"),
 conversation:()=>window.JubaMeta.conversation("messenger","messenger:"),
 messages:()=>window.JubaMeta.messages("messenger","messenger:"),
 diagnostics:()=>window.JubaMeta.diagnostics("messenger")
};
