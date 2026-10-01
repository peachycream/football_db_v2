import { useEffect, useMemo, useState } from 'react';
import type { SavedViewSummary, SavedViewState } from '@/types/api';
import {
  listViews,
  createView,
  updateView,
  deleteView,
  getView,
  touchView,
} from '@/lib/api';
import { Button, Popover, Input } from '@/components/ui/primitives';
import { cn } from '@/lib/utils';

interface ViewsMenuProps {
  /** Current AppState slice that gets saved/loaded as a view. */
  currentState: SavedViewState;
  /** Apply the loaded view to the app reducer. */
  onLoad: (state: SavedViewState, view: SavedViewSummary) => void;
  /** The view_id currently loaded, or null if none. */
  currentViewId: number | null;
  /** Becomes null when the loaded view is overwritten / renamed (caller may use). */
  onUnload: () => void;
  /** Whether currentState has drifted from the loaded view's saved state. */
  isDirty: boolean;
  /** Name of the loaded view, for the trigger label and "Update" button. */
  currentViewName: string | null;
}

export function ViewsMenu({
  currentState,
  onLoad,
  currentViewId,
  onUnload,
  isDirty,
  currentViewName,
}: ViewsMenuProps) {
  const [open, setOpen] = useState(false);
  const [views, setViews] = useState<SavedViewSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Save-form local state
  const [showSaveForm, setShowSaveForm] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveDesc, setSaveDesc] = useState('');
  const [saving, setSaving] = useState(false);

  // Fetch list whenever we open the popover (cheap; stays current after edits
  // in other tabs too).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listViews()
      .then((r) => { if (!cancelled) setViews(r.views); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open]);

  // Reset the save-form when popover closes
  useEffect(() => {
    if (!open) {
      setShowSaveForm(false);
      setSaveName('');
      setSaveDesc('');
      setError(null);
    }
  }, [open]);

  const handleLoad = async (summary: SavedViewSummary) => {
    setError(null);
    try {
      const full = await getView(summary.view_id);
      if (!full.config) {
        setError('This view has corrupt config and cannot be loaded.');
        return;
      }
      // Fire-and-forget the timestamp bump; UI doesn't need to wait.
      touchView(summary.view_id).catch(() => { /* non-critical */ });
      onLoad(full.config, summary);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async (summary: SavedViewSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(`Delete "${summary.name}"? This can't be undone.`)) return;
    setError(null);
    try {
      await deleteView(summary.view_id);
      setViews((vs) => vs.filter((v) => v.view_id !== summary.view_id));
      if (currentViewId === summary.view_id) onUnload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleSave = async () => {
    const name = saveName.trim();
    if (!name) {
      setError('Name required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createView({
        name,
        description: saveDesc.trim() || null,
        config: currentState,
      });
      setViews((vs) => [
        { view_id: created.view_id, name: created.name, description: created.description, created_at: created.created_at, last_used: created.last_used },
        ...vs,
      ]);
      // Treat the new save as "loaded" so the menu reflects ownership.
      onLoad(currentState, {
        view_id: created.view_id, name: created.name, description: created.description,
        created_at: created.created_at, last_used: created.last_used,
      });
      setShowSaveForm(false);
      setSaveName('');
      setSaveDesc('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (currentViewId == null) return;
    setError(null);
    try {
      const updated = await updateView(currentViewId, { config: currentState });
      setViews((vs) =>
        vs
          .map((v) => v.view_id === currentViewId ? {
            view_id: updated.view_id, name: updated.name, description: updated.description,
            created_at: updated.created_at, last_used: updated.last_used,
          } : v)
          .sort(sortByRecency),
      );
      onLoad(currentState, {
        view_id: updated.view_id, name: updated.name, description: updated.description,
        created_at: updated.created_at, last_used: updated.last_used,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // Pre-fill save form name with the current view's name + " copy" when a
  // dirty view is being "saved as new", to nudge toward clear naming.
  const handleOpenSaveForm = () => {
    setShowSaveForm(true);
    if (currentViewName && !saveName) {
      setSaveName(isDirty ? `${currentViewName} (copy)` : '');
    }
  };

  const triggerLabel = useMemo(() => {
    if (currentViewName) {
      return isDirty ? `${currentViewName} •` : currentViewName;
    }
    return 'Views';
  }, [currentViewName, isDirty]);

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      align="left"
      className="w-80 max-h-[32rem] flex flex-col"
      trigger={
        <button
          type="button"
          className={cn(
            'h-7 px-2.5 rounded-md text-xs flex items-center gap-1.5',
            'bg-bg-elevated hover:bg-bg-hover border border-border',
            'text-text-muted hover:text-text transition-colors',
            'focus:outline-none focus:ring-1 focus:ring-accent/40',
            currentViewName && 'text-text',
          )}
          title={
            isDirty
              ? 'Loaded view has unsaved changes — click to manage'
              : 'Save and load views'
          }
        >
          <BookmarkIcon />
          <span className="truncate max-w-[12rem]">{triggerLabel}</span>
          <ChevronIcon />
        </button>
      }
    >
      {/* Update / new-save quick actions when a view is loaded */}
      {currentViewId != null && (
        <div className="px-3 py-2 border-b border-border flex items-center gap-2">
          <Button
            variant={isDirty ? 'accent' : 'default'}
            size="sm"
            disabled={!isDirty}
            onClick={handleUpdate}
            className="flex-1"
            title={isDirty ? 'Overwrite the loaded view with the current state' : 'No changes to save'}
          >
            {isDirty ? 'Update loaded view' : '✓ Up to date'}
          </Button>
        </div>
      )}

      {/* Error strip */}
      {error && (
        <div className="px-3 py-1.5 text-[11px] text-error border-b border-border bg-bg-card">
          {error}
        </div>
      )}

      {/* List */}
      <div className="overflow-y-auto flex-1">
        {loading && (
          <div className="px-3 py-4 text-xs text-text-dim text-center">Loading…</div>
        )}
        {!loading && views.length === 0 && (
          <div className="px-3 py-6 text-xs text-text-dim text-center">
            No saved views yet. Save the current view below.
          </div>
        )}
        {!loading && views.map((v) => {
          const isCurrent = v.view_id === currentViewId;
          return (
            <button
              key={v.view_id}
              type="button"
              onClick={() => handleLoad(v)}
              className={cn(
                'w-full text-left px-3 py-2 flex items-start gap-2',
                'hover:bg-bg-elevated transition-colors group',
                isCurrent && 'bg-accent/10',
              )}
              title={v.description ?? undefined}
            >
              <div className="flex-1 min-w-0">
                <div className={cn(
                  'text-xs truncate',
                  isCurrent ? 'text-accent' : 'text-text',
                )}>
                  {v.name}
                </div>
                <div className="text-[10px] text-text-dim mt-0.5 truncate">
                  {v.description ? v.description : (
                    <span className="italic opacity-60">no description</span>
                  )}
                </div>
                <div className="text-[10px] text-text-dim mt-0.5">
                  {formatRelativeTimestamp(v.last_used ?? v.created_at)}
                  {!v.last_used && <span className="opacity-60"> · never opened</span>}
                </div>
              </div>
              <button
                type="button"
                onClick={(e) => handleDelete(v, e)}
                className={cn(
                  'shrink-0 w-6 h-6 rounded flex items-center justify-center',
                  'text-text-dim hover:text-error hover:bg-error/10',
                  'opacity-0 group-hover:opacity-100 transition-opacity',
                )}
                title="Delete this view"
              >
                ✕
              </button>
            </button>
          );
        })}
      </div>

      {/* Save form / button */}
      <div className="border-t border-border">
        {!showSaveForm ? (
          <button
            type="button"
            onClick={handleOpenSaveForm}
            className="w-full px-3 py-2 text-xs text-text-muted hover:text-text hover:bg-bg-elevated transition-colors text-left"
          >
            + Save current view…
          </button>
        ) : (
          <div className="px-3 py-2 space-y-2">
            <Input
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="View name"
              autoFocus
              maxLength={80}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSave();
                if (e.key === 'Escape') setShowSaveForm(false);
              }}
            />
            <Input
              value={saveDesc}
              onChange={(e) => setSaveDesc(e.target.value)}
              placeholder="Description (optional)"
              maxLength={400}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSave();
                if (e.key === 'Escape') setShowSaveForm(false);
              }}
            />
            <div className="flex gap-2 pt-1">
              <Button
                size="sm"
                variant="accent"
                onClick={handleSave}
                disabled={saving || !saveName.trim()}
                className="flex-1"
              >
                {saving ? 'Saving…' : 'Save'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => { setShowSaveForm(false); setError(null); }}
                disabled={saving}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </Popover>
  );
}

/* ──────────────────────────────────────────────────────────────────────
 * Helpers
 * ────────────────────────────────────────────────────────────────────── */

function sortByRecency(a: SavedViewSummary, b: SavedViewSummary): number {
  // Server sort order: last_used DESC NULLS LAST, created_at DESC. Mirror it
  // here so local optimistic updates don't have to refetch.
  const aLast = a.last_used ?? '';
  const bLast = b.last_used ?? '';
  if (aLast && bLast) return aLast < bLast ? 1 : -1;
  if (aLast) return -1;
  if (bLast) return 1;
  return a.created_at < b.created_at ? 1 : -1;
}

/** Renders SQL TIMESTAMPs (e.g. "2025-05-25 12:32:23") as relative. */
function formatRelativeTimestamp(ts: string): string {
  if (!ts) return '';
  // SQLite TIMESTAMP is in UTC despite no Z. Parse as UTC.
  const isoLike = ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z';
  const date = new Date(isoLike);
  if (isNaN(date.getTime())) return ts;
  const diffSec = (Date.now() - date.getTime()) / 1000;
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 86400 * 30) return `${Math.floor(diffSec / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function BookmarkIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="w-3.5 h-3.5 shrink-0"
    >
      <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="w-3 h-3 shrink-0 opacity-60"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
