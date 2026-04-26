/**
 * @summary
 * Module-level mutable state for the admin/operator console (active conversation,
 * cached conversation list, context-menu target, and slash-command cache). Exposed
 * as get/set helpers so other modules avoid sharing raw bindings.
 * Exports: getActiveConversationId, setActiveConversationIdRaw,
 *   getConversationCache, setConversationCache,
 *   getConvContextMenuTarget, setConvContextMenuTarget,
 *   getConvMenuCloseHandler, setConvMenuCloseHandler,
 *   getConvMenuEscapeHandler, setConvMenuEscapeHandler,
 *   getCommandCache
 * Deps: admin-types
 * @end-summary
 */
let activeConversationId = null;
let conversationCache = [];
let convContextMenuTarget = null;
let convMenuCloseHandler = null;
let convMenuEscapeHandler = null;
const commandCache = {};
export function getActiveConversationId() {
    return activeConversationId;
}
export function setActiveConversationIdRaw(id) {
    activeConversationId = id;
}
export function getConversationCache() {
    return conversationCache;
}
export function setConversationCache(items) {
    conversationCache = items;
}
export function getConvContextMenuTarget() {
    return convContextMenuTarget;
}
export function setConvContextMenuTarget(id) {
    convContextMenuTarget = id;
}
export function getConvMenuCloseHandler() {
    return convMenuCloseHandler;
}
export function setConvMenuCloseHandler(handler) {
    convMenuCloseHandler = handler;
}
export function getConvMenuEscapeHandler() {
    return convMenuEscapeHandler;
}
export function setConvMenuEscapeHandler(handler) {
    convMenuEscapeHandler = handler;
}
export function getCommandCache() {
    return commandCache;
}
