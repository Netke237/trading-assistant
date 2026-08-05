import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SearchProfile, SearchProfileSnapshot } from '@/types/searchProfile';

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

interface SearchProfilesState {
  profiles: SearchProfile[];
  saveProfile:   (name: string, snapshot: SearchProfileSnapshot) => string;
  updateProfile: (id: string, snapshot: SearchProfileSnapshot) => void;
  renameProfile: (id: string, name: string) => void;
  deleteProfile: (id: string) => void;
}

export const useSearchProfilesStore = create<SearchProfilesState>()(
  persist(
    (set) => ({
      profiles: [],
      saveProfile: (name, snapshot) => {
        const now = new Date().toISOString();
        const id = genId();
        set((s) => ({
          profiles: [...s.profiles, { ...snapshot, id, name, createdAt: now, updatedAt: now }],
        }));
        return id;
      },
      updateProfile: (id, snapshot) => set((s) => ({
        profiles: s.profiles.map((p) =>
          p.id === id ? { ...p, ...snapshot, updatedAt: new Date().toISOString() } : p),
      })),
      // Bumps updatedAt too, so a rename reorders the dropdown's
      // most-recently-touched-first sort the same way an edit would.
      renameProfile: (id, name) => set((s) => ({
        profiles: s.profiles.map((p) =>
          p.id === id ? { ...p, name, updatedAt: new Date().toISOString() } : p),
      })),
      deleteProfile: (id) => set((s) => ({
        profiles: s.profiles.filter((p) => p.id !== id),
      })),
    }),
    {
      name: 'bamendjou:search-profiles',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 1,
      partialize: (state) => ({ profiles: state.profiles }),
    },
  ),
);
