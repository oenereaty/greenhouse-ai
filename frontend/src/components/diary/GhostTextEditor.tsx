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

    // 이전엔 스페이스 두 번을 눌러야만 직전 단어에 대한 고스트가 (다시) 떴는데,
    // 그 경로로 뜬 고스트를 Tab으로 확정하면 "흰가루  병"처럼 단어 사이에 공백이
    // 두 개 낀 채로 붙어버렸다(사용자 확인, 2026-07-10). 지금 입력 중인 마지막
    // 단어만 보고 바로 제안하도록 단순화 — 공백 뒤에는 아직 완성된 다음 단어가
    // 없으므로 자연스럽게 고스트가 사라진다.
    const updateGhost = () => {
      const text = getPlainText();
      const lastWord = text.match(/(\S+)$/)?.[1] ?? "";
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
