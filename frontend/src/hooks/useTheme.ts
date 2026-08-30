import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'astra-theme'

function initialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  return (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? 'dark'
}

/**
 * Light/dark theme. Defaults to dark (the app's original look); the choice is
 * persisted under `astra-theme`. Toggling flips the `.dark` class on <html>;
 * the inline script in index.html applies it before first paint.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const toggle = useCallback(() => {
    setTheme(current => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggle }
}