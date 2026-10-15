/**
 * Every feature folder with a `register.ts` (or `register.tsx`) is imported automatically,
 * so feature modules never need to edit a shared file to add routes, navigation, tabs or panels.
 */
const modules = import.meta.glob('./*/register.{ts,tsx}', { eager: true })
export const FEATURE_COUNT = Object.keys(modules).length
