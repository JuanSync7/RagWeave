/**
 * Minimal ambient type declarations for marked and dompurify.
 * Used when the packages are not yet installed in node_modules.
 * Once `npm install` is run these declarations are superseded by the
 * proper types shipped inside node_modules.
 */

declare module "marked" {
    interface CodeToken {
        raw: string;
        text: string;
        lang?: string;
        escaped?: boolean;
    }
    interface MarkedRenderer {
        code?(token: CodeToken): string;
    }
    interface MarkedExtension {
        gfm?: boolean;
        breaks?: boolean;
        renderer?: MarkedRenderer;
    }
    const marked: {
        parse(src: string): string | Promise<string>;
        use(extension: MarkedExtension): void;
    };
    export { marked };
    export default marked;
}

declare module "dompurify" {
    interface DOMPurifyI {
        sanitize(dirty: string): string;
    }
    const DOMPurify: DOMPurifyI;
    export default DOMPurify;
}
