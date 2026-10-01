import { useEffect, useState } from 'react';

/**
 * Returns a debounced copy of `value` that updates `delay` ms after the
 * last change. Used to coalesce rapid config edits (e.g. slider drags)
 * into a single API call.
 */
export function useDebounce<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}
