import { reportLocalWriteFailure, reportLocalWriteSuccess } from './settingsSaveStatus';

/** Preserve Storage's format and throw behavior while reporting failed writes. */
export function reportingLocalStorage(label: string): Storage {
  return {
    get length() { return localStorage.length; },
    key: (index) => localStorage.key(index),
    getItem: (key) => localStorage.getItem(key),
    removeItem: (key) => localStorage.removeItem(key),
    clear: () => localStorage.clear(),
    setItem: (key, value) => {
      try {
        localStorage.setItem(key, value);
      } catch (error) {
        reportLocalWriteFailure(key, label, value);
        throw error;
      }
      reportLocalWriteSuccess(key);
    },
  };
}
