"use client";

import { useState } from "react";

interface CreateDatabankModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (name: string, description: string) => void;
  creating: boolean;
}

export default function CreateDatabankModal({ isOpen, onClose, onCreate, creating }: CreateDatabankModalProps) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");

  if (!isOpen) return null;

  const handleCreate = () => {
    if (name.trim()) {
      onCreate(name.trim(), desc.trim());
      setName("");
      setDesc("");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-md mx-4 rounded-2xl border-2 border-white bg-white p-5 shadow-2xl">
        <h3 className="text-[16px] font-bold text-ink">Create Databank</h3>
        <p className="text-[12px] text-ink/50 mt-0.5">Set up a new knowledge base for your agents</p>
        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Product Knowledge Base"
              className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Description (optional)</label>
            <input
              type="text"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="What is this databank for?"
              className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
            />
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-xl border-2 border-ink/10 px-4 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!name.trim() || creating}
            className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-40"
          >
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
