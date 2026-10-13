"use strict";
window.JubaAdapters=window.JubaAdapters||{};
window.JubaAdapters.instagram={
 code:"instagram",
 capabilities:window.JubaMessageProtocol.capabilities.instagram,
 matches:()=>location.hostname.endsWith("instagram.com")&&location.pathname.startsWith("/direct/"),
 account:()=>window.JubaMeta.account("instagram"),
 context:()=>window.JubaMeta.context("instagram"),
 conversation:()=>window.JubaMeta.conversation("instagram","ig:"),
 messages:()=>window.JubaMeta.messages("instagram","ig:"),
 diagnostics:()=>window.JubaMeta.diagnostics("instagram")
};
