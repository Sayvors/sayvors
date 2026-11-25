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
  searchPrompts: string;
  addPrompt: string;
  editPrompt: string;
  archivePrompt: string;
  deletePrompt: string;
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
    <section className="ui-card p-4" aria-label={copy.promptLibrary}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[14px] font-bold text-[var(--ui-ink)]">
          {copy.promptLibrary}
        </h2>
        <button
          type="button"
          onClick={() => startCreate()}
          className="rounded-[8px] border border-[var(--ui-line)] px-2.5 py-1 text-[11px] font-bold"
        >
          {copy.addPrompt}
        </button>
      </div>
      <input
        aria-label={copy.searchPrompts}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="mt-3 w-full rounded-[8px] border border-[var(--ui-line)] bg-white px-3 py-2 text-[12px]"
        placeholder={copy.searchPrompts}
      />
      <div className="mt-3 space-y-2">
        {visible.map((row) => (
          <div
            key={row.id}
            className={`rounded-[8px] border p-2.5 ${
              selectedId === row.id
                ? "border-[var(--ui-ink)]"
                : "border-[var(--ui-line)]"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(row.id)}
              className="block w-full text-start"
            >
              <span className="block text-[12px] font-bold text-[var(--ui-ink)]">
                {row.title}
              </span>
              <span className="mt-1 block text-[11px] text-[var(--ui-ink-2)]">
                {row.prompt_text}
              </span>
            </button>
            <div className="mt-2 flex gap-2 text-[10px] font-bold">
              <button type="button" onClick={() => startEdit(row)}>
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
              >
                {copy.deletePrompt}
              </button>
            </div>
          </div>
        ))}
        {visible.length === 0 && (
          <p className="text-[12px] text-[var(--ui-ink-2)]">{copy.noPrompts}</p>
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="mt-4 border-t border-[var(--ui-line)] pt-3">
          <h3 className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
            {copy.suggestionsTitle}
          </h3>
          {suggestions.map((suggestion) => (
            <div
              key={suggestion}
              className="mt-2 flex items-start justify-between gap-2 text-[11px] text-[var(--ui-ink-2)]"
            >
              <span>{suggestion}</span>
              <button
                type="button"
                onClick={() => startCreate(suggestion)}
                className="shrink-0 font-bold text-[var(--ui-ink)]"
              >
                {copy.useSuggestion}
              </button>
            </div>
          ))}
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
              className="mt-1 w-full rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[13px]"
            />
          </label>
          <label className="mt-3 block text-[11px] font-semibold">
            {copy.promptLabel}
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              className="mt-1 min-h-28 w-full rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[13px]"
            />
          </label>
          <label className="mt-3 block text-[11px] font-semibold">
            {copy.intentLabel}
            <select
              value={intent}
              onChange={(event) => setIntent(event.target.value)}
              className="mt-1 w-full rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[13px]"
            >
              <option value="discovery">discovery</option>
              <option value="comparison">comparison</option>
              <option value="fact-check">fact-check</option>
              <option value="recommendation">recommendation</option>
            </select>
          </label>
          {error && (
            <p role="alert" className="mt-3 text-[12px] text-red-700">
              {error}
            </p>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={close}>
              {copy.cancel}
            </button>
            <button
              type="button"
              disabled={busy || !title.trim() || text.trim().length < 3}
              onClick={() => void save()}
              className="rounded-[8px] bg-[var(--ui-ink)] px-3.5 py-2 text-[12px] font-bold text-white disabled:opacity-50"
            >
              {copy.savePrompt}
            </button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
