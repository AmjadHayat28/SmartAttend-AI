/** Upload limit, matching the API's MAX_UPLOAD_SIZE_MB (8) and the reverse proxy's body limit.
 *  Checked in the browser for instant feedback; the server enforces it regardless. */
export const MAX_UPLOAD_MB = 8;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
