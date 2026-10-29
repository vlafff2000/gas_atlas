import { pref } from './chartPrefs'

/** Большая группа боковой панели, где собраны «Документы и настройки» (разделы объекта, не модули). */
export const PAGES_GROUP = 'Документы и настройки'

/**
 * Меню боковой панели: одно на весь компьютер, не зависит от выбранного объекта.
 * ``hidden`` — скрытые разделы и модули (по их id), ``groups`` — скрытые большие группы целиком.
 * null — меню ещё не настраивали: тогда берётся состав меню объекта (см. ``hiddenPages`` в api_projects).
 */
export interface MenuPrefs { hidden: string[]; groups: string[] }
export const menuPrefs = pref<MenuPrefs | null>('atlas.menu', null)
