"use client";

import { useState } from "react";
import Modal from "@/components/dashboard/media/Modal";

type PromptItem = {
  id: string;
  channel_id: string;
  title: string;
  prompt_text: string;
  intent: string;
  is_active: boolean;
};

type Copy = {
  promptLibrary: string;
  libraryEyebrow: string;
  searchPrompts: string;
  addPrompt: string;
  editPrompt: string;
  archivePrompt: string;
  deletePrompt: string;
  loading: string;
  titleLabel: string;
  promptLabel: string;
  intentLabel: string;
  savePrompt: string;
  cancel: string;
  noPrompts: string;
  suggestionsTitle: string;
  useSuggestion: string;
  active: string;
  archived: string;
};

type Props = {
  channelId: string;
  copy: Copy;
  prompts: PromptItem[];
  suggestions: string[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: (body: {
    channel_id: string;
    title: string;
    prompt_text: string;
    intent: string;
  }) => Promise<void>;
  onUpdate: (
    id: string,
    body: Partial<Pick<PromptItem, "title" | "prompt_text" | "intent" | "is_active">>,
  ) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  loading?: boolean;
};

export default function PromptLibrary({
  channelId,
  copy,
  prompts,
  suggestions,
  selectedId,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
  loading = false,
}: Props) {
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<PromptItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [intent, setIntent] = useState("discovery");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const visible = prompts.filter((row) =>
    `${row.title} ${row.prompt_text}`.toLowerCase().includes(search.toLowerCase()),
  );
  const startCreate = (value = "") => {
    setEditing(null);
    setCreating(true);
    setTitle(value.slice(0, 80));
    setText(value);
    setIntent("discovery");
    setError(null);
  };
  const startEdit = (row: PromptItem) => {
    setCreating(false);
    setEditing(row);
    setTitle(row.title);
    setText(row.prompt_text);
    setIntent(row.intent);
    setError(null);
  };
  const close = () => {
    setCreating(false);
    setEditing(null);
    setError(null);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await onUpdate(editing.id, { title, prompt_text: text, intent });
      } else {
        await onCreate({ channel_id: channelId, title, prompt_text: text, intent });
      }
      close();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "save_failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ai-panel p-5 lg:sticky lg:top-6" aria-label={copy.promptLibrary}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="ai-eyebrow">{copy.libraryEyebrow}</p>
          <h2 className="mt-1 text-[16px] font-bold text-[var(--ai-ink)]">
            {copy.promptLibrary}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => startCreate()}
          className="ai-btn-primary min-h-10 px-3 text-[11px]"
        >
          <span aria-hidden="true">+</span> {copy.addPrompt}
        </button>
      </div>
      <input
        aria-label={copy.searchPrompts}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="ai-control mt-4 w-full px-3 text-[12px]"
        placeholder={copy.searchPrompts}
      />
      <div className="mt-3 space-y-2">
        {loading && (
          <div role="status" aria-label={copy.loading} className="space-y-2">
            <div className="ai-skeleton h-16 w-full" />
            <div className="ai-skeleton h-16 w-full" />
          </div>
        )}
        {!loading && visible.map((row) => (
          <div
            key={row.id}
            className={`rounded-[var(--ai-radius-control)] border p-3 transition-colors ${
              selectedId === row.id
                ? "border-[var(--ai-accent)] bg-[var(--ai-sunken)]"
                : "border-[var(--ai-line)] bg-[var(--ai-surface)] hover:border-[var(--ai-line-strong)]"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(row.id)}
              className="block w-full text-start"
            >
              <span className="block text-[12px] font-bold text-[var(--ai-ink)]">
                {row.title}
              </span>
              <span className="mt-1 block text-[11px] leading-5 text-[var(--ai-ink-2)]">
                {row.prompt_text}
              </span>
            </button>
            <div className="mt-2 flex flex-wrap gap-1 text-[10px] font-bold">
              <button type="button" onClick={() => startEdit(row)} className="min-h-8 rounded-md px-2 text-[var(--ai-ink-2)] hover:bg-[var(--ai-surface)] hover:text-[var(--ai-ink)]">
                {copy.editPrompt}
              </button>
              <button
                type="button"
                onClick={() =>
                  void onUpdate(row.id, { is_active: !row.is_active }).catch(
                    (exc) =>
                      setError(exc instanceof Error ? exc.message : "save_failed"),
                  )
                }
                className="min-h-8 rounded-md px-2 text-[var(--ai-ink-2)] hover:bg-[var(--ai-surface)] hover:text-[var(--ai-ink)]"
              >
                {row.is_active ? copy.archivePrompt : copy.active}
              </button>
              <button
                type="button"
                onClick={() =>
                  void onDelete(row.id).catch((exc) =>
                    setError(exc instanceof Error ? exc.message : "save_failed"),
                  )
                }
                className="min-h-8 rounded-md px-2 text-[var(--ai-danger)] hover:bg-[var(--ai-surface)]"
              >
                {copy.deletePrompt}
              </button>
            </div>
          </div>
        ))}
        {!loading && visible.length === 0 && (
          <p className="text-[12px] leading-5 text-[var(--ai-ink-2)]">{copy.noPrompts}</p>
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="mt-5 border-t border-[var(--ai-line)] pt-4">
          <h3 className="ai-eyebrow">{copy.suggestionsTitle}</h3>
          <div className="mt-2 divide-y divide-[var(--ai-line)]">
            {suggestions.map((suggestion, index) => (
              <div
                key={suggestion}
                className="flex items-start justify-between gap-3 py-3 text-[11px] leading-5 text-[var(--ai-ink-2)]"
              >
                <div className="flex gap-3">
                  <span className="font-mono text-[10px] font-bold text-[var(--ai-signal)]">
                    0{index + 1}
                  </span>
                  <span>{suggestion}</span>
                </div>
                <button
                  type="button"
                  onClick={() => startCreate(suggestion)}
                  className="min-h-8 shrink-0 rounded-md px-2 font-bold text-[var(--ai-accent)] hover:bg-[var(--ai-sunken)]"
                >
                  {copy.useSuggestion}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <Modal
        open={!!(creating || editing)}
        onClose={close}
        busy={busy}
        title={editing ? copy.editPrompt : copy.addPrompt}
        closeLabel={copy.cancel}
      >
        <div>
          <label className="mt-3 block text-[11px] font-semibold">
            {copy.titleLabel}
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="ai-control mt-1 w-full px-3 text-[13px]"
            />
          </label>
          <label className="mt-3 block text-[11px] font-semibold">
            {copy.promptLabel}
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              className="ai-control mt-1 min-h-28 w-full px-3 py-2 text-[13px]"
            />
          </label>
          <label className="mt-3 block text-[11px] font-semibold">
            {copy.intentLabel}
            <select
              value={intent}
              onChange={(event) => setIntent(event.target.value)}
              className="ai-control mt-1 w-full px-3 text-[13px]"
            >
              <option value="discovery">discovery</option>
              <option value="comparison">comparison</option>
              <option value="fact-check">fact-check</option>
              <option value="recommendation">recommendation</option>
            </select>
          </label>
          {error && (
            <p role="alert" className="mt-3 text-[12px] font-semibold text-[var(--ai-danger)]">
              {error}
            </p>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={close} className="ai-control px-4 text-[12px] font-bold">
              {copy.cancel}
            </button>
            <button
              type="button"
              disabled={busy || !title.trim() || text.trim().length < 3}
              onClick={() => void save()}
              className="ai-btn-primary px-4 text-[12px]"
            >
              {copy.savePrompt}
            </button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
