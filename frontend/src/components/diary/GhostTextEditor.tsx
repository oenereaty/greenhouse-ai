import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export interface GhostTextEditorHandle {
  insertText: (text: string) => void;
  clear: () => void;
}

interface GhostTextEditorProps {
  autocompleteTerms: string[];
  onChange: (text: string) => void;
  resetKey: string | number;
  placeholder?: string;
}

/**
 * Ghost-text autocomplete editor, ported from ui/diary_editor/index.html.
 * Uncontrolled contentEditable (React never re-renders its DOM content) — the
 * ghost suggestion is a real `contenteditable="false"` span appended after the
 * caret, same technique the original Streamlit component used. Composition
 * events are guarded so Korean IME input never gets clobbered mid-keystroke.
 */
const GhostTextEditor = forwardRef<GhostTextEditorHandle, GhostTextEditorProps>(
  ({ autocompleteTerms, onChange, resetKey, placeholder }, ref) => {
    const editorRef = useRef<HTMLDivElement>(null);
    const ghostRef = useRef<string>("");
    const composingRef = useRef(false);
    const termsRef = useRef(autocompleteTerms);
    termsRef.current = autocompleteTerms;

    const getPlainText = (): string => {
      const el = editorRef.current;
      if (!el) return "";
      const ghost = el.querySelector<HTMLSpanElement>(".ghost");
      if (!ghost) return el.innerText;
      const full = el.innerText;
      const gt = ghost.innerText;
      return full.endsWith(gt) ? full.slice(0, full.length - gt.length) : full;
    };

    const moveCursorToEnd = () => {
      const el = editorRef.current;
      if (!el) return;
      try {
        const range = document.createRange();
        const sel = window.getSelection();
        range.selectNodeContents(el);
        range.collapse(false);
        sel?.removeAllRanges();
        sel?.addRange(range);
      } catch {
        /* selection unavailable */
      }
    };

    const clearGhost = () => {
      const el = editorRef.current;
      const g = el?.querySelector<HTMLSpanElement>(".ghost");
      g?.remove();
      ghostRef.current = "";
    };

    const showGhost = (suffix: string) => {
      clearGhost();
      const el = editorRef.current;
      if (!suffix || !el) return;
      ghostRef.current = suffix;
      const span = document.createElement("span");
      span.className = "ghost";
      span.setAttribute("contenteditable", "false");
      span.style.color = "#c0c0c0";
      span.style.fontStyle = "italic";
      span.style.pointerEvents = "none";
      span.style.userSelect = "none";
      span.textContent = suffix;
      el.appendChild(span);
    };

    const findSuffix = (prefix: string): string => {
      if (!prefix) return "";
      const hit = termsRef.current.find((t) => t.startsWith(prefix) && t.length > prefix.length);
      return hit ? hit.slice(prefix.length) : "";
    };

    const updateGhost = () => {
      const text = getPlainText();
      const dblSpace = text.length >= 2 && text.slice(-1) === " " && text.slice(-2, -1) === " ";
      const search = dblSpace ? text.trimEnd() : text;
      const lastWord = search.match(/(\S+)$/)?.[1] ?? "";
      showGhost(findSuffix(lastWord));
    };

    const sendValue = () => onChange(getPlainText());

    const acceptGhost = () => {
      const el = editorRef.current;
      if (!ghostRef.current || !el) return;
      const accepted = ghostRef.current;
      clearGhost();
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        range.collapse(false);
        const node = document.createTextNode(accepted + " ");
        range.insertNode(node);
        range.setStartAfter(node);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      } else {
        el.appendChild(document.createTextNode(accepted + " "));
      }
      sendValue();
      updateGhost();
    };

    useImperativeHandle(ref, () => ({
      insertText: (text: string) => {
        const el = editorRef.current;
        if (!el) return;
        clearGhost();
        const cur = getPlainText();
        el.textContent = cur ? `${cur}\n${text}` : text;
        moveCursorToEnd();
        sendValue();
      },
      clear: () => {
        const el = editorRef.current;
        if (!el) return;
        clearGhost();
        el.textContent = "";
        sendValue();
      },
    }));

    useEffect(() => {
      const el = editorRef.current;
      if (!el) return;
      clearGhost();
      el.textContent = "";
      onChange("");
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [resetKey]);

    return (
      <div
        ref={editorRef}
        contentEditable
        spellCheck={false}
        aria-multiline="true"
        data-placeholder={placeholder}
        className="ghost-text-editor"
        onCompositionStart={() => {
          composingRef.current = true;
          clearGhost();
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
          updateGhost();
          sendValue();
        }}
        onInput={() => {
          if (composingRef.current) return;
          updateGhost();
          sendValue();
        }}
        onKeyDown={(e) => {
          if (e.key === "Tab") {
            e.preventDefault();
            if (ghostRef.current) acceptGhost();
            return;
          }
          if (["Backspace", "Delete", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
            clearGhost();
            return;
          }
          if (e.key === "Escape") clearGhost();
        }}
        onBlur={clearGhost}
        onMouseDown={(e) => {
          if (!(e.target as HTMLElement).classList.contains("ghost")) clearGhost();
        }}
      />
    );
  },
);

export default GhostTextEditor;
