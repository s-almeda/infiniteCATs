// Base URL for the Flask backend, baked in at build time.
// Unset (the default): requests are same-origin relative paths like /api/graph,
// so they go to whichever domain served the page.
// Set VITE_FLASK_API_URL (e.g. https://cats.shmuh.co) for builds hosted somewhere
// other than the backend, such as the Vercel deployment.
export const API_BASE = (import.meta.env.VITE_FLASK_API_URL ?? '').replace(/\/+$/, '')
