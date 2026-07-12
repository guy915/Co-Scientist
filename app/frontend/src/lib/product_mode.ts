/** Developer-only extensions are quarantined from the faithful product. */
export const DEVELOPER_MODE =
  import.meta.env.MODE === 'test' ||
  import.meta.env.VITE_DEVELOPER_MODE === 'true';
