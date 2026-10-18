import { useEffect, useState } from "react";
import { api } from "../services/api";

/** Object URLs for protected images (fetched with the Authorization header), revoked on change/unmount. */
export function useAuthedBlobUrls(srcs: string[]) {
  const key = srcs.join("|");
  const [urls, setUrls] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const created: string[] = [];
    Promise.all(
      srcs.map((src) =>
        api
          .get<Blob>(src, { responseType: "blob" })
          .then((r) => {
            const url = URL.createObjectURL(r.data);
            created.push(url);
            return [src, url] as const;
          })
          .catch(() => null),
      ),
    ).then((pairs) => {
      if (!cancelled) setUrls(Object.fromEntries(pairs.filter((p): p is readonly [string, string] => p !== null)));
    });
    return () => {
      cancelled = true;
      created.forEach((u) => URL.revokeObjectURL(u));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return urls;
}
