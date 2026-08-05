'use client';

import { useState, useEffect } from 'react';
import { Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { captureCurrentSnapshot, applySearchProfile, stableStringify } from '@/lib/searchProfileSnapshot';
import { SaveProfileDialog } from '@/components/molecules/SaveProfileDialog';
import { RenameProfileDialog } from '@/components/molecules/RenameProfileDialog';
import { ConfirmDialog } from '@/components/molecules/ConfirmDialog';
import styles from './SearchProfileBar.module.css';

export function SearchProfileBar() {
  const screenerMode = useScanStore((s) => s.screenerMode);
  const profiles       = useSearchProfilesStore((s) => s.profiles);
  const updateProfile  = useSearchProfilesStore((s) => s.updateProfile);
  const renameProfile  = useSearchProfilesStore((s) => s.renameProfile);
  const deleteProfile  = useSearchProfilesStore((s) => s.deleteProfile);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // The dropdown re-filters by mode on every screenerMode change — clear the
  // selection so it can't point at an id no longer in its own option list.
  useEffect(() => { setSelectedId(null); }, [screenerMode]);

  // Pre-Breakout has no equivalent of universe/direction/horizon/execution
  // params today (SearchProfile.mode is 'options' | 'stocks' only) — hide
  // the bar entirely rather than force a cast onto a third mode it can't
  // represent.
  if (screenerMode === 'prebreakout') return null;

  const modeProfiles = profiles
    .filter((p) => p.mode === screenerMode)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const selected = modeProfiles.find((p) => p.id === selectedId) ?? null;

  const isDirty = selected
    ? stableStringify(captureCurrentSnapshot(screenerMode)) !==
      stableStringify({
        mode: selected.mode, universe: selected.universe, direction: selected.direction,
        horizonPreset: selected.horizonPreset, holdMin: selected.holdMin, holdMax: selected.holdMax,
        scanOverrides: selected.scanOverrides, scanSettings: selected.scanSettings,
        strategy: selected.strategy, strategyParams: selected.strategyParams,
      })
    : false;

  function handleSelect(id: string) {
    setSelectedId(id || null);
    if (!id) return;
    const p = modeProfiles.find((x) => x.id === id);
    if (p) applySearchProfile(p);
  }

  return (
    <div className={styles.bar}>
      <Text size={12} weight={600}>Search Profile</Text>
      <select
        className={styles.select}
        value={selectedId ?? ''}
        onChange={(e) => handleSelect(e.target.value)}
        aria-label="Search profile"
      >
        <option value="">— none —</option>
        {modeProfiles.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      <button type="button" className={styles.btn} onClick={() => setShowSaveDialog(true)}>
        Save as new…
      </button>

      {selected && (
        <>
          <button
            type="button"
            className={styles.btn}
            disabled={!isDirty}
            onClick={() => updateProfile(selected.id, captureCurrentSnapshot(screenerMode))}
          >
            Update &ldquo;{selected.name}&rdquo;
          </button>
          <button type="button" className={styles.btnGhost} onClick={() => setShowRenameDialog(true)}>
            Rename
          </button>
          <button type="button" className={styles.btnGhost} onClick={() => setShowDeleteConfirm(true)}>
            Delete
          </button>
        </>
      )}

      {modeProfiles.length === 0 && (
        <Text size={11} tone="dim">No saved profiles yet — configure the panel below, then Save as new…</Text>
      )}

      {showSaveDialog && (
        <SaveProfileDialog
          mode={screenerMode}
          onClose={() => setShowSaveDialog(false)}
          onSave={(name) => {
            const id = useSearchProfilesStore.getState().saveProfile(name, captureCurrentSnapshot(screenerMode));
            setSelectedId(id);
            setShowSaveDialog(false);
          }}
        />
      )}
      {showRenameDialog && selected && (
        <RenameProfileDialog
          currentName={selected.name}
          onClose={() => setShowRenameDialog(false)}
          onSave={(name) => { renameProfile(selected.id, name); setShowRenameDialog(false); }}
        />
      )}
      {showDeleteConfirm && selected && (
        <ConfirmDialog
          title={`Delete profile "${selected.name}"?`}
          onCancel={() => setShowDeleteConfirm(false)}
          onConfirm={() => { deleteProfile(selected.id); setSelectedId(null); setShowDeleteConfirm(false); }}
        />
      )}
    </div>
  );
}
