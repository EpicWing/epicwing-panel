<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { basicSetup } from "codemirror";
import { Compartment, EditorState, type Extension } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { indentWithTab } from "@codemirror/commands";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { json } from "@codemirror/lang-json";
import { yaml } from "@codemirror/lang-yaml";
import { properties } from "@codemirror/legacy-modes/mode/properties";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { tags } from "@lezer/highlight";

import type { Lang } from "../lib/highlight";

const props = defineProps<{ modelValue: string; language: Lang }>();
const emit = defineEmits<{ "update:modelValue": [value: string]; save: [] }>();

const host = ref<HTMLElement | null>(null);
const languageSlot = new Compartment();
let view: EditorView | null = null;
let lastEmitted = props.modelValue;

// Maps the language dropdown of the panel to CodeMirror languages.
function languageFor(lang: Lang): Extension {
  switch (lang) {
    case "yaml":
      return yaml();
    case "json":
      return json();
    case "ini":
      return StreamLanguage.define(properties);
    case "shell":
      return StreamLanguage.define(shell);
    default:
      return [];
  }
}

// Colors come from CSS variables, so dark and light mode switch without a reload.
const colors = HighlightStyle.define([
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--ew-code-comment)" },
  { tag: [tags.punctuation, tags.separator, tags.bracket], color: "var(--ew-code-comment)" },
  {
    tag: [
      tags.propertyName,
      tags.attributeName,
      tags.definition(tags.propertyName),
      tags.definition(tags.variableName),
      tags.variableName,
    ],
    color: "var(--ew-code-key)",
  },
  { tag: [tags.string, tags.special(tags.string), tags.quote], color: "var(--ew-code-string)" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "var(--ew-code-number)" },
  {
    tag: [tags.heading, tags.keyword, tags.meta, tags.typeName, tags.standard(tags.variableName)],
    color: "var(--ew-code-section)",
  },
]);

const look = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "13px",
    backgroundColor: "var(--ew-code-bg)",
    color: "var(--ew-code-text)",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
    lineHeight: "18px",
  },
  ".cm-content": { caretColor: "var(--ew-code-caret)", padding: "12px 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--ew-code-caret)" },
  ".cm-gutters": {
    backgroundColor: "var(--ew-code-gutter)",
    color: "var(--ew-code-gutter-text)",
    border: "none",
    borderRight: "1px solid var(--ew-code-line)",
  },
  ".cm-activeLine": { backgroundColor: "var(--ew-code-active)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--ew-code-active)", color: "var(--ew-code-text)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
    { backgroundColor: "rgba(245, 158, 11, 0.28)" },
  ".cm-matchingBracket": {
    backgroundColor: "rgba(245, 158, 11, 0.18)",
    outline: "1px solid rgba(245, 158, 11, 0.5)",
  },
  ".cm-searchMatch": { backgroundColor: "rgba(245, 158, 11, 0.25)" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "rgba(245, 158, 11, 0.5)" },
  ".cm-panels": { backgroundColor: "var(--ew-code-gutter)", color: "var(--ew-code-text)" },
  ".cm-panels.cm-panels-bottom": { borderTop: "1px solid var(--ew-code-line)" },
  ".cm-panel.cm-search label": { fontSize: "12px" },
  ".cm-textfield": {
    backgroundColor: "var(--ew-code-bg)",
    color: "var(--ew-code-text)",
    border: "1px solid var(--ew-code-line)",
    borderRadius: "4px",
  },
  ".cm-button": {
    backgroundImage: "none",
    backgroundColor: "var(--ew-code-active)",
    color: "var(--ew-code-text)",
    border: "1px solid var(--ew-code-line)",
    borderRadius: "4px",
  },
  ".cm-foldPlaceholder": {
    backgroundColor: "transparent",
    border: "1px solid var(--ew-code-line)",
    color: "var(--ew-code-gutter-text)",
  },
  ".cm-tooltip": {
    backgroundColor: "var(--ew-code-gutter)",
    border: "1px solid var(--ew-code-line)",
    color: "var(--ew-code-text)",
  },
});

onMounted(() => {
  if (!host.value) return;
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        keymap.of([
          {
            key: "Mod-s",
            preventDefault: true,
            run: () => {
              emit("save");
              return true;
            },
          },
          indentWithTab,
        ]),
        basicSetup,
        EditorState.tabSize.of(2),
        languageSlot.of(languageFor(props.language)),
        syntaxHighlighting(colors),
        look,
        EditorView.updateListener.of((update) => {
          if (!update.docChanged) return;
          lastEmitted = update.state.doc.toString();
          emit("update:modelValue", lastEmitted);
        }),
      ],
    }),
  });
  view.focus();
});

watch(
  () => props.language,
  (lang) => view?.dispatch({ effects: languageSlot.reconfigure(languageFor(lang)) }),
);

// Only outside changes replace the document, typing comes back here unchanged.
watch(
  () => props.modelValue,
  (value) => {
    if (!view || value === lastEmitted) return;
    lastEmitted = value;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
  },
);

onBeforeUnmount(() => {
  view?.destroy();
  view = null;
});
</script>

<template>
  <div ref="host" class="ew-editor h-full"></div>
</template>

<style>
.ew-editor {
  --ew-code-bg: #1e1e20;
  --ew-code-gutter: #1a1a1c;
  --ew-code-gutter-text: #6e7681;
  --ew-code-text: #aab2bd;
  --ew-code-key: #e6edf3;
  --ew-code-string: #c9d1d9;
  --ew-code-number: #f0b35a;
  --ew-code-section: #f59e0b;
  --ew-code-comment: #6e7681;
  --ew-code-caret: #e5e7eb;
  --ew-code-line: #2a2a2e;
  --ew-code-active: rgba(255, 255, 255, 0.04);
}

:root[data-theme="light"] .ew-editor {
  --ew-code-bg: #f8f8fa;
  --ew-code-gutter: #ececf0;
  --ew-code-gutter-text: #8a8a95;
  --ew-code-text: #4f4f59;
  --ew-code-key: #17171a;
  --ew-code-string: #3b3d44;
  --ew-code-number: #9a5b00;
  --ew-code-section: #b36b00;
  --ew-code-comment: #8a8a95;
  --ew-code-caret: #17171a;
  --ew-code-line: #dcdce2;
  --ew-code-active: rgba(0, 0, 0, 0.04);
}
</style>
