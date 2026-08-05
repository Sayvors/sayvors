"use client";

import { useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import WidgetPreview from "@/components/agents/WidgetPreview";

type WidgetPreset = {
  id: string;
  name: string;
  category: "Standard" | "Minimal" | "Corporate" | "Playful";
  position: "bottom-right" | "bottom-left" | "top-right" | "top-left";
  primaryColor: string;
  font: string;
  launcherIcon: string;
  welcomeText: string;
  logoUrl: string;
  avatarUrl: string;
  showReviews: boolean;
};

const DEFAULT_PRESETS: WidgetPreset[] = [
  {
    id: "preset-1",
    name: "Classic Purple",
    category: "Standard",
    position: "bottom-right",
    primaryColor: "#3d1d6e",
    font: "system",
    launcherIcon: "chat",
    welcomeText: "Hi! How can I help you today?",
    logoUrl: "",
    avatarUrl: "",
    showReviews: false,
  },
  {
    id: "preset-2",
    name: "Minimal Left",
    category: "Minimal",
    position: "bottom-left",
    primaryColor: "#14101f",
    font: "system",
    launcherIcon: "chat",
    welcomeText: "Hey there! Ask me anything.",
    logoUrl: "",
    avatarUrl: "",
    showReviews: false,
  },
  {
    id: "preset-3",
    name: "Corporate Blue",
    category: "Corporate",
    position: "bottom-right",
    primaryColor: "#0284c7",
    font: "system",
    launcherIcon: "headphones",
    welcomeText: "Welcome! Our team is here to help.",
    logoUrl: "",
    avatarUrl: "",
    showReviews: true,
  },
  {
    id: "preset-4",
    name: "Playful Coral",
    category: "Playful",
    position: "bottom-left",
    primaryColor: "#ff4f6e",
    font: "system",
    launcherIcon: "question",
    welcomeText: "Need a hand? I'm here for you!",
    logoUrl: "",
    avatarUrl: "",
    showReviews: false,
  },
];

const CATEGORIES = ["All", "Standard", "Minimal", "Corporate", "Playful"] as const;

const POSITION_OPTIONS = ["bottom-right", "bottom-left", "top-right", "top-left"] as const;
const FONT_OPTIONS = ["system", "Inter", "Poppins", "Roboto", "Lora"];
const ICON_OPTIONS = ["chat", "question", "headphones"];

function emptyPreset(): WidgetPreset {
  return {
    id: `custom-${Date.now()}`,
    name: "My Widget",
    category: "Standard",
    position: "bottom-right",
    primaryColor: "#3d1d6e",
    font: "system",
    launcherIcon: "chat",
    welcomeText: "Hi! How can I help you today?",
    logoUrl: "",
    avatarUrl: "",
    showReviews: false,
  };
}

export default function WidgetsPage() {
  const [activeTab, setActiveTab] = useState<"browse" | "my-widgets">("browse");
  const [categoryFilter, setCategoryFilter] = useState<string>("All");
  const [myWidgets, setMyWidgets] = useState<WidgetPreset[]>([]);
  const [editingWidget, setEditingWidget] = useState<WidgetPreset | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const browsePresets = DEFAULT_PRESETS.filter(
    (p) => categoryFilter === "All" || p.category === categoryFilter
  );

  const startCreate = () => {
    const fresh = emptyPreset();
    setEditingWidget(fresh);
    setIsCreating(true);
  };

  const startEdit = (preset: WidgetPreset) => {
    setEditingWidget({ ...preset });
    setIsCreating(false);
  };

  const saveWidget = () => {
    if (!editingWidget) return;
    if (isCreating) {
      setMyWidgets((prev) => [...prev, editingWidget]);
    } else {
      setMyWidgets((prev) => prev.map((w) => (w.id === editingWidget.id ? editingWidget : w)));
    }
    setEditingWidget(null);
    setIsCreating(false);
  };

  const deleteWidget = (id: string) => {
    setMyWidgets((prev) => prev.filter((w) => w.id !== id));
    if (editingWidget?.id === id) setEditingWidget(null);
  };

  const duplicateWidget = (preset: WidgetPreset) => {
    const dup: WidgetPreset = { ...preset, id: `custom-${Date.now()}`, name: `${preset.name} (Copy)` };
    setMyWidgets((prev) => [...prev, dup]);
  };

  const updateField = <K extends keyof WidgetPreset>(key: K, value: WidgetPreset[K]) => {
    if (editingWidget) setEditingWidget({ ...editingWidget, [key]: value });
  };

  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Widget Library" }]} />
        <div className="mt-2 flex items-center justify-between">
          <div>
            <h1 className="text-[20px] font-bold text-ink dark:text-fog">Widget Library</h1>
            <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
              Browse widget presets or create your own.
            </p>
          </div>
          <button
            onClick={startCreate}
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            Create Widget
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-0.5 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.03] w-fit">
        <button
          onClick={() => setActiveTab("browse")}
          className={`rounded-md px-4 py-2 text-[12px] font-medium transition ${
            activeTab === "browse"
              ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet"
              : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
          }`}
        >
          Browse
        </button>
        <button
          onClick={() => setActiveTab("my-widgets")}
          className={`rounded-md px-4 py-2 text-[12px] font-medium transition ${
            activeTab === "my-widgets"
              ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet"
              : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
          }`}
        >
          My Widgets
        </button>
      </div>

      <div className="flex gap-5">
        {/* Main content area */}
        <div className="flex-1 min-w-0">
          {/* Browse tab */}
          {activeTab === "browse" && (
            <div className="space-y-4">
              {/* Category filter */}
              <div className="flex gap-1.5">
                {CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setCategoryFilter(cat)}
                    className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${
                      categoryFilter === cat
                        ? "bg-deep-violet text-white"
                        : "bg-ink/[0.04] text-ink/50 hover:bg-ink/[0.06] dark:bg-fog/[0.04] dark:text-fog/50 dark:hover:bg-fog/[0.06]"
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Widget grid */}
              <div className="grid gap-3 sm:grid-cols-2">
                {browsePresets.map((preset) => (
                  <div
                    key={preset.id}
                    className="rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-deep-violet/20 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
                  >
                    <div className="mb-3">
                      <div className="flex items-center justify-between">
                        <p className="text-[13px] font-semibold text-ink dark:text-fog">{preset.name}</p>
                        <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[9px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                          {preset.category}
                        </span>
                      </div>
                    </div>
                    <WidgetPreview
                      position={preset.position}
                      primaryColor={preset.primaryColor}
                      font={preset.font}
                      launcherIcon={preset.launcherIcon}
                      welcomeText={preset.welcomeText}
                    />
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={() => startEdit(preset)}
                        className="flex-1 rounded-lg bg-deep-violet/[0.06] px-3 py-1.5 text-[11px] font-medium text-deep-violet transition hover:bg-deep-violet/10"
                      >
                        Use This
                      </button>
                      <button
                        onClick={() => duplicateWidget(preset)}
                        className="rounded-lg border border-ink/[0.06] px-3 py-1.5 text-[11px] font-medium text-ink/40 transition hover:border-ink/[0.1] dark:border-fog/[0.06] dark:text-fog/40"
                      >
                        Duplicate
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* My Widgets tab */}
          {activeTab === "my-widgets" && (
            <div className="space-y-4">
              {myWidgets.length === 0 ? (
                <div className="rounded-xl border border-dashed border-ink/[0.12] p-8 text-center dark:border-fog/[0.12]">
                  <p className="text-[13px] text-ink/30 dark:text-fog/30">No custom widgets yet. Create one to get started.</p>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {myWidgets.map((widget) => (
                    <div
                      key={widget.id}
                      className="rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-deep-violet/20 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
                    >
                      <div className="flex items-center justify-between mb-3">
                        <p className="text-[13px] font-semibold text-ink dark:text-fog">{widget.name}</p>
                        <span className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[9px] font-medium text-deep-violet">
                          Custom
                        </span>
                      </div>
                      <WidgetPreview
                        position={widget.position}
                        primaryColor={widget.primaryColor}
                        font={widget.font}
                        launcherIcon={widget.launcherIcon}
                        welcomeText={widget.welcomeText}
                      />
                      <div className="mt-3 flex gap-2">
                        <button
                          onClick={() => startEdit(widget)}
                          className="flex-1 rounded-lg bg-deep-violet/[0.06] px-3 py-1.5 text-[11px] font-medium text-deep-violet transition hover:bg-deep-violet/10"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => duplicateWidget(widget)}
                          className="rounded-lg border border-ink/[0.06] px-3 py-1.5 text-[11px] font-medium text-ink/40 transition hover:border-ink/[0.1] dark:border-fog/[0.06] dark:text-fog/40"
                        >
                          Duplicate
                        </button>
                        <button
                          onClick={() => deleteWidget(widget.id)}
                          className="rounded-lg px-3 py-1.5 text-[11px] font-medium text-ink/30 transition hover:text-coral dark:text-fog/30"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Inline editor panel */}
        {editingWidget && (
          <div className="w-80 shrink-0 rounded-xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[14px] font-semibold text-ink dark:text-fog">
                {isCreating ? "Create Widget" : "Edit Widget"}
              </h3>
              <button
                onClick={() => { setEditingWidget(null); setIsCreating(false); }}
                className="rounded-md p-1 text-ink/30 transition hover:text-ink/60 dark:text-fog/30 dark:hover:text-fog/60"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                  <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            <div className="space-y-3">
              {/* Name */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Name</label>
                <input
                  type="text"
                  value={editingWidget.name}
                  onChange={(e) => updateField("name", e.target.value)}
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>

              {/* Position */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Position</label>
                <div className="grid grid-cols-2 gap-1">
                  {POSITION_OPTIONS.map((pos) => (
                    <button
                      key={pos}
                      onClick={() => updateField("position", pos)}
                      className={`rounded-lg border px-2 py-1.5 text-[10px] font-medium transition ${
                        editingWidget.position === pos
                          ? "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet"
                          : "border-ink/[0.06] text-ink/40 hover:border-ink/[0.1] dark:border-fog/[0.06] dark:text-fog/40"
                      }`}
                    >
                      {pos.replace(/-/g, " ")}
                    </button>
                  ))}
                </div>
              </div>

              {/* Color */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Primary Color</label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={editingWidget.primaryColor}
                    onChange={(e) => updateField("primaryColor", e.target.value)}
                    className="h-7 w-7 cursor-pointer rounded-md border border-ink/[0.06] dark:border-fog/[0.06]"
                  />
                  <input
                    type="text"
                    value={editingWidget.primaryColor}
                    onChange={(e) => updateField("primaryColor", e.target.value)}
                    className="flex-1 rounded-lg border border-ink/[0.06] bg-white px-2 py-1.5 text-[11px] font-mono text-ink outline-none dark:border-fog/[0.06] dark:bg-ink dark:text-fog"
                  />
                </div>
              </div>

              {/* Font */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Font</label>
                <div className="flex flex-wrap gap-1">
                  {FONT_OPTIONS.map((f) => (
                    <button
                      key={f}
                      onClick={() => updateField("font", f)}
                      className={`rounded-full px-2.5 py-1 text-[10px] font-medium transition ${
                        editingWidget.font === f
                          ? "bg-deep-violet text-white"
                          : "bg-ink/[0.04] text-ink/50 hover:bg-ink/[0.06] dark:bg-fog/[0.04] dark:text-fog/50"
                      }`}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>

              {/* Launcher Icon */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Launcher Icon</label>
                <div className="flex gap-1.5">
                  {ICON_OPTIONS.map((ic) => (
                    <button
                      key={ic}
                      onClick={() => updateField("launcherIcon", ic)}
                      className={`rounded-lg border px-3 py-1.5 text-[10px] font-medium capitalize transition ${
                        editingWidget.launcherIcon === ic
                          ? "border-deep-violet/30 bg-deep-violet/[0.06] text-deep-violet"
                          : "border-ink/[0.06] text-ink/40 hover:border-ink/[0.1] dark:border-fog/[0.06] dark:text-fog/40"
                      }`}
                    >
                      {ic}
                    </button>
                  ))}
                </div>
              </div>

              {/* Welcome Text */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Welcome Text</label>
                <input
                  type="text"
                  value={editingWidget.welcomeText}
                  onChange={(e) => updateField("welcomeText", e.target.value)}
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>

              {/* Logo Upload */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Logo URL</label>
                <input
                  type="text"
                  value={editingWidget.logoUrl}
                  onChange={(e) => updateField("logoUrl", e.target.value)}
                  placeholder="https://example.com/logo.png"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>

              {/* Avatar Upload */}
              <div>
                <label className="block text-[11px] font-medium text-ink/50 dark:text-fog/50 mb-1">Avatar URL</label>
                <input
                  type="text"
                  value={editingWidget.avatarUrl}
                  onChange={(e) => updateField("avatarUrl", e.target.value)}
                  placeholder="https://example.com/avatar.png"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>

              {/* Show Reviews toggle */}
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium text-ink/50 dark:text-fog/50">Show Reviews</label>
                <button
                  onClick={() => updateField("showReviews", !editingWidget.showReviews)}
                  className={`relative h-5 w-9 rounded-full transition ${
                    editingWidget.showReviews ? "bg-deep-violet" : "bg-ink/20 dark:bg-fog/20"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                      editingWidget.showReviews ? "translate-x-4" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>
            </div>

            {/* Live preview */}
            <div className="mt-4">
              <WidgetPreview
                position={editingWidget.position}
                primaryColor={editingWidget.primaryColor}
                font={editingWidget.font}
                launcherIcon={editingWidget.launcherIcon}
                welcomeText={editingWidget.welcomeText}
              />
            </div>

            {/* Save */}
            <button
              onClick={saveWidget}
              className="mt-4 w-full rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
            >
              {isCreating ? "Create Widget" : "Save Changes"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
