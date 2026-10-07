import {useEffect, useState} from 'react';
import {
  prefersReducedMotion,
  watchReducedMotion,
} from '@/shared/lib/reduced_motion';

export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(prefersReducedMotion);
  useEffect(
    () => watchReducedMotion(() => setReduce(prefersReducedMotion())),
    [],
  );
  return reduce;
}
