// @summary
// Mutable singleton state shared across user-console feature modules.
// Centralizing the previously closure-scoped variables here lets future PRs split
// feature code (sidebar, settings, streaming, conversations, slash commands, …)
// into their own modules without each one having to re-establish state plumbing.
// Exports: state, AttachmentChip, SlashCommand
// Deps: (none)
// @end-summary

export interface SlashCommand {
    name: string;
    description: string;
    args_hint?: string;
    category?: string;
}

export interface AttachmentChip {
    id: string;
    icon: string;
    label: string;
}

export interface ConsoleState {
    activeConversationId: string | null;
    isStreaming: boolean;
    dynamicCmds: SlashCommand[];
    allSlashItems: HTMLElement[];
    slashSelIdx: number;
    allPickerItems: HTMLElement[];
    pickerIdx: number;
    attachments: AttachmentChip[];
    userScrolledUp: boolean;
    streamAbortCtrl: AbortController | null;
}

export const state: ConsoleState = {
    activeConversationId: localStorage.getItem("nc_active_conv") || null,
    isStreaming: false,
    dynamicCmds: [],
    allSlashItems: [],
    slashSelIdx: 0,
    allPickerItems: [],
    pickerIdx: 0,
    attachments: [],
    userScrolledUp: false,
    streamAbortCtrl: null,
};
