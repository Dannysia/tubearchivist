import { useState } from 'react';

const STORAGE_KEY = 'timeMachine';

const readStored = () => {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
};

const useTimeMachine = (): [boolean, (enabled: boolean) => void] => {
  const [enabled, setEnabled] = useState(readStored);

  const update = (next: boolean) => {
    setEnabled(next);
    try {
      localStorage.setItem(STORAGE_KEY, String(next));
    } catch {}
  };

  return [enabled, update];
};

export default useTimeMachine;
